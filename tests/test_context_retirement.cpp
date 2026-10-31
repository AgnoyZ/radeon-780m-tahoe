// Execute the staged cleanup implementation; OS objects and hardware observations are explicit fakes.
#include "PhxNativeABI.h"
#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <strings.h>
#include <vector>
using IOReturn = int;
using UInt32 = uint32_t;
using IOOptionBits = uint32_t;
using IOByteCount = uint64_t;
using addr64_t = uint64_t;
static constexpr unsigned kIOMemoryMapperNone = 0x800;
enum { kIOReturnSuccess, kIOReturnNotReady, kIOReturnBadArgument, kIOReturnNotFound };
static std::vector<std::string> events;
static std::set<void *> allocations;
static unsigned frees = 0, lineFlushes = 0, delays = 0, casCalls = 0, lockFrees = 0;
static bool failCasOnce = false;
static void IOFree(void *p, size_t) { assert(allocations.erase(p) == 1); ++frees; events.push_back("free-storage"); std::free(p); }
static bool OSCompareAndSwapPtr(void *old, void *value, void *volatile *where) {
    ++casCalls;
    if (failCasOnce) { failCasOnce = false; return false; }
    if (*where != old) return false;
    *where = value; return true;
}
static void afterLock(int *);
static void IOLockLock(int *p) { assert(p && !*p); *p = 1; afterLock(p); }
static void IOLockUnlock(int *p) { assert(p && *p); *p = 0; }
static void IOLockFree(int *p) { assert(p && !*p); ++lockFrees; }
static void IOLog(const char *, ...) {}
static void IODelay(unsigned);
static void flushLine(void *) { if (!lineFlushes) events.push_back("flush-pages"); ++lineFlushes; }
static unsigned gSysctlUp = 0;
static int sysctl__debug_phxbos_flush = 0, sysctl__debug_phxbos_flush_bytes = 0;
static void sysctl_unregister_oid(int *) {}
struct IOMemoryDescriptor {
    unsigned retains{0}, releases{0}, completes{0};
    void retain() { ++retains; }
    void release() { ++releases; events.push_back("release"); }
    void complete() { ++completes; events.push_back("complete"); }
};
struct PageBytes {
    std::vector<uint8_t> storage = std::vector<uint8_t>(65536 + 4095, 0xa5);
    uint8_t *data() { return reinterpret_cast<uint8_t *>((reinterpret_cast<uintptr_t>(storage.data()) + 4095) & ~uintptr_t(4095)); }
    const uint8_t *data() const { return reinterpret_cast<const uint8_t *>((reinterpret_cast<uintptr_t>(storage.data()) + 4095) & ~uintptr_t(4095)); }
    uint8_t *begin() { return data(); } uint8_t *end() { return data() + 65536; }
    const uint8_t *begin() const { return data(); } const uint8_t *end() const { return data() + 65536; }
    uint8_t &operator[](size_t i) { return data()[i]; }
    const uint8_t &operator[](size_t i) const { return data()[i]; }
};
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {
    PageBytes bytes;
    void *cpu{bytes.data()};
    uint64_t length{65536}, physical{0x200000}, segmentLength{65536};
    unsigned cpuReads{0}, failCpuAfter{0};
    uint64_t getLength() const { return length; }
    void *getBytesNoCopy() { ++cpuReads; return failCpuAfter && cpuReads > failCpuAfter ? nullptr : cpu; }
    addr64_t getPhysicalSegment(uint64_t off, IOByteCount *out, unsigned options) {
        assert(off == 0 && out && options == kIOMemoryMapperNone); *out = segmentLength; return physical;
    }
};
struct IOService { unsigned retains{0}, stops{0}; void retain() { ++retains; } void stop(IOService *) { ++stops; } };
struct IOUserClient { unsigned terminated{0}, baseFreed{0}; void terminate() { ++terminated; } void free() { ++baseFreed; } };
struct FakeMap : IOMemoryDescriptor {
    std::vector<uint64_t> words = std::vector<uint64_t>(256, 0);
    uintptr_t getVirtualAddress() { return reinterpret_cast<uintptr_t>(words.data()); }
};
struct IOExternalMethodArguments {
    uint32_t scalarInputCount{3}, scalarOutputCount{3}, structureInputSize{0}, structureOutputSize{0};
    void *structureInputDescriptor{nullptr}, *structureOutputDescriptor{nullptr};
    uint64_t scalarInput[3]{5, 500000, 0}, scalarOutput[3]{};
};
static constexpr int kMaxMaps = 4096;
#include "retire-shared.inc"
#include "retire-constants.inc"
class PhxBringup : public IOService {
public:
#include "retire-structures.inc"
    VmCtx vm[kMaxCtx]{};
    HwVmid hwv[kNumUserVmids]{};
    GpuQueue gq[2]{};
    bool stopping{false}, stopQuarantined{false};
    PhxRetiredBuffers *quarantinedBuffers{nullptr};
    uint64_t gSeq{10}, ringMc{0}; bool tmrSetUp{false};
    int mutex{0}, smuMutex{0}; int *gpuLock{&mutex}, *smuLock{&smuMutex};
    FakeMap aperture, registers, bells;
    FakeMap *fbAper{&aperture}, *mmio{&registers}, *doorbellMap{&bells};
    IOMemoryDescriptor pciObject; IOMemoryDescriptor *pci{&pciObject};
    IOBufferMemoryDescriptor *sysBuf{nullptr};
    IOBufferMemoryDescriptor root, child;
    std::map<uint32_t, uint32_t> regs;
    bool timeout{false}, allOnes{false}, disableMismatch{false};
    mutable unsigned ackReads{0}; unsigned writes{0}, clears{0}, sessionReleases{0};
    PhxBringup() {
        auto &c = vm[0]; c.busy = true; c.hw = 8; c.phys = 0x200000;
        c.pages = kPtChunks * kPtChunkPages; c.used = 17; c.lastSeq = 5;
        c.chunk[0] = &root; c.chunk[1] = &child;
        child.physical = 0x220000; c.chunkPhys[0] = root.physical; c.chunkPhys[1] = child.physical;
        hwv[0].ctx = 1; hwv[0].lastSeq = 5;
        gq[0].ready = true; gq[0].fenceOff = 0x100; gq[0].tail = 1; gq[0].fseq[0] = 5; gq[0].retiredSeq = 4;
        aperture.words[0x100 / 8] = 4; regs[kRegCtx0Cntl + 8] = 0x01fffe07;
    }
    void wreg(uint32_t reg, uint32_t value) const {
        auto &self = *const_cast<PhxBringup *>(this); assert(mutex && mmio); ++self.writes;
        self.regs[reg] = value;
        if (reg == kRegCtx0Cntl + 8) { assert(value == 0); events.push_back("disable"); }
    }
    uint32_t rreg(uint32_t reg) const {
        assert(mutex && mmio);
        if (reg == kRegInvEng17Ack) {
            ++ackReads;
            if (allOnes) return UINT32_MAX;
            if (timeout) return 0;
            events.push_back("ack"); return 1u << 8;
        }
        if (disableMismatch && reg == kRegCtx0Cntl + 8) return 1;
        auto it = regs.find(reg); return it == regs.end() ? 0 : it->second;
    }
    uint64_t ptTablePhys(VmCtx &c, uint32_t i) { assert(mutex && i == 0); return c.chunk[0] ? c.phys : 0; }
    void clearRing() { ++clears; }
    void releaseSession() { ++sessionReleases; }
    bool vmOwnershipKnown(uint32_t) const;
    bool ptClear(VmCtx &) const;
    bool vmFlushTlb(uint32_t) const;
    void deferClient(uint32_t, uint64_t, PhxRetiredBuffers *);
    void reapContexts(); void reapContextsLocked();
    uint32_t vmidAlloc();
    uint64_t queueFence(const GpuQueue &) const;
    bool queueProgress(const GpuQueue &, uint64_t *) const;
    uint64_t gpuRetiredLocked() const;
    uint64_t gpuRetired() const;
    void stop(IOService *);
};
class IOAccelPhxNativeClient : public IOUserClient {
public:
    using Bo = PhxClientBo;
    struct Map { bool used; };
    PhxBringup *owner;
    int mutex{0}; int *lock{&mutex};
    bool closed{false}, hello{true}, sessionClaimed{true};
    uint32_t vmid{1}; uint64_t lastSeq{5}, emitted{5};
    PhxRetiredBuffers *bufferStorage; Bo *bos; Map *maps{nullptr};
    uint32_t pendFenceHandle{0}, pendFenceOffset{0}; uint64_t pendFenceSeq{0};
    unsigned flushCalls{0};
    IOAccelPhxNativeClient(PhxBringup &p, PhxRetiredBuffers *storage) : owner(&p), bufferStorage(storage), bos(storage->entries) {}
    void reapPending() { assert(mutex); }
    void flushBos() { assert(!closed && bos); ++flushCalls; }
    void boRelease(Bo &); void freeAll(); void closeResources(); IOReturn clientClose(); void free();
    Bo *findBo(uint32_t);
    IOReturn clientMemoryForType(UInt32, IOOptionBits *, IOMemoryDescriptor **);
    IOReturn doWaitSeq(IOExternalMethodArguments *);
};
static PhxBringup *active;
static bool stopAfterLock = false;
static void afterLock(int *lock) {
    if (stopAfterLock && active && lock == active->gpuLock) { active->stopping = true; stopAfterLock = false; }
}
static IOAccelPhxNativeClient *closeOnDelay = nullptr;
static void IODelay(unsigned us) {
    ++delays;
    if (us == 1) assert(active->mutex);
    else {
        assert(us == 100);
        if (closeOnDelay) {
            auto *c = closeOnDelay; closeOnDelay = nullptr;
            active->aperture.words[0x100 / 8] = 5;
            assert(c->clientClose() == kIOReturnSuccess);
        }
    }
}
#include "retire-methods.inc"

static PhxRetiredBuffers *storage(IOMemoryDescriptor &normal, IOMemoryDescriptor &host) {
    auto *p = static_cast<PhxRetiredBuffers *>(std::calloc(1, sizeof(PhxRetiredBuffers)));
    assert(p); allocations.insert(p);
    p->entries[1].md = &normal; p->entries[1].size = 4096;
    p->entries[2].md = &host; p->entries[2].size = 4096; p->entries[2].host = true;
    return p;
}
static void retained(const PhxBringup &p, const IOMemoryDescriptor &normal, const IOMemoryDescriptor &host) {
    assert(p.vm[0].busy && p.vm[0].closing && p.vm[0].retiredBuffers);
    assert(normal.releases == 0 && host.releases == 0 && host.completes == 0 && frees == 0);
    assert(lineFlushes == 0 && p.root.bytes[0] == 0xa5 && p.child.bytes[0] == 0xa5);
}
static void reclaimed(const PhxBringup &p, const IOMemoryDescriptor &normal, const IOMemoryDescriptor &host, bool hadHardware = true, uint32_t pages = 17) {
    assert(!p.vm[0].busy && !p.vm[0].closing && !p.vm[0].retiredBuffers && !p.vm[0].hw);
    assert(normal.releases == 1 && normal.completes == 0 && host.releases == 1 && host.completes == 1);
    assert(frees == 1 && lineFlushes == pages * 4096 / 64 && p.root.releases == 0 && p.child.releases == 0);
    const unsigned rootBytes = std::min(pages, 16u) * 4096, childBytes = pages > 16 ? (pages - 16) * 4096 : 0;
    assert(std::all_of(p.root.bytes.begin(), p.root.bytes.begin() + rootBytes, [](uint8_t b) { return b == 0; }));
    assert(std::all_of(p.root.bytes.begin() + rootBytes, p.root.bytes.end(), [](uint8_t b) { return b == 0xa5; }));
    assert(std::all_of(p.child.bytes.begin(), p.child.bytes.begin() + childBytes, [](uint8_t b) { return b == 0; }));
    assert(std::all_of(p.child.bytes.begin() + childBytes, p.child.bytes.end(), [](uint8_t b) { return b == 0xa5; }));
    if (hadHardware) assert(std::find(events.begin(), events.end(), "ack") < std::find(events.begin(), events.end(), "flush-pages"));
    assert(std::find(events.begin(), events.end(), "flush-pages") < std::find(events.begin(), events.end(), "release"));
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1]; PhxBringup p; active = &p;
    assert(kPtAddrMask == 0x0000fffffffff000ull && kRegCtx0BaseLo == 0x2953 &&
           kRegCtx0StartLo == 0x2973 && kRegCtx0EndLo == 0x2993);
    IOMemoryDescriptor normal, host; auto *buffers = storage(normal, host);
    const bool clientCase = test.rfind("client-", 0) == 0 || test == "wait-after-close" || test == "close-during-wait";
    if (test.rfind("clear-", 0) == 0) {
        auto &c = p.vm[0];
        const uint32_t originalPages = c.pages;
        uint32_t used = 17;
        bool damaged = true;
        p.aperture.words[0x100 / 8] = 5;
        const std::string kinds[] = {"root", "used", "cached"};
        bool matrix = false;
        for (const std::string &kind : kinds) {
            const std::string prefix = "clear-" + kind + "-";
            if (test.rfind(prefix, 0) != 0) continue;
            const std::string fault = test.substr(prefix.size());
            const std::set<std::string> faults = {"short-length", "long-length", "null-cpu", "unaligned-cpu", "cpu-overflow",
                "zero-physical", "unaligned-physical", "high-physical", "physical-overflow", "short-segment",
                "cached-base-mismatch", "physical-alias", "cpu-alias"};
            if (!faults.count(fault)) continue;
            matrix = true;
            if (kind == "cached") c.used = used = 1;
            const unsigned index = kind == "root" ? 0 : 1;
            auto &backing = index == 0 ? p.root : p.child;
            auto &other = index == 0 ? p.child : p.root;
            if (fault == "short-length") backing.length = 65535;
            else if (fault == "long-length") backing.length = 65537;
            else if (fault == "null-cpu") backing.cpu = nullptr;
            else if (fault == "unaligned-cpu") backing.cpu = backing.bytes.data() + 1;
            else if (fault == "cpu-overflow") backing.cpu = reinterpret_cast<void *>(UINTPTR_MAX & ~uintptr_t(4095));
            else if (fault == "zero-physical") backing.physical = 0;
            else if (fault == "unaligned-physical") backing.physical += 1;
            else if (fault == "high-physical") backing.physical = 1ull << 48;
            else if (fault == "physical-overflow") backing.physical = 0x0000fffffffff000ull;
            else if (fault == "short-segment") backing.segmentLength = 65535;
            else if (fault == "cached-base-mismatch") { c.chunkPhys[index] += 4096; if (!index) c.phys = c.chunkPhys[0]; }
            else if (fault == "physical-alias") {
                backing.physical = other.physical + 4096; c.chunkPhys[index] = backing.physical;
                if (!index) c.phys = backing.physical;
            } else if (fault == "cpu-alias") backing.cpu = other.bytes.data() + 4096;
        }
        if (!matrix) {
            if (test == "clear-root-mismatch") c.phys += 4096;
            else if (test == "clear-used-zero") c.used = 0;
            else if (test == "clear-pages-overflow") c.pages += 1;
            else if (test == "clear-stale-base") c.chunkPhys[2] = 0x240000;
            else if (test == "clear-cached-hole") {
                c.used = used = 1; c.chunk[1] = nullptr; c.chunkPhys[1] = 0;
                c.chunk[2] = &p.child; c.chunkPhys[2] = p.child.physical;
            } else if (test == "clear-snapshot") {
                damaged = false; p.root.failCpuAfter = p.child.failCpuAfter = 1;
            } else if (test == "clear-invalid-entries") {
                damaged = false;
                reinterpret_cast<uint64_t *>(p.root.bytes.data())[0] = c.phys | 3;
                reinterpret_cast<uint64_t *>(p.child.bytes.data())[0] = UINT64_MAX;
            } else assert(false && "Unknown clear scenario");
        }
        p.deferClient(1, 5, buffers);
        assert(!c.hw && !p.hwv[0].ctx && !p.hwv[0].faulted && p.ackReads == 1 && p.writes);
        if (damaged) {
            retained(p, normal, host);
            assert(!p.root.releases && !p.child.releases);
            assert(std::all_of(p.root.bytes.begin(), p.root.bytes.end(), [](uint8_t b) { return b == 0xa5; }));
            assert(std::all_of(p.child.bytes.begin(), p.child.bytes.end(), [](uint8_t b) { return b == 0xa5; }));
            // Repair only fixture backing; the actual closing/retirement ledger must survive the refusal.
            p.root.cpu = p.root.bytes.data(); p.child.cpu = p.child.bytes.data();
            p.root.length = p.child.length = p.root.segmentLength = p.child.segmentLength = 65536;
            p.root.physical = c.phys = c.chunkPhys[0] = 0x200000;
            p.child.physical = c.chunkPhys[1] = 0x220000;
            c.chunk[1] = &p.child; c.chunk[2] = nullptr; c.chunkPhys[2] = 0;
            c.pages = originalPages; c.used = used;
            p.reapContexts();
        } else if (test == "clear-snapshot") assert(p.root.cpuReads == 1 && p.child.cpuReads == 1);
        reclaimed(p, normal, host, true, used);
        p.reapContexts(); reclaimed(p, normal, host, true, used);
    } else if (test.rfind("shutdown-", 0) == 0) {
        p.gq[0].ready = false; p.vm[0].busy = false; p.vm[0].hw = 0; p.hwv[0] = PhxBringup::HwVmid{};
        IOBufferMemoryDescriptor system; p.sysBuf = &system;
        const bool noLock = test.rfind("shutdown-no-lock-", 0) == 0;
        const bool cold = test == "shutdown-no-lock-cold";
        if (noLock) p.gpuLock = nullptr;
        if (test == "shutdown-orphan-slot") p.hwv[0].ctx = 1;
        else if (test == "shutdown-faulted-slot") p.hwv[0].faulted = true;
        else if (test == "shutdown-no-lock-context") p.vm[0].busy = true;
        else if (test == "shutdown-no-lock-queue") p.gq[0].ready = true;
        else if (test == "shutdown-no-lock-firmware") p.ringMc = 0x300000;
        else if (test == "shutdown-no-lock-tmr") p.tmrSetUp = true;
        else if (test == "shutdown-no-lock-ledger" || test == "shutdown-no-lock-repeat") p.quarantinedBuffers = buffers;
        else assert(cold && "Unknown shutdown scenario");
        p.stop(nullptr);
        assert(p.stopping && p.stops == 1 && !normal.releases && !host.completes && !host.releases && !frees && !lineFlushes);
        if (cold) {
            assert(!p.stopQuarantined && !p.retains && p.clears == 1 && lockFrees == 1);
            assert(!p.gpuLock && !p.smuLock && !p.mmio && !p.fbAper && !p.doorbellMap && !p.pci && !p.sysBuf);
            assert(p.root.releases == 1 && p.child.releases == 1 && system.releases == 1);
            assert(p.registers.releases == 1 && p.aperture.releases == 1 && p.bells.releases == 1 && p.pciObject.releases == 1);
        } else {
            assert(p.stopQuarantined && p.retains == 1 && !p.clears && !lockFrees);
            assert((p.gpuLock == nullptr) == noLock && p.smuLock && p.mmio && p.fbAper && p.doorbellMap && p.pci && p.sysBuf);
            assert(!p.root.releases && !p.child.releases && !system.releases);
            assert(!p.registers.releases && !p.aperture.releases && !p.bells.releases && !p.pciObject.releases);
            assert(!p.gpuReady() && !p.vmCtx(1));
            if (test == "shutdown-no-lock-repeat") {
                p.stop(nullptr);
                assert(p.retains == 1 && p.stops == 2 && !p.clears && !lockFrees && p.quarantinedBuffers == buffers);
                assert(!p.root.releases && !p.child.releases && !system.releases && p.mmio && p.smuLock);
            }
        }
    } else if (clientCase) {
        IOAccelPhxNativeClient c(p, buffers);
        if (test == "client-pending-bo-close") { c.bos[1].pendingFree = true; c.bos[2].pendingFree = true; }
        if (test == "client-no-vmid") c.vmid = 0;
        if (test == "client-close-complete") p.aperture.words[0x100 / 8] = 5;
        if (test == "close-during-wait") {
            closeOnDelay = &c; IOExternalMethodArguments args;
            assert(c.doWaitSeq(&args) == kIOReturnNotReady && c.flushCalls == 0);
            reclaimed(p, normal, host);
        } else {
            if (test == "client-destructor-pending") c.free();
            else assert(c.clientClose() == kIOReturnSuccess);
            if (test == "client-close-then-free") c.free();
            if (test == "client-repeat-close") assert(c.clientClose() == kIOReturnSuccess);
            if (test == "wait-after-close") {
                IOExternalMethodArguments args; assert(c.doWaitSeq(&args) == kIOReturnNotReady && c.flushCalls == 0);
            }
            if (test == "client-memory-after-close") {
                IOOptionBits options = 77; IOMemoryDescriptor *memory = nullptr;
                assert(c.clientMemoryForType(1, &options, &memory) == kIOReturnNotReady);
                assert(!memory && options == 77 && !normal.retains);
            }
            if (test == "client-no-vmid") {
                assert(normal.releases == 1 && host.completes == 1 && host.releases == 1);
                assert(!p.vm[0].closing && !lineFlushes); c.free(); assert(frees == 1);
            } else if (test == "client-close-complete") reclaimed(p, normal, host);
            else {
                retained(p, normal, host);
                if (test == "client-pending-bo-close") {
                    assert(p.vm[0].retiredBuffers->entries[1].pendingFree);
                    assert(p.vm[0].retiredBuffers->entries[2].pendingFree);
                    p.aperture.words[0x100 / 8] = 5; p.reapContexts(); reclaimed(p, normal, host);
                }
            }
        }
        assert(c.closed && c.mutex == 0 && p.mutex == 0 && p.sessionReleases == 1);
        if (test != "client-no-vmid") assert(!c.bos && !c.bufferStorage && !c.vmid);
    } else if (test.rfind("stop-", 0) == 0) {
        if (test != "stop-cold") p.deferClient(1, 5, buffers);
        else { p.gq[0].ready = false; p.vm[0].busy = false; p.vm[0].hw = 0; p.hwv[0] = PhxBringup::HwVmid{}; }
        if (test == "stop-faulted") { p.aperture.words[0x100 / 8] = 5; p.timeout = true; }
        if (test == "stop-orphan") p.quarantinedBuffers = buffers;
        p.stop(nullptr);
        if (test == "stop-cold") {
            assert(!p.stopQuarantined && p.clears == 1 && !p.gpuLock && p.root.releases == 1);
        } else {
            retained(p, normal, host);
            assert(p.stopQuarantined && p.stopping && !p.gpuReady() && !p.vmCtx(1));
            assert(p.retains == 1 && p.clears == 0 && p.gpuLock && p.mmio && p.fbAper && !p.root.releases);
            if (test == "stop-repeat") { p.stop(nullptr); assert(p.retains == 1 && p.stops == 2); }
        }
    } else {
        uint32_t handle = 1; uint64_t seq = 5;
        const bool orphan = test == "bad-handle" || test == "inactive-handle" || test == "future-client-sequence" ||
            test == "duplicate-close-transfer" || test == "no-lock-quarantine" || test == "atomic-quarantine-retry";
        if (orphan) {
            if (test == "bad-handle" || test == "atomic-quarantine-retry") handle = PhxBringup::kMaxCtx + 1;
            if (test == "inactive-handle") p.vm[0].busy = false;
            if (test == "future-client-sequence") seq = p.gSeq + 1;
            if (test == "duplicate-close-transfer") p.vm[0].closing = true;
            if (test == "no-lock-quarantine") p.gpuLock = nullptr;
            if (test == "atomic-quarantine-retry") failCasOnce = true;
            p.deferClient(handle, seq, buffers);
            assert(p.quarantinedBuffers == buffers && !normal.releases && !host.completes && !frees && !lineFlushes);
            assert(casCalls == (test == "atomic-quarantine-retry" ? 2u : 1u));
        } else {
            bool expectRelease = test == "defer-complete" || test == "partial-last-chunk" || test == "double-reap" ||
                test == "unbound-context" || test == "zero-submissions" || test == "two-queues-complete" ||
                test == "mixed-buffer-release" || test == "empty-buffer-container";
            if (expectRelease || test == "ack-timeout" || test == "ack-retry" || test == "ack-all-ones" ||
                test == "disable-mismatch" || test == "disable-retry" || test == "faulted-peer" ||
                test == "faulted-peer-recovered" || test == "invalid-owner" || test == "invalid-hardware-id" ||
                test == "invalid-pages" || test == "missing-chunk" || test == "unbound-peer-invalid-hardware") p.aperture.words[0x100 / 8] = 5;
            if (test == "zero-submissions") { p.vm[0].lastSeq = seq = 0; p.vm[0].hw = 0; p.hwv[0] = PhxBringup::HwVmid{}; p.gq[0].ready = false; }
            if (test == "driver-last-sequence") seq = 0;
            if (test == "client-last-sequence") { p.vm[0].lastSeq = 0; p.aperture.words[0x100 / 8] = 4; }
            if (test == "no-aperture") p.fbAper = nullptr;
            if (test == "no-mmio") p.mmio = nullptr;
            if (test == "no-queues") p.gq[0].ready = false;
            if (test == "future-fence") p.aperture.words[0x100 / 8] = p.gSeq + 1;
            if (test == "ack-timeout" || test == "ack-retry") p.timeout = true;
            if (test == "ack-all-ones") p.allOnes = true;
            if (test == "disable-mismatch" || test == "disable-retry") p.disableMismatch = true;
            if (test == "unbound-context") { p.vm[0].hw = 0; p.hwv[0] = PhxBringup::HwVmid{}; }
            if (test == "faulted-peer" || test == "faulted-peer-recovered") p.hwv[1].faulted = true;
            if (test == "unbound-peer-invalid-hardware") { p.vm[1].busy = true; p.vm[1].hw = 7; }
            if (test == "invalid-owner") p.hwv[0].ctx = 2;
            if (test == "invalid-hardware-id") p.vm[0].hw = 7;
            if (test == "invalid-pages") p.vm[0].used = p.vm[0].pages + 1;
            if (test == "missing-chunk") p.vm[0].chunk[1] = nullptr;
            if (test == "two-queues-pending" || test == "two-queues-complete") {
                p.gq[0].fseq[0] = 4; p.gq[0].retiredSeq = 3; p.aperture.words[0x100 / 8] = 4;
                p.gq[1].ready = true; p.gq[1].tail = 1; p.gq[1].fseq[0] = 5; p.gq[1].fenceOff = 0x108; p.gq[1].retiredSeq = 4;
                p.aperture.words[0x108 / 8] = test == "two-queues-complete" ? 5 : 4;
            }
            if (test == "empty-buffer-container") { buffers->entries[1] = PhxClientBo{}; buffers->entries[2] = PhxClientBo{}; }
            p.deferClient(handle, seq, buffers);
            if (test == "empty-buffer-container") assert(frees == 1 && !normal.releases && !host.completes && !p.vm[0].busy);
            else if (expectRelease) reclaimed(p, normal, host, test != "unbound-context" && test != "zero-submissions");
            else retained(p, normal, host);
            if (test == "late-completion" || test == "ack-retry" || test == "disable-retry" || test == "faulted-peer-recovered") {
                p.aperture.words[0x100 / 8] = 5; p.timeout = false; p.disableMismatch = false; p.hwv[1].faulted = false;
                p.reapContexts(); reclaimed(p, normal, host);
            }
            if (test == "alloc-pending" || test == "alloc-reclaims" || test == "alloc-stopping-after-lock") {
                for (unsigned i = 1; i < PhxBringup::kMaxCtx; ++i) p.vm[i].busy = true;
                if (test == "alloc-reclaims") p.aperture.words[0x100 / 8] = 5;
                if (test == "alloc-stopping-after-lock") { p.aperture.words[0x100 / 8] = 5; stopAfterLock = true; }
                const uint32_t allocated = p.vmidAlloc();
                assert(allocated == (test == "alloc-reclaims" ? 1u : 0u));
                if (allocated) assert(frees == 1 && host.completes == 1 && p.vm[0].busy && !p.vm[0].closing && !p.vm[0].retiredBuffers);
                else retained(p, normal, host);
            }
            if (test == "double-reap") { p.reapContexts(); reclaimed(p, normal, host); }
            if (test == "ack-timeout") assert(p.ackReads == 1000 && delays == 999 && p.hwv[0].faulted);
            if (test == "disable-mismatch") assert(!p.ackReads && p.hwv[0].faulted);
        }
    }
    assert(!p.mutex && !p.smuMutex);
    // Host fixture teardown only: deliberately retained fake allocations are not actual kernel leaks.
    for (void *allocation : allocations) std::free(allocation);
    allocations.clear();
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
