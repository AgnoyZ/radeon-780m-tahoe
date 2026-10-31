// Actual staged method bodies; only IOKit/MMIO/retirement observations are faked.
#include "PhxHardwarePolicy.hpp"
#include "PhxNativeABI.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <map>
#include <string>
#include <vector>
using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnNotReady, kIOReturnBadArgument, kIOReturnBusy, kIOReturnNoResources };
struct IOBufferMemoryDescriptor {};
struct PhxRetiredBuffers;
static void IOLockLock(int *p) { assert(p && !*p); *p = 1; }
static void IOLockUnlock(int *p) { assert(p && *p); *p = 0; }
static void IODelay(unsigned);
#include "vm-constants.inc"
struct FakeMap {
    std::vector<uint64_t> words;
    explicit FakeMap(size_t bytes) : words(bytes / 8, 0xa5a5a5a5a5a5a5a5ull) {}
    uintptr_t getVirtualAddress() { return reinterpret_cast<uintptr_t>(words.data()); }
};
class PhxBringup {
public:
#include "vm-structures.inc"
    VmCtx vm[kMaxCtx]{};
    HwVmid hwv[kNumUserVmids]{};
    GpuQueue gq[2]{};
    FakeMap memory{0x10000}, bells{0x1000};
    FakeMap *fbAper{&memory}, *doorbellMap{&bells};
    void *mmio{reinterpret_cast<void *>(1)};
    uint64_t fbMcBase{0x100000000ull}, hwTick{1000}, gSeq{42}, done{0};
    int mutex{0}; int *gpuLock{&mutex};
    bool stopping{false};
    std::string mode;
    mutable std::map<uint32_t, uint32_t> regs;
    uint32_t badRegister{UINT32_MAX};
    mutable unsigned ackReads{0}, reads{0}, retireReads{0};
    unsigned writes{0}, requests{0}, delay1{0}, delay50{0}, flushes{0};
    bool forceTimeout{false};
    explicit PhxBringup(const std::string &name) : mode(name) {
        vm[0].busy = true; vm[0].phys = 0x200000;
        auto &q = gq[0]; q.ready = true; q.ringOff = 0x4000; q.ringDw = 1024;
        q.wbOff = 0x6000; q.fenceOff = 0x6100; q.dbByte = 8;
    }
    uint32_t rreg(uint32_t reg) const {
        assert(mutex && mmio); ++reads;
        if (reg == kRegInvEng17Ack) {
            ++ackReads;
            if (forceTimeout || mode == "flush-timeout" || mode == "flush-wrong-vmid" ||
                mode == "bind-timeout" || mode == "bind-cached-timeout" || mode == "submit-timeout")
                return mode == "flush-wrong-vmid" ? 1 : 0;
            if (mode.find("all-ones") != std::string::npos) return UINT32_MAX;
            if (mode == "flush-last" && ackReads < 1000) return 0;
            return regs.at(kRegInvEng17Req) & 0xffff;
        }
        const uint32_t value = regs.count(reg) ? regs.at(reg) : 0;
        return reg == badRegister ? value ^ 1u : value;
    }
    void wreg(uint32_t reg, uint32_t value) const {
        assert(mutex && mmio);
        auto &self = *const_cast<PhxBringup *>(this); ++self.writes;
        if (reg == kRegInvEng17Req) {
            assert(!(value & 1) && (value & 0xffff0000u) == 0x00f80000u);
            ++self.requests;
        }
        regs[reg] = value;
    }
    void hdpFlush() { assert(mutex); ++flushes; }
    void reapContextsLocked() { assert(mutex); }
    uint64_t queueFence(const GpuQueue &) const { return gSeq; }
    bool queueProgress(const GpuQueue &, uint64_t *value) const { assert(mutex); *value = gSeq; return true; }
    uint64_t gpuRetiredLocked() const { assert(mutex); ++retireReads; return done; }
    bool vmFlushTlb(uint32_t) const;
    bool vmBindingValid(uint32_t, uint64_t) const;
    uint32_t vmBind(uint32_t);
    void ringPut(GpuQueue &, uint32_t, uint32_t);
    IOReturn gpuSubmit(uint32_t, bool, const uint64_t *, const uint32_t *, uint32_t, uint64_t *);
};
static PhxBringup *active;
static void IODelay(unsigned us) {
    assert(active && active->mutex);
    if (us == 1) ++active->delay1;
    else {
        assert(us == 50); ++active->delay50;
        if (active->mode == "bind-late-retirement" && active->delay50 == 3) active->done = 100;
    }
}
#include "vm-methods.inc"

static void cached(PhxBringup &p) {
    auto &c = p.vm[0]; c.hw = 8;
    p.hwv[0].ctx = 1; p.hwv[0].lastSeq = 7; p.hwv[0].lastUse = 5;
    p.regs[kRegCtx0BaseLo + 16] = static_cast<uint32_t>(c.phys | 3);
    p.regs[kRegCtx0BaseLo + 17] = static_cast<uint32_t>(c.phys >> 32);
    p.regs[kRegCtx0Cntl + 8] = 0x01fffe07;
    p.regs[kRegCtx0StartLo + 16] = p.regs[kRegCtx0StartLo + 17] = 0;
    p.regs[kRegCtx0EndLo + 16] = 0xffffffff;
    p.regs[kRegCtx0EndLo + 17] = 0xf;
}
static void occupied(PhxBringup &p) {
    for (unsigned i = 0; i < kNumUserVmids; ++i) {
        p.vm[i + 1].busy = true; p.vm[i + 1].hw = 8 + i; p.vm[i + 1].phys = 0x300000 + i * 4096;
        p.hwv[i].ctx = i + 2; p.hwv[i].lastSeq = 100 + i; p.hwv[i].lastUse = 100 + i;
    }
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1];
    PhxBringup p(test); active = &p;
    uint32_t handle = 1, expectedVmid = 8;
    bool success = true;
    if (test.rfind("flush-", 0) == 0) {
        uint32_t vmid = 8;
        if (test.size() < 9 && test[6] >= '0' && test[6] <= '9') vmid = static_cast<uint32_t>(std::stoul(test.substr(6)));
        else if (test == "flush-zero") vmid = 0;
        else if (test == "flush-low") vmid = 7;
        else if (test == "flush-high") vmid = 16;
        else if (test == "flush-shift32") vmid = 32;
        else if (test == "flush-max") vmid = UINT32_MAX;
        else if (test == "flush-no-mmio") p.mmio = nullptr;
        success = vmid >= 8 && vmid < 16 && p.mmio && test != "flush-timeout" && test != "flush-wrong-vmid" && test != "flush-all-ones";
        IOLockLock(p.gpuLock); assert(p.vmFlushTlb(vmid) == success); IOLockUnlock(p.gpuLock);
        if (vmid < 8 || vmid > 15 || !p.mmio) assert(p.writes == 0 && p.reads == 0 && p.delay1 == 0);
        else {
            assert(p.requests == 1 && p.regs[kRegInvEng17Req] == (0x00f80000u | (1u << vmid)));
            const bool bounded = test == "flush-timeout" || test == "flush-wrong-vmid" || test == "flush-last";
            assert(p.ackReads == (bounded ? 1000u : 1u) && p.delay1 == (bounded ? 999u : 0u));
        }
    } else {
        if (test.find("cached") != std::string::npos || test.rfind("cached-", 0) == 0) cached(p);
        if (test == "bind-zero") handle = 0;
        else if (test == "bind-high") handle = PhxBringup::kMaxCtx + 1;
        else if (test == "bind-inactive") p.vm[0].busy = false;
        else if (test == "bind-no-mmio") p.mmio = nullptr;
        else if (test == "bind-zero-root") p.vm[0].phys = 0;
        else if (test == "bind-misaligned-root") p.vm[0].phys |= 8;
        else if (test == "bind-high-root" || test == "submit-bad-root") p.vm[0].phys |= 1ull << 48;
        else if (test == "bind-tick-overflow") p.hwTick = UINT64_MAX;
        else if (test == "submit-sequence-exhausted") p.gSeq = UINT64_MAX;
        else if (test == "submit-wptr-exhausted") p.gq[0].wptr = p.gq[0].doneEnd = UINT64_MAX - 5;
        else if (test == "submit-stopping") p.stopping = true;
        else if (test == "bind-cached-low") p.vm[0].hw = 7;
        else if (test == "bind-cached-high") p.vm[0].hw = 16;
        else if (test == "bind-cached-owner") p.hwv[0].ctx = 2;
        else if (test.find("victim") != std::string::npos) {
            occupied(p);
            if (test == "bind-invalid-victim") p.hwv[0].ctx = PhxBringup::kMaxCtx + 1;
            else if (test == "bind-inactive-victim") p.vm[1].busy = false;
            else if (test == "bind-mismatched-victim") p.vm[1].hw = 9;
        } else if (test == "bind-all-busy" || test == "bind-retired-lru" || test == "bind-late-retirement") {
            occupied(p);
            if (test == "bind-retired-lru") { p.done = 102; p.hwv[2].lastUse = 1; expectedVmid = 10; }
        }
        if (test.find("readback-") != std::string::npos) {
            const unsigned i = static_cast<unsigned>(test.back() - '0'); assert(i < 7);
            const uint32_t regs[] = {kRegCtx0BaseLo + 16, kRegCtx0BaseLo + 17, kRegCtx0Cntl + 8,
                kRegCtx0StartLo + 16, kRegCtx0StartLo + 17, kRegCtx0EndLo + 16, kRegCtx0EndLo + 17};
            p.badRegister = regs[i];
        }
        success = test == "bind-first" || test == "bind-cached" || test == "bind-retired-lru" ||
            test == "bind-late-retirement" || test == "submit-first" || test == "submit-cached";
        const bool retry = test.find("retry-timeout") != std::string::npos;
        if (retry) p.forceTimeout = true;
        const auto memory = p.memory.words, bells = p.bells.words;
        const auto initialSeq = p.gSeq, initialWptr = p.gq[0].wptr;
        if (test.rfind("submit-", 0) == 0) {
            uint64_t va = 0x400000, seq = UINT64_MAX; uint32_t dw = 4;
            IOReturn result = p.gpuSubmit(1, false, &va, &dw, 1, &seq);
            if (!success) {
                const auto expected = test == "submit-stopping" ? kIOReturnNotReady :
                    test == "submit-sequence-exhausted" || test == "submit-wptr-exhausted" ? kIOReturnNoResources : kIOReturnBusy;
                assert(result == expected && seq == UINT64_MAX && p.gSeq == initialSeq);
                assert(p.memory.words == memory && p.bells.words == bells && p.flushes == 0);
                assert(p.gq[0].tail == 0 && p.gq[0].wptr == initialWptr);
            }
            if (retry) {
                const unsigned writes = p.writes; p.forceTimeout = false;
                result = p.gpuSubmit(1, false, &va, &dw, 1, &seq);
                assert(p.writes == writes + 1); success = true;
            }
            if (success) {
                assert(result == kIOReturnSuccess && seq == 43 && p.gSeq == 43 && p.flushes == 2);
                assert(p.gq[0].tail == 1 && p.gq[0].wptr == 12 && p.hwv[0].lastSeq == 43);
                assert(p.vm[0].lastSeq == 43);
                const uint32_t *words = reinterpret_cast<const uint32_t *>(p.memory.words.data()) + 0x4000 / 4;
                const uint32_t packet[] = {0xc0023f00, 0x400000, 0, 4u | (1u << 23) | (8u << 24),
                    0xc0064900, 0x06603514, 0x40000000, 0x6100, 1, 43, 0, 0};
                assert(std::memcmp(words, packet, sizeof(packet)) == 0);
                assert(p.memory.words[(0x6000 + 16) / 8] == 12 && p.bells.words[1] == 12);
            }
            assert(p.mutex == 0);
        } else {
            IOLockLock(p.gpuLock); uint32_t result = p.vmBind(handle);
            assert(result == (success ? expectedVmid : 0));
            if (retry) {
                const unsigned writes = p.writes; p.forceTimeout = false;
                result = p.vmBind(handle); assert(result == 8 && p.writes == writes + 1); success = true;
            }
            IOLockUnlock(p.gpuLock);
            assert(p.memory.words == memory && p.bells.words == bells && p.gSeq == 42);
            if (success) {
                assert(p.vm[0].hw == result && p.hwv[result - 8].ctx == 1 && p.hwv[result - 8].lastUse == p.hwTick);
                assert(p.requests >= 1);
                if (test == "bind-retired-lru") assert(p.vm[3].hw == 0 && p.vm[1].hw == 8 && p.vm[2].hw == 9);
                if (test == "bind-late-retirement") assert(p.delay50 == 3 && p.vm[1].hw == 0);
            }
        }
        if (test.find("readback-") != std::string::npos) assert(p.requests == 0 && p.ackReads == 0);
        if (test == "bind-all-busy") assert(p.delay50 == 40001 && p.writes == 0);
        if (test == "bind-timeout" || test == "bind-cached-timeout" || test == "submit-timeout")
            assert(p.ackReads == 1000 && p.delay1 == 999 && p.requests == 1);
    }
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
