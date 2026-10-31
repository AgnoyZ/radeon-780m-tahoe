// Execute staged methods; descriptor backing, page tables, MMIO and queue completion are host fakes.
#include "PhxNativeABI.h"
#include "PhxHardwarePolicy.hpp"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <strings.h>
#include <vector>
using IOReturn = int;
using IOByteCount = uint64_t;
using addr64_t = uint64_t;
enum { kIOReturnSuccess, kIOReturnNotReady, kIOReturnBadArgument, kIOReturnNotFound,
       kIOReturnBusy, kIOReturnTimeout, kIOReturnNoMemory, kIOReturnVMError,
       kIOReturnExclusiveAccess, kIOReturnUnsupported, kIOReturnNoResources };
static constexpr unsigned kIOMemoryMapperNone = 0;
static unsigned flushes = 0, delays = 0;
static void IOLockLock(int *p) { assert(p && !*p); *p = 1; }
static void IOLockUnlock(int *p) { assert(p && *p); *p = 0; }
static void IODelay(unsigned us) { assert(us == 1); ++delays; }
static void flushLine(void *) { ++flushes; }
static void IOLog(const char *, ...) {}
struct IOMemoryDescriptor {
    uint64_t length{8192}, physical{0x400000}, segmentLength{4096};
    unsigned calls{0}, badCall{0}, releases{0}, completes{0};
    uint64_t getLength() const { return length; }
    uint64_t getPhysicalSegment(uint64_t off, IOByteCount *lengthOut, unsigned options) {
        assert(options == kIOMemoryMapperNone); ++calls; *lengthOut = segmentLength;
        if (badCall && calls == badCall) return 0;
        return physical ? physical + off : 0;
    }
    void release() { assert(!releases); ++releases; }
    void complete() { assert(!completes); ++completes; }
};
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {};
struct FakeMap {
    std::vector<uint64_t> words = std::vector<uint64_t>(128, 0);
    uintptr_t getVirtualAddress() { return reinterpret_cast<uintptr_t>(words.data()); }
};
struct IOExternalMethodArguments {
    uint32_t scalarInputCount{0}, scalarOutputCount{0}, structureInputSize{0}, structureOutputSize{0};
    void *structureInputDescriptor{nullptr}, *structureOutputDescriptor{nullptr};
    const void *structureInput{nullptr};
    uint64_t scalarInput[4]{}, scalarOutput[4]{};
};
#include "bo-shared.inc"
#include "bo-constants.inc"
class PhxBringup {
public:
#include "bo-structures.inc"
    VmCtx vm[kMaxCtx]{};
    HwVmid hwv[kNumUserVmids]{};
    GpuQueue gq[2]{};
    uint64_t gSeq{5}; bool stopping{false};
    int mutex{0}; int *gpuLock{&mutex};
    FakeMap aperture, registers; FakeMap *fbAper{&aperture}, *mmio{&registers};
    std::map<uint32_t, uint32_t> regs;
    std::map<uint64_t, uint64_t> leaves;
    unsigned allocations{0}, failAllocation{0}, writes{0}, submissions{0};
    bool timeout{false}, allOnes{false}, failVmid{false};
    PhxBringup() {
        vm[0].busy = true; vm[0].hw = 8; vm[0].phys = 0x200000; vm[0].lastSeq = 5;
        hwv[0].ctx = 1; hwv[0].lastSeq = 5;
        gq[0].ready = true; gq[0].fenceOff = 0x100; gq[0].tail = 1; gq[0].fseq[0] = 5; gq[0].retiredSeq = 4;
        aperture.words[0x100 / 8] = 5;
        regs[kRegCtx0BaseLo + 16] = 0x200003; regs[kRegCtx0BaseLo + 17] = 0;
        regs[kRegCtx0Cntl + 8] = 0x01fffe07;
        regs[kRegCtx0StartLo + 16] = regs[kRegCtx0StartLo + 17] = 0;
        regs[kRegCtx0EndLo + 16] = 0xffffffff; regs[kRegCtx0EndLo + 17] = 0xf;
    }
    void wreg(uint32_t reg, uint32_t value) const {
        assert(mutex && mmio && reg == kRegInvEng17Req && value == 0x00f80100);
        ++const_cast<PhxBringup *>(this)->writes;
    }
    uint32_t rreg(uint32_t reg) const {
        assert(mutex && mmio);
        if (reg == kRegInvEng17Ack) return allOnes ? UINT32_MAX : timeout ? 0 : (1u << 8);
        const auto it = regs.find(reg); return it == regs.end() ? 0 : it->second;
    }
    uint64_t *vmPte(VmCtx &c, uint64_t va, bool alloc) {
        assert(mutex && &c == &vm[0]);
        if (alloc) { if (++allocations == failAllocation) return nullptr; return &leaves[va]; }
        auto it = leaves.find(va); return it == leaves.end() ? nullptr : &it->second;
    }
    uint32_t vmidAlloc() { return failVmid ? 0 : 1; }
    bool debugEnabled() const { return false; }
    IOReturn gpuSubmit(uint32_t handle, bool gfx, const uint64_t *va, const uint32_t *dw, uint32_t n, uint64_t *seq) {
        assert(handle == 1 && !gfx && n == 1 && va[0] == 0x30000 && dw[0] == 4);
        ++submissions; *seq = ++gSeq; vm[0].lastSeq = *seq; return kIOReturnSuccess;
    }
    bool vmOwnershipKnown(uint32_t) const;
    IOReturn vmIdleLocked(uint32_t, bool);
    IOReturn vmCanReclaim(uint32_t);
    IOReturn vmMap(uint32_t, uint64_t, IOMemoryDescriptor *, uint64_t, uint64_t, bool *);
    IOReturn vmUnmap(uint32_t, uint64_t, uint64_t);
    bool vmFlushTlb(uint32_t) const;
    bool vmBindingValid(uint32_t, uint64_t) const;
    uint64_t queueFence(const GpuQueue &) const;
    bool queueProgress(const GpuQueue &, uint64_t *) const;
    uint64_t gpuRetiredLocked() const;
    uint64_t gpuRetired() const;
};
class IOAccelPhxNativeClient {
public:
    using Bo = PhxClientBo;
#include "bo-maps.inc"
    PhxBringup *owner;
    std::unique_ptr<PhxRetiredBuffers> storage{new PhxRetiredBuffers{}};
    Bo *bos{storage->entries};
    std::vector<Map> mapStorage = std::vector<Map>(kMaxMaps);
    Map *maps{mapStorage.data()};
    bool closed{false}; uint32_t vmid{1};
    bool ctx[PHXN_MAX_CTX + 1]{};
    uint64_t visUsed{0}, hiUsed{0}, gttUsed{0}, hostUsed{0}, lastSeq{5}, emitted{5};
    uint32_t pendFenceHandle{0}, pendFenceOffset{0}; uint64_t pendFenceSeq{0};
    unsigned flushCalls{0};
    explicit IOAccelPhxNativeClient(PhxBringup &p) : owner(&p) { ctx[1] = true; }
    bool ensureVmid() { return vmid || (vmid = owner->vmidAlloc()) != 0; }
    void flushBos() { ++flushCalls; }
    bool hasPending() const; void reapPending();
    IOReturn doBoFree(IOExternalMethodArguments *);
    void boRelease(Bo &); Bo *findBo(uint32_t);
    IOReturn doGemVa(IOExternalMethodArguments *);
    bool ibCovered(uint64_t, uint64_t);
    IOReturn doSubmit(IOExternalMethodArguments *);
};
#include "bo-methods.inc"

static IOReturn freeBo(IOAccelPhxNativeClient &c, uint64_t h = 1) {
    IOExternalMethodArguments a; a.scalarInputCount = 1; a.scalarInput[0] = h;
    return c.doBoFree(&a);
}
static phxn_gem_va gem(bool unmap = false) {
    phxn_gem_va v{}; v.handle = 1; v.va_address = 0x10000; v.map_size = 8192;
    v.operation = unmap ? PHX_AMDGPU_VA_OP_UNMAP : PHX_AMDGPU_VA_OP_MAP;
    v.flags = PHX_AMDGPU_VM_PAGE_EXECUTABLE; return v;
}
static IOReturn gemCall(IOAccelPhxNativeClient &c, const phxn_gem_va &v) {
    IOExternalMethodArguments a; a.structureInput = &v; a.structureInputSize = sizeof(v);
    return c.doGemVa(&a);
}
static void mapped(PhxBringup &p, IOAccelPhxNativeClient &c, unsigned i = 0, uint64_t va = 0x10000, uint32_t handle = 1) {
    c.maps[i] = {true, handle, va, 8192, 0, PHX_AMDGPU_VM_PAGE_EXECUTABLE, false};
    p.leaves[va] = 0x400000 | kPteSysFlags; p.leaves[va + 4096] = 0x401000 | kPteSysFlags;
}
static void retained(const IOAccelPhxNativeClient &c, const IOMemoryDescriptor &md) {
    assert(c.bos[1].md == &md && c.bos[1].pendingFree && !md.releases && !md.completes);
    assert(c.gttUsed == 8192);
}
static void released(const IOAccelPhxNativeClient &c, const IOMemoryDescriptor &md, bool host = false) {
    assert(!c.bos[1].md && !c.bos[1].pendingFree && md.releases == 1 && md.completes == unsigned(host));
    assert(c.gttUsed == 0 && c.hostUsed == 0 && c.visUsed == 0 && c.hiUsed == 0);
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1]; PhxBringup p; IOAccelPhxNativeClient c(p);
    IOMemoryDescriptor md, ib;
    c.bos[1] = {&md, 8192, 2, 0, nullptr, false, false}; c.gttUsed = 8192;
    if (test.rfind("free-", 0) == 0) {
        if (test == "free-complete" || test == "free-gtt") assert(p.gpuRetired() == 5 && c.gttUsed == 8192);
        if (test != "free-no-vmid") mapped(p, c);
        if (test == "free-busy" || test == "free-late-completion" || test == "free-hidden" || test == "free-repeat") p.aperture.words[32] = 4;
        if (test == "free-ack-timeout" || test == "free-ack-retry") p.timeout = true;
        if (test == "free-aliases") mapped(p, c, 1, 0x20000);
        if (test == "free-no-vmid") { c.vmid = 0; c.owner = nullptr; }
        if (test == "free-fence-cleared") { c.pendFenceHandle = 1; c.pendFenceOffset = 8; c.pendFenceSeq = 5; }
        if (test == "free-pool-underflow") c.gttUsed = 4096;
        if (test == "free-host") { c.bos[1].host = true; c.hostUsed = 8192; c.gttUsed = 0; }
        if (test == "free-hi" || test == "free-visible") {
            c.bos[1].domain = 1; c.gttUsed = 0;
            if (test == "free-hi") { c.bos[1].bits = PHXN_PLACED_HI_POOL; c.hiUsed = 8192; }
            else c.visUsed = 8192;
        }
        if (test == "free-faulted-peer") { p.hwv[1].faulted = true; p.vm[0].hw = 0; p.hwv[0] = {}; }
        if (test == "free-invalid-map-handle" || test == "free-missing-map-bo") {
            c.maps[1] = {true, test == "free-invalid-map-handle" ? PHXN_MAX_BOS : 3u, 0x20000, 8192, 0, 0, true};
        }
        if (test == "free-high-handle") {
            assert(freeBo(c, (1ull << 32) + 1) == kIOReturnBadArgument);
            assert(!c.bos[1].pendingFree && c.findBo(1) && !md.releases && c.maps[0].used);
        } else if (test == "free-closed") {
            c.closed = true; c.bos[1].pendingFree = true; c.maps[0].pending = true; c.reapPending(); retained(c, md);
        } else {
            assert(freeBo(c) == kIOReturnSuccess && !c.findBo(1));
            if (test == "free-repeat") assert(freeBo(c) == kIOReturnNotFound);
            if (test == "free-fence-cleared") assert(!c.pendFenceHandle && !c.pendFenceOffset && !c.pendFenceSeq);
            if (test == "free-late-completion" || test == "free-ack-retry") {
                retained(c, md); assert(c.maps[0].used && c.maps[0].pending);
                p.aperture.words[32] = 5; p.timeout = false; c.reapPending();
                released(c, md); assert(!c.maps[0].used && !p.hwv[0].faulted);
                c.reapPending(); released(c, md);
            } else if (test == "free-pool-underflow") {
                assert(c.bos[1].pendingFree && c.gttUsed == 4096 && !md.releases && !c.maps[0].used);
            } else if (test == "free-busy" || test == "free-hidden" || test == "free-repeat" ||
                       test == "free-ack-timeout" || test == "free-faulted-peer" ||
                       test == "free-invalid-map-handle" || test == "free-missing-map-bo") {
                retained(c, md);
                if (test == "free-busy") assert(!p.writes && !flushes && p.leaves[0x10000] != 0);
                if (test == "free-ack-timeout") assert(p.hwv[0].faulted && p.leaves[0x10000] == 0 && c.maps[0].used);
            } else {
                released(c, md, test == "free-host"); assert(!c.maps[0].used && !c.maps[1].used);
                c.reapPending(); released(c, md, test == "free-host");
            }
        }
    } else if (test.rfind("unmap-", 0) == 0) {
        mapped(p, c); auto v = gem(true);
        if (test == "unmap-idempotent") assert(c.maps[0].used && !c.maps[0].pending);
        if (test == "unmap-busy") p.aperture.words[32] = 4;
        if (test == "unmap-timeout" || test == "unmap-retry") p.timeout = true;
        if (test == "unmap-overlap") { v.va_address += 4096; v.map_size = 4096; }
        if (test == "unmap-wrong-handle") { c.bos[2] = {&ib, 8192, 2, 0, nullptr, false, false}; v.handle = 2; }
        if (test == "unmap-zero-size" || test == "unmap-unaligned" || test == "unmap-overflow" || test == "unmap-no-lock") {
            if (test == "unmap-no-lock") p.gpuLock = nullptr;
            const auto r = p.vmUnmap(1, test == "unmap-overflow" ? UINT64_MAX - 4095 : test == "unmap-unaligned" ? 0x10001 : 0x10000,
                                    test == "unmap-zero-size" ? 0 : 8192);
            assert(r == (test == "unmap-no-lock" ? kIOReturnNotReady : kIOReturnBadArgument));
            assert(p.leaves[0x10000] && !flushes && !p.writes);
        } else {
            const auto r = gemCall(c, v);
            if (test == "unmap-busy") {
                assert(r == kIOReturnBusy && c.maps[0].used && !c.maps[0].pending && p.leaves[0x10000] && !flushes && !p.writes);
            } else if (test == "unmap-timeout" || test == "unmap-retry") {
                assert(r == kIOReturnTimeout && c.maps[0].used && c.maps[0].pending && p.hwv[0].faulted && !md.releases);
                if (test == "unmap-retry") {
                    p.timeout = false; assert(gemCall(c, v) == kIOReturnSuccess);
                    assert(!c.maps[0].used && !p.hwv[0].faulted && !md.releases);
                    assert(gemCall(c, v) == kIOReturnSuccess);
                }
            } else if (test == "unmap-overlap" || test == "unmap-wrong-handle") {
                assert(r == kIOReturnBadArgument && c.maps[0].used && p.leaves[0x10000] && !p.writes);
            } else {
                assert(r == kIOReturnSuccess && !c.maps[0].used && !p.leaves[0x10000]);
                assert(gemCall(c, v) == kIOReturnSuccess && !md.releases && c.gttUsed == 8192);
            }
        }
    } else if (test.rfind("map-", 0) == 0 || test.rfind("gem-", 0) == 0) {
        auto v = gem(); IOReturn expected = kIOReturnSuccess;
        bool direct = false, cleanup = true;
        uint32_t handle = 1; IOMemoryDescriptor *descriptor = &md;
        if (test == "map-not-ready") { p.gq[0].ready = false; expected = kIOReturnNotReady; }
        if (test == "map-no-owner") { c.owner = nullptr; expected = kIOReturnNotReady; }
        if (test == "map-no-vmid") { c.vmid = 0; p.failVmid = true; expected = kIOReturnNoResources; }
        if (test == "map-pending-overlap") { mapped(p, c); c.maps[0].pending = true; expected = kIOReturnBusy; }
        if (test == "map-existing") { p.leaves[0x11000] = 0x500077; expected = kIOReturnExclusiveAccess; }
        if (test == "map-ack-timeout" || test == "map-ack-retry" || test == "map-rollback-timeout" || test == "map-rollback-retry") {
            p.timeout = true; expected = kIOReturnTimeout;
        }
        if (test == "map-partial-rollback" || test == "map-rollback-timeout" || test == "map-rollback-retry") {
            p.failAllocation = 2; if (!p.timeout) expected = kIOReturnNoMemory;
        }
        if (test == "map-first-allocation-fails") { p.failAllocation = 1; expected = kIOReturnNoMemory; }
        if (test == "map-changed-segment") { md.badCall = 4; expected = kIOReturnVMError; }
        if (test == "map-zero-size") { v.map_size = 0; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-unaligned-va") { v.va_address++; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-unaligned-off") { v.offset_in_bo++; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-unaligned-size") { v.map_size--; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-low-va") { v.va_address = 0; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-va-overflow") { v.va_address = UINT64_MAX - 4095; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-bo-overflow") { v.offset_in_bo = UINT64_MAX - 4095; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-bo-short") { md.length = 4096; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-null-md") { descriptor = nullptr; direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-null-cleanup") { direct = true; expected = kIOReturnBadArgument; }
        if (test == "map-physical-zero") { md.physical = 0; expected = kIOReturnVMError; }
        if (test == "map-physical-unaligned") { md.physical++; expected = kIOReturnVMError; }
        if (test == "map-physical-high") { md.physical = 1ull << 48; expected = kIOReturnVMError; }
        if (test == "map-physical-short") { md.segmentLength = 4095; expected = kIOReturnVMError; }
        if (test == "map-busy") { p.aperture.words[32] = 4; expected = kIOReturnBusy; }
        if (test == "map-unbound") { p.vm[0].hw = 0; p.hwv[0] = {}; }
        if (test == "map-no-lock") { p.gpuLock = nullptr; expected = kIOReturnNotReady; }
        if (test == "map-no-mmio") { p.mmio = nullptr; expected = kIOReturnNotReady; }
        if (test == "map-no-aperture") { p.fbAper = nullptr; expected = kIOReturnNotReady; }
        if (test == "map-closing") { p.vm[0].closing = true; expected = kIOReturnNotReady; }
        if (test == "map-stopping") { p.stopping = true; expected = kIOReturnNotReady; }
        if (test == "map-invalid-handle") { handle = 97; direct = true; expected = kIOReturnNotReady; }
        if (test == "map-owner-mismatch") { p.hwv[0].ctx = 2; expected = kIOReturnNotReady; }
        if (test == "map-invalid-hardware-id") { p.vm[0].hw = 32; expected = kIOReturnNotReady; }
        if (test == "map-binding-mismatch") { p.regs[kRegCtx0Cntl + 8] = 0; expected = kIOReturnNotReady; }
        if (test == "map-faulted-peer") { p.hwv[1].faulted = true; expected = kIOReturnNotReady; }
        if (test == "map-ack-all-ones") { p.allOnes = true; expected = kIOReturnTimeout; }
        if (test == "map-future-fence") { p.aperture.words[32] = 6; expected = kIOReturnBusy; }
        if (test == "gem-overflow-offset") { v.offset_in_bo = UINT64_MAX - 4095; expected = kIOReturnBadArgument; }
        if (test == "gem-overflow-size") { v.map_size = UINT64_MAX - 4095; expected = kIOReturnBadArgument; }
        if (test == "gem-noncanonical") { v.va_address = 1ull << 49; expected = kIOReturnBadArgument; }
        if (test == "map-success") assert(!c.maps[0].used && p.leaves.empty());
        const auto r = direct ? p.vmMap(handle, v.va_address, descriptor, v.offset_in_bo, v.map_size,
                                       test == "map-null-cleanup" ? nullptr : &cleanup) : gemCall(c, v);
        assert(r == expected && !md.releases && !md.completes && c.gttUsed == 8192);
        if (direct && test != "map-null-cleanup") assert(!cleanup);
        if (test == "map-pending-overlap") assert(c.maps[0].used && c.maps[0].pending && !p.writes);
        else if (expected == kIOReturnSuccess) {
            assert(c.maps[0].used && !c.maps[0].pending && p.leaves[0x10000] == (0x400000 | kPteSysFlags));
            assert(p.leaves[0x11000] == (0x401000 | kPteSysFlags) && md.calls == 4);
            assert(p.writes == (test == "map-unbound" ? 0u : 1u));
        } else if (expected == kIOReturnTimeout) {
            assert(c.maps[0].used && c.maps[0].pending && p.hwv[0].faulted);
            assert(!c.ibCovered(0x10000, 4));
            if (test == "map-rollback-timeout" || test == "map-rollback-retry") assert(!p.leaves[0x10000]);
            if (test == "map-ack-retry" || test == "map-rollback-retry") {
                p.timeout = false; c.reapPending();
                assert(!c.maps[0].used && !p.hwv[0].faulted && !p.leaves[0x10000] && !p.leaves[0x11000]);
                assert(freeBo(c) == kIOReturnSuccess); released(c, md);
            }
        } else {
            assert(!c.maps[0].used);
            if (test == "map-existing") assert(p.leaves[0x11000] == 0x500077 && !p.writes && !flushes);
            else for (const auto &entry : p.leaves) assert(entry.second == 0);
            if (test == "map-partial-rollback" || test == "map-changed-segment") assert(p.writes == 1 && flushes == 2);
            else assert(!p.writes && !flushes);
        }
    } else if (test.rfind("coverage-", 0) == 0) {
        mapped(p, c); assert(c.ibCovered(0x10000, 8192));
        if (test == "coverage-pending") c.maps[0].pending = true;
        else { assert(test == "coverage-hidden"); c.bos[1].pendingFree = true; }
        assert(!c.ibCovered(0x10000, 4));
    } else if (test.rfind("submit-", 0) == 0) {
        c.bos[2] = {&ib, 8192, 2, 0, nullptr, false, false}; c.gttUsed += 8192;
        mapped(p, c, 1, 0x30000, 2);
        if (test == "submit-pending" || test == "submit-after-reap" || test == "submit-timeout") {
            mapped(p, c); p.aperture.words[32] = 4; assert(freeBo(c) == kIOReturnSuccess);
            assert(c.hasPending() && !md.releases);
            if (test != "submit-pending") p.aperture.words[32] = 5;
            if (test == "submit-timeout") p.timeout = true;
        }
        if (test == "submit-hidden-ib") { c.bos[2].pendingFree = true; p.aperture.words[32] = 4; }
        if (test == "submit-pending-ib") { c.maps[1].pending = true; p.aperture.words[32] = 4; }
        struct { phxn_cs_in h; phxn_cs_ib ib; } packet{};
        packet.h.abi = PHXN_ABI_VERSION; packet.h.ctx_id = 1; packet.h.num_ibs = 1;
        packet.ib.va_start = 0x30000; packet.ib.ib_bytes = 16; packet.ib.ip_type = PHX_AMDGPU_HW_IP_COMPUTE;
        IOExternalMethodArguments a; a.scalarOutputCount = 1; a.structureInput = &packet; a.structureInputSize = sizeof(packet);
        const auto r = c.doSubmit(&a);
        if (test == "submit-after-reap" || test == "submit-forwarded") {
            assert(r == kIOReturnSuccess && p.submissions == 1 && c.lastSeq == 6 && a.scalarOutput[0] == 6 && c.flushCalls == 1);
            if (test == "submit-after-reap") assert(md.releases == 1 && !c.maps[0].used && c.gttUsed == 8192);
        } else assert(r == kIOReturnBusy && !p.submissions && !c.flushCalls && !md.releases && !ib.releases);
    } else { std::cerr << "Unknown case: " << test << '\n'; return 2; }
    assert(!p.mutex);
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
