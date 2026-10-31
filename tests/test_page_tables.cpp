// Run the staged allocator/walker; all descriptor backing and physical observations are host fakes.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <strings.h>
#include <vector>
using IOByteCount = uint64_t;
using addr64_t = uint64_t;
using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnVMError, kIOReturnNoMemory };
static constexpr unsigned kIODirectionInOut = 3, kIOMemoryPhysicallyContiguous = 0x10;
static constexpr unsigned kIOMemoryMapperNone = 0x800;
static void *kernel_task = reinterpret_cast<void *>(1);
static void flushLine(void *);
static void afterLock();
static void IOLockLock(int *p) { assert(p && !*p); *p = 1; afterLock(); }
static void IOLockUnlock(int *p) { assert(p && *p); *p = 0; }
struct PhxRetiredBuffers;
#include "pt-constants.inc"
struct IOBufferMemoryDescriptor {
    void *storage{nullptr}, *cpu{nullptr};
    uint64_t length{65536}, physical{0}, segmentLength{65536};
    unsigned releases{0}, zeroFlushes{0}, segmentCalls{0};
    explicit IOBufferMemoryDescriptor(uint64_t pa) : physical(pa) {
        assert(posix_memalign(&storage, 4096, 65536) == 0);
        cpu = storage;
        std::memset(storage, 0xa5, 65536);
    }
    ~IOBufferMemoryDescriptor() { std::free(storage); }
    uint64_t getLength() const { return length; }
    void *getBytesNoCopy() const { return cpu; }
    uint64_t getPhysicalSegment(uint64_t off, IOByteCount *out, unsigned options) {
        assert(off == 0 && out && options == kIOMemoryMapperNone);
        assert(!releases); ++segmentCalls; *out = segmentLength; return physical;
    }
    void release() { assert(!releases); ++releases; }
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void *, unsigned, uint32_t, uint64_t);
};
static std::vector<std::unique_ptr<IOBufferMemoryDescriptor>> descriptors;
static IOBufferMemoryDescriptor *nextDescriptor = nullptr, *pendingDescriptor = nullptr;
static uint64_t nextPhysical = 0x200000;
static unsigned allocationCalls = 0, allocationFailures = 0, flushes = 0;
static IOBufferMemoryDescriptor *descriptor() {
    descriptors.emplace_back(new IOBufferMemoryDescriptor(nextPhysical));
    nextPhysical += 0x20000;
    return descriptors.back().get();
}
IOBufferMemoryDescriptor *IOBufferMemoryDescriptor::inTaskWithPhysicalMask(void *task, unsigned flags, uint32_t size, uint64_t mask) {
    assert(task == kernel_task && flags == (kIODirectionInOut | kIOMemoryPhysicallyContiguous));
    assert(size == 65536 && mask == kPtAddrMask); ++allocationCalls;
    if (allocationFailures) { --allocationFailures; return nullptr; }
    auto *b = nextDescriptor ? nextDescriptor : descriptor();
    nextDescriptor = nullptr; pendingDescriptor = b; return b;
}
class PhxBringup {
public:
#include "pt-structures.inc"
    VmCtx vm[kMaxCtx]{};
    int mutex{0}; int *gpuLock{&mutex};
    bool ready{true}, stopping{false}; unsigned reaps{0};
    bool gpuReady() const { return ready && !stopping; }
    void reapContextsLocked() { assert(mutex); ++reaps; }
    uint64_t *ptTable(const VmCtx &, uint64_t) const;
    uint64_t ptTablePhys(VmCtx &, uint32_t);
    uint64_t *vmPte(VmCtx &, uint64_t, bool, IOReturn * = nullptr);
    uint32_t vmidAlloc();
};
static PhxBringup *active;
static bool stopAfterLock = false;
static void afterLock() { if (stopAfterLock) { active->stopping = true; stopAfterLock = false; } }
static void flushLine(void *address) {
    ++flushes;
    const auto pointer = reinterpret_cast<uintptr_t>(address);
    bool owned = false;
    for (const auto &b : descriptors) {
        const auto base = reinterpret_cast<uintptr_t>(b->storage);
        if (!b->releases && pointer >= base && pointer - base < 65536) owned = true;
    }
    assert(owned);
    if (pendingDescriptor && !pendingDescriptor->releases && pendingDescriptor->zeroFlushes < 1024) {
        auto &b = *pendingDescriptor;
        assert(address == static_cast<uint8_t *>(b.storage) + b.zeroFlushes * 64);
        if (!b.zeroFlushes)
            assert(std::all_of(static_cast<uint8_t *>(b.storage), static_cast<uint8_t *>(b.storage) + 65536,
                               [](uint8_t value) { return value == 0; }));
        for (const auto &c : active->vm) for (const auto *published : c.chunk) assert(published != &b);
        ++b.zeroFlushes;
    }
}
#include "pt-methods.inc"

static void root(PhxBringup &p) {
    auto &c = p.vm[0];
    c.phys = p.ptTablePhys(c, 0); assert(c.phys);
    c.pages = p.kPtChunks * p.kPtChunkPages; c.used = 1;
}
static uint64_t *page(PhxBringup::VmCtx &c, unsigned index) {
    assert(c.chunk[index / 16]);
    return reinterpret_cast<uint64_t *>(static_cast<uint8_t *>(c.chunk[index / 16]->storage) + (index % 16) * 4096);
}
static std::vector<uint8_t> snapshot(const IOBufferMemoryDescriptor &b) {
    const auto *p = static_cast<const uint8_t *>(b.storage); return {p, p + 65536};
}
static void corrupt(IOBufferMemoryDescriptor &b, const std::string &mode) {
    if (mode == "short-length") b.length = 65535;
    else if (mode == "long-length") b.length = 65537;
    else if (mode == "null-cpu") b.cpu = nullptr;
    else if (mode == "unaligned-cpu") b.cpu = static_cast<uint8_t *>(b.storage) + 8;
    else if (mode == "cpu-overflow") b.cpu = reinterpret_cast<void *>(UINTPTR_MAX - 4095);
    else if (mode == "zero-physical") b.physical = 0;
    else if (mode == "unaligned-physical") b.physical |= 8;
    else if (mode == "high-physical") b.physical = 1ull << 48;
    else if (mode == "physical-overflow") b.physical = kPtAddrMask - 4096;
    else if (mode == "short-segment") b.segmentLength = 65535;
    else assert(false);
}
static void secondChunk(PhxBringup &p) {
    auto &c = p.vm[0]; c.used = 16;
    assert(p.ptTablePhys(c, 16)); c.used = 17;
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1]; PhxBringup p; active = &p;
    auto &c = p.vm[0];
    if (test.rfind("root-", 0) == 0) {
        if (test == "root-cached" || test == "root-reused" || test == "root-invalid-cached" || test == "root-skips-invalid") root(p);
        if (test == "root-allocation-fails") allocationFailures = p.kMaxCtx;
        if (test == "root-busy") for (auto &context : p.vm) context.busy = true;
        if (test == "root-stopping") p.stopping = true;
        if (test == "root-stops-after-lock") stopAfterLock = true;
        if (test == "root-invalid-cached" || test == "root-skips-invalid") c.chunk[0]->length = 1;
        if (test == "root-invalid-cached") for (unsigned i = 1; i < p.kMaxCtx; ++i) p.vm[i].busy = true;
        const unsigned beforeAlloc = allocationCalls, beforeFlush = flushes;
        const uint32_t result = p.vmidAlloc(); assert(p.mutex == 0);
        if (test == "root-skips-invalid") {
            assert(result == 2 && p.vm[1].busy && !c.busy && !c.chunk[0]->releases);
        } else if (test == "root-fresh" || test == "root-cached" || test == "root-reused") {
            assert(result == 1 && c.busy && !c.closing && c.used == 1 && c.phys == c.chunkPhys[0]);
            assert(c.pages == 1024 && c.hw == 0 && c.lastSeq == 0 && c.retireSeq == 0 && !c.retiredBuffers);
            if (test == "root-fresh") assert(allocationCalls == beforeAlloc + 1 && flushes == beforeFlush + 1024);
            else assert(allocationCalls == beforeAlloc && flushes == beforeFlush);
            if (test == "root-reused") {
                c.busy = false; assert(p.vmidAlloc() == 1 && c.busy && allocationCalls == beforeAlloc);
            }
        } else {
            assert(result == 0 && flushes == beforeFlush);
            if (test == "root-invalid-cached") assert(!c.chunk[0]->releases && !c.busy);
            else if (test != "root-busy") assert(!c.busy && !c.chunk[0]);
        }
    } else if (test.rfind("backing-", 0) == 0) {
        auto *b = descriptor(); uint64_t pa = 123; uint8_t *cpu = reinterpret_cast<uint8_t *>(1);
        if (test == "backing-null-output") {
            assert(!phxPtBacking(b, 65536, nullptr, &cpu)); assert(!phxPtBacking(b, 65536, &pa, nullptr));
        } else {
            const unsigned size = test == "backing-zero-size" ? 0 : test == "backing-bad-size" ? 65535 : 65536;
            assert(!phxPtBacking(test == "backing-null" ? nullptr : b, size, &pa, &cpu));
            assert(pa == 0 && cpu == nullptr);
        }
        assert(!b->releases && !allocationCalls && !flushes);
    } else {
        root(p); const auto originalRoot = snapshot(*c.chunk[0]);
        const unsigned beforeAlloc = allocationCalls, beforeFlush = flushes;
        const auto dash = test.find('-'); const std::string kind = test.substr(0, dash), mode = test.substr(dash + 1);
        const bool corruption = mode == "short-length" || mode == "long-length" || mode == "null-cpu" ||
            mode == "unaligned-cpu" || mode == "cpu-overflow" || mode == "zero-physical" ||
            mode == "unaligned-physical" || mode == "high-physical" || mode == "physical-overflow" || mode == "short-segment";
        if (corruption && (kind == "fresh" || kind == "cached" || kind == "lookup")) {
            auto *b = kind == "fresh" ? descriptor() : c.chunk[0]; corrupt(*b, mode);
            const auto unchanged = snapshot(*b);
            if (kind == "fresh") { c.used = 16; nextDescriptor = b; assert(!p.ptTablePhys(c, 16)); }
            else if (kind == "cached") assert(!p.ptTablePhys(c, 0));
            else assert(!p.ptTable(c, c.phys));
            assert(b->releases == (kind == "fresh" ? 1u : 0u) && snapshot(*b) == unchanged);
            assert(!c.chunk[1] && !c.chunkPhys[1] && flushes == beforeFlush);
            assert(snapshot(*c.chunk[0]) == originalRoot);
        } else if (test == "fresh-physical-alias" || test == "fresh-cpu-alias") {
            auto *b = descriptor(); c.used = 16; nextDescriptor = b;
            if (test == "fresh-physical-alias") b->physical = c.phys;
            else b->cpu = c.chunk[0]->cpu;
            assert(!p.ptTablePhys(c, 16) && b->releases == 1 && !c.chunk[0]->releases);
            assert(!c.chunk[1] && !c.chunkPhys[1] && flushes == beforeFlush && snapshot(*c.chunk[0]) == originalRoot);
        } else if (test == "cached-physical-alias" || test == "cached-cpu-alias" || test == "lookup-alias") {
            secondChunk(p); auto *b = c.chunk[1];
            if (test == "cached-cpu-alias") b->cpu = c.chunk[0]->cpu;
            else b->physical = c.chunkPhys[1] = c.phys;
            const unsigned saved = flushes;
            if (test == "lookup-alias") assert(!p.ptTable(c, c.phys));
            else assert(!p.ptTablePhys(c, 0));
            assert(!b->releases && !c.chunk[0]->releases && flushes == saved);
        } else if (test == "allocate-next-chunk") {
            c.used = 16; const uint64_t pa = p.ptTablePhys(c, 16);
            assert(pa == c.chunkPhys[1] && c.chunk[1] && c.used == 16 && !p.ptTable(c, pa));
            ++c.used; assert(p.ptTable(c, pa) == page(c, 16));
            assert(allocationCalls == beforeAlloc + 1 && flushes == beforeFlush + 1024);
        } else if (test == "allocate-last-page") {
            c.phys = c.chunkPhys[0] = c.chunk[0]->physical = kPtAddrMask - 15 * 4096;
            c.used = 16; assert(p.ptTablePhys(c, 15) == kPtAddrMask);
            assert(p.ptTable(c, kPtAddrMask) == page(c, 15));
        } else if (test == "allocate-cached") {
            page(c, 0)[500] = 0x123456789ull;
            assert(p.ptTablePhys(c, 0) == c.phys && page(c, 0)[500] == 0x123456789ull);
            assert(allocationCalls == beforeAlloc && flushes == beforeFlush);
        } else if (test == "allocate-capacity" || test == "allocate-skipped-index" || test == "allocate-large-pages" ||
                   test == "allocate-used-overflow" || test == "allocate-missing-prefix" || test == "allocate-stale-physical") {
            unsigned index = 0;
            if (test == "allocate-capacity") c.used = index = 1024;
            if (test == "allocate-skipped-index") index = 2;
            if (test == "allocate-large-pages") c.pages = 1025;
            if (test == "allocate-used-overflow") c.used = c.pages + 1;
            if (test == "allocate-missing-prefix") c.used = index = 32;
            if (test == "allocate-stale-physical") c.chunkPhys[1] = 0x123000;
            assert(!p.ptTablePhys(c, index) && allocationCalls == beforeAlloc && flushes == beforeFlush);
        } else if (test.rfind("lookup-", 0) == 0) {
            uint64_t pa = c.phys;
            if (test == "lookup-last-used") { c.used = 16; pa += 15 * 4096; }
            if (test == "lookup-unused") pa += 4096;
            if (test == "lookup-end") pa += 65536;
            if (test == "lookup-before") pa -= 4096;
            if (test == "lookup-misaligned") pa += 8;
            if (test == "lookup-high") pa = 1ull << 48;
            if (test == "lookup-zero") pa = 0;
            if (test == "lookup-no-used") c.used = 0;
            if (test == "lookup-used-overflow") c.used = 1025;
            if (test == "lookup-pages-overflow") c.pages = 1025;
            if (test == "lookup-missing-chunk") c.used = 17;
            if (test == "lookup-changed-physical") c.chunk[0]->physical += 4096;
            auto *result = p.ptTable(c, pa);
            if (test == "lookup-root") assert(result == page(c, 0));
            else if (test == "lookup-last-used") assert(result == page(c, 15));
            else assert(!result);
            assert(allocationCalls == beforeAlloc && flushes == beforeFlush && snapshot(*c.chunk[0]) == originalRoot);
        } else if (test == "walk-partial-allocation" || test == "allocate-partial-retry") {
            c.used = 15; allocationFailures = 1;
            assert(!p.vmPte(c, 0, true) && c.used == 16 && !c.chunk[1]);
            assert(page(c, 0)[0] == ((c.phys + 15 * 4096) | 7) && page(c, 15)[0] == 0);
            assert(flushes == beforeFlush + 1 && !c.chunk[0]->releases);
            if (test == "allocate-partial-retry") {
                assert(p.vmPte(c, 0, true) == page(c, 17));
                assert(c.used == 18 && c.chunk[1] && !c.chunk[1]->releases);
            }
        } else if (test == "walk-high-va" || test == "walk-zero-root" || test == "walk-root-mismatch" || test == "walk-capacity" || test == "walk-no-allocate") {
            if (test == "walk-zero-root") c.phys = 0;
            if (test == "walk-root-mismatch") c.phys += 4096;
            if (test == "walk-capacity") c.pages = 1;
            assert(!p.vmPte(c, test == "walk-high-va" ? 1ull << 48 : 0, test != "walk-no-allocate"));
            assert(c.used == 1 && allocationCalls == beforeAlloc && flushes == beforeFlush);
        } else if (test == "walk-poisoned-invalid" || test == "walk-zero-child" || test == "walk-foreign-child" || test == "walk-unused-child" ||
                   test == "walk-root-cycle" || test == "walk-parent-cycle" || test == "walk-three-level-cycle") {
            uint64_t entry = 2;
            if (test == "walk-zero-child") entry = 7;
            if (test == "walk-foreign-child") entry = 0x7000007;
            if (test == "walk-unused-child") entry = (c.phys + 4096) | 7;
            if (test == "walk-root-cycle") entry = c.phys | 7;
            if (test == "walk-parent-cycle" || test == "walk-three-level-cycle") {
                c.used = test == "walk-parent-cycle" ? 2 : 3;
                entry = (c.phys + 4096) | 7;
                page(c, 1)[0] = (c.phys + (test == "walk-parent-cycle" ? 4096 : 8192)) | 7;
                if (c.used == 3) page(c, 2)[0] = c.phys | 7;
            }
            page(c, 0)[0] = entry; const auto saved = snapshot(*c.chunk[0]); const unsigned used = c.used;
            assert(!p.vmPte(c, 0, true) && c.used == used && snapshot(*c.chunk[0]) == saved);
            assert(allocationCalls == beforeAlloc && flushes == beforeFlush);
        } else if (test.rfind("walk-bad-flags-", 0) == 0) {
            assert(p.vmPte(c, 0, true)); const unsigned bit = std::stoul(test.substr(15));
            page(c, 0)[0] ^= 1ull << bit;
            const unsigned saved = flushes; const auto unchanged = snapshot(*c.chunk[0]);
            assert(!p.vmPte(c, 0, true) && c.used == 4 && snapshot(*c.chunk[0]) == unchanged && flushes == saved);
        } else if (test == "walk-allocate" || test == "walk-read" || test == "walk-repeat" || test == "walk-sibling" ||
                   test == "walk-distant" || test == "walk-last-va" || test == "walk-low-last-byte") {
            const uint64_t va = test == "walk-last-va" ? (1ull << 48) - 1 : test == "walk-low-last-byte" ? 4095 : 0;
            auto *leaf = p.vmPte(c, va, true);
            assert(leaf == page(c, 3) + ((va >> 12) & 511) && c.used == 4 && *leaf == 0);
            assert(flushes == beforeFlush + 3 && allocationCalls == beforeAlloc);
            *leaf = 0x400077; const unsigned saved = flushes;
            assert(p.vmPte(c, va, test != "walk-read") == leaf && *leaf == 0x400077 && flushes == saved);
            if (test == "walk-sibling") { assert(p.vmPte(c, 1ull << 21, true) == page(c, 4)); assert(c.used == 5); }
            if (test == "walk-distant") { assert(p.vmPte(c, 1ull << 39, true) == page(c, 6)); assert(c.used == 7); }
        } else assert(false);
    }
    for (const auto &b : descriptors) assert(b->releases <= 1);
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
