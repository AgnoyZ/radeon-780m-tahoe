// Actual staged kernel methods; only their OS, memory and hardware dependencies are faked.
#include "PhxNativeABI.h"
#include "PhxHardwarePolicy.hpp"
#include "PhxPspLayout.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <strings.h>
#include <vector>

using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnNotReady, kIOReturnBadArgument, kIOReturnNoResources,
       kIOReturnTimeout, kIOReturnError, kIOReturnExclusiveAccess };
static void IOLockLock(int *lock) { assert(*lock == 0); *lock = 1; }
static void IOLockUnlock(int *lock) { assert(*lock == 1); *lock = 0; }
static void IOSleep(unsigned);

struct FakeMap {
    std::vector<uint32_t> words;
    explicit FakeMap(size_t bytes) : words(bytes / 4, 0xA5A5A5A5) {}
    uintptr_t getVirtualAddress() { return reinterpret_cast<uintptr_t>(words.data()); }
};
#include "psp-frame.inc"

class PhxBringup {
public:
    std::string mode;
    FakeMap memory;
    void *mmio{reinterpret_cast<void *>(1)};
    FakeMap *fbAper{&memory};
    int lock{0};
    int *smuLock{&lock};
    int gpuMutex{0};
    int *gpuLock{&gpuMutex};
    uint64_t fbAperLen, fbSize{0x10000}, fbMcBase{0x100000000ull}, fbPhys{0x200000000ull};
    uint64_t ringMc{0x100000000ull}, ringOff{0}, cmdOff{0x4000}, cmdMc{0x100004000ull};
    uint64_t fenceOff{0x8000}, fenceMc{0x100008000ull};
    uint32_t fenceCounter{0};
    bool pspSubmissionFaulted{false};
    PhxPspLayout pspLayout{PHX_PSP_LAYOUT_VERSION, 0, 0x9000, 0x3000, 0xC000, 0x1000, {0, 0}};
    bool pspLayoutConfigured{true}, gpuActive{false};
    uint64_t tmrOff{0x9000}, tmrMc{0x100009000ull}, tmrSize{0};
    uint64_t fwBufOff{0xC000}, fwBufMc{0x10000C000ull}, fwBufSize{0x1000};
    bool tmrSetUp{false};
    unsigned writes{0}, reads{0}, sleeps{0}, flushes{0};
    mutable unsigned waits{0};
    uint32_t wptr{0};
    bool armed{false};

    explicit PhxBringup(const char *test) : mode(test),
        memory(mode == "create-timeout" ? 0x6000000 : 0x10000), fbAperLen(memory.words.size() * 4) {}
    uint32_t rreg(uint32_t reg) { assert(lock); ++reads; return reg == PHX_PSP_C2PMSG_67 ? wptr : 0; }
    void wreg(uint32_t reg, uint32_t value) {
        assert(lock); ++writes;
        if (reg == PHX_PSP_C2PMSG_67) { wptr = value; armed = true; }
    }
    void hdpFlush() { assert(lock); ++flushes; }
    bool pspWaitTos(uint32_t timeout) const {
        assert(lock && timeout == 2000); ++waits;
        return mode == "layout-create-success" || (mode == "create-timeout" && waits == 1);
    }
    void step() {
        assert(lock); ++sleeps;
        if (!armed) return;
        if (mode == "timeout" || mode == "tmr-timeout") return;
        memory.words[fenceOff / 4] = mode == "wrong-fence" ? fenceCounter - 1 : fenceCounter;
        memory.words[(cmdOff + PHX_PSP_GFX_RESP_OFFSET) / 4] =
            mode == "psp-error" || mode == "tmr-error" || mode == "load-error" ? 0x100 : 0;
        memory.words[(cmdOff + PHX_PSP_GFX_RESP_OFFSET + 8) / 4] = 0x12345678;
        memory.words[(cmdOff + PHX_PSP_GFX_RESP_OFFSET + 12) / 4] = 0xABCDEF01;
    }
    void clearRing();
    bool gpuReady() const { assert(gpuMutex == 1); return gpuActive; }
    IOReturn configurePspLayout(const PhxPspLayout &, uint64_t[4]);
    IOReturn pspRing(uint32_t, uint64_t, uint64_t[4]);
    IOReturn pspRunCmd(uint32_t, const uint32_t *, uint32_t, uint64_t[4]);
    IOReturn fwStage(uint32_t, const void *, uint32_t);
    IOReturn loadIpFw(uint32_t, uint32_t, uint32_t, uint64_t[4]);
    IOReturn pspCtl(uint32_t, uint32_t, uint64_t[4]);
};
static PhxBringup *active;
static void IOSleep(unsigned milliseconds) { assert(milliseconds == 1 || milliseconds == 20); active->step(); }
#include "psp-methods.inc"

static IOReturn submit(PhxBringup &p, const uint32_t *words, uint32_t count, uint64_t *out) {
    IOLockLock(p.smuLock);
    auto result = p.pspRunCmd(PHX_PSP_GFX_CMD_LOAD_IP_FW, words, count, out);
    IOLockUnlock(p.smuLock);
    return result;
}

static void assert_fault_stays_terminal(PhxBringup &p) {
    assert(p.pspSubmissionFaulted && !p.tmrSetUp);
    const auto before = p.memory.words;
    const auto writes = p.writes;
    uint64_t out[4]{};
    uint32_t word = 0x11223344;
    assert(submit(p, nullptr, 0, out) == kIOReturnNotReady);
    assert(p.pspCtl(1, 4096, out) == kIOReturnNotReady);
    assert(p.pspCtl(2, 0, out) == kIOReturnNotReady);
    assert(p.loadIpFw(4, 0, 4, out) == kIOReturnNotReady);
    assert(p.fwStage(0, &word, 4) == kIOReturnNotReady);
    assert(p.pspRing(1, 0, out) == kIOReturnNotReady);
    assert(p.pspRing(2, 0, out) == kIOReturnNotReady);
    p.clearRing();
    assert(p.pspSubmissionFaulted);
    assert(p.pspRing(1, 0, out) == kIOReturnNotReady);
    assert(p.writes == writes && p.memory.words == before && p.lock == 0);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string test = argv[1];
    PhxBringup p(argv[1]); active = &p;
    uint64_t out[4] = {99, 99, 99, 99};
    uint32_t words[15] = {0x10203040, 2, 3, 4};
    IOReturn result;
    if (test.rfind("layout-", 0) == 0) {
        p.clearRing(); p.pspLayoutConfigured = false; p.pspLayout = {};
        PhxPspLayout candidate{PHX_PSP_LAYOUT_VERSION, 0x1000, 0xA000, 0x2000, 0xD000, 0x2000, {0, 0}};
        const auto before = p.memory.words;
        if (test == "layout-overlap") candidate.tmrOffset = 0x9000;
        if (test == "layout-outside-vram") p.fbSize = 0xE000;
        if (test == "layout-outside-aperture") p.fbAperLen = 0xE000;
        if (test == "layout-mc-overflow") p.fbMcBase = UINT64_MAX - 4095;
        if (test == "layout-physical-overflow") p.fbPhys = UINT64_MAX - 4095;
        if (test == "layout-active-ring") p.ringMc = p.fbMcBase;
        if (test == "layout-active-gpu") p.gpuActive = true;
        if (test == "layout-faulted") p.pspSubmissionFaulted = true;
        if (test == "layout-create-missing") {
            result = p.pspRing(1, candidate.ringOffset, out);
            assert(result == kIOReturnNotReady);
        } else {
            result = p.configurePspLayout(candidate, test == "layout-null-output" ? nullptr : out);
            bool accepted = test == "layout-configure" || test == "layout-reconfigure" ||
                            test == "layout-create-success" || test == "layout-create-mismatch" ||
                            test == "layout-create-revalidate";
            assert(p.pspLayoutConfigured == accepted);
            if (accepted) {
                assert(result == kIOReturnSuccess && !memcmp(&candidate, &p.pspLayout, sizeof(candidate)));
                assert(out[0] == p.fbMcBase && out[1] == p.fbPhys && out[2] == p.fbSize && out[3] == p.fbAperLen);
                assert(!p.writes && !p.reads && !p.waits && p.memory.words == before);
                if (test == "layout-reconfigure") {
                    candidate.ringOffset = 0;
                    assert(p.configurePspLayout(candidate, out) == kIOReturnSuccess);
                    assert(p.pspLayout.ringOffset == 0);
                    candidate.version = 2;
                    assert(p.configurePspLayout(candidate, out) == kIOReturnBadArgument);
                    assert(p.pspLayout.version == 1 && p.pspLayout.ringOffset == 0 && p.pspLayoutConfigured);
                } else if (test != "layout-configure") {
                    if (test == "layout-create-revalidate") p.fbSize = 0xE000;
                    result = p.pspRing(1, candidate.ringOffset + (test == "layout-create-mismatch" ? 4096 : 0), out);
                    if (test == "layout-create-success") {
                        assert(result == kIOReturnSuccess && p.ringOff == candidate.ringOffset);
                        assert(p.ringMc == p.fbMcBase + candidate.ringOffset);
                        assert(p.tmrOff == candidate.tmrOffset && p.tmrMc == p.fbMcBase + candidate.tmrOffset);
                        assert(p.fwBufOff == candidate.stagingOffset && p.fwBufSize == candidate.stagingCapacity);
                        assert(p.fwBufMc == p.fbMcBase + candidate.stagingOffset);
                        assert(p.cmdOff == candidate.ringOffset + PHX_PSP_CMD_REL);
                        assert(p.fenceOff == candidate.ringOffset + PHX_PSP_FENCE_REL);
                        assert(p.writes == 5 && p.waits == 2);
                        for (size_t i = 0; i < before.size(); ++i) {
                            const auto off = i * 4;
                            bool cleared = (off >= p.ringOff && off < p.ringOff + PHX_PSP_RING_BUF_SIZE) ||
                                           (off >= p.cmdOff && off < p.cmdOff + 4096) ||
                                           (off >= p.fenceOff && off < p.fenceOff + 4096);
                            assert(p.memory.words[i] == (cleared ? 0u : before[i]));
                        }
                    } else assert(result == kIOReturnBadArgument);
                }
            } else {
                assert(result == (test == "layout-faulted" ? kIOReturnNotReady :
                    test == "layout-active-ring" || test == "layout-active-gpu" ? kIOReturnExclusiveAccess : kIOReturnBadArgument));
                assert(p.pspLayout.version == 0);
            }
        }
        if (test != "layout-create-success")
            assert(!p.writes && !p.reads && !p.waits && p.memory.words == before);
    } else if (test.rfind("tmr-", 0) == 0) {
        if (test == "tmr-error" || test == "tmr-timeout") { p.tmrSetUp = true; p.tmrSize = 8192; }
        const auto before = p.memory.words;
        result = p.pspCtl(1, test == "tmr-zero" ? 0 : test == "tmr-too-large" ? p.pspLayout.tmrCapacity + 1 : 4096, out);
        if (test == "tmr-success") {
            assert(result == kIOReturnSuccess && p.tmrSetUp && p.tmrSize == 4096);
        } else if (test == "tmr-too-large" || test == "tmr-zero") {
            assert(result == kIOReturnBadArgument && !p.tmrSetUp && p.tmrSize == 0);
            assert(p.memory.words == before && !p.writes && !p.reads);
        } else {
            assert(result == (test == "tmr-timeout" ? kIOReturnTimeout : kIOReturnError));
            assert(p.tmrSize == 0 && out[2] == 0 && out[3] == 0);
            assert_fault_stays_terminal(p);
        }
    } else if (test.rfind("stage-", 0) == 0) {
        if (test == "stage-overrun") p.fwBufSize = 4095;
        if (test == "stage-aperture-overflow") p.fwBufOff = UINT64_MAX - 3;
        const auto before = p.memory.words;
        const unsigned char bytes[3] = {1, 2, 3};
        result = p.fwStage(4092, test == "stage-null" ? nullptr : bytes, test == "stage-empty" ? 0 : 3);
        if (test == "stage-tail") {
            assert(result == kIOReturnSuccess);
            assert(p.memory.words[(p.fwBufOff + 4092) / 4] == 0x00030201);
        } else assert(result == kIOReturnBadArgument && p.memory.words == before);
        assert(!p.writes && !p.reads);
    } else if (test.rfind("load-", 0) == 0) {
        if (test == "load-address-overflow") p.fwBufMc = UINT64_MAX - 3;
        const auto before = p.memory.words;
        result = p.loadIpFw(4, 4, 4, out);
        if (test == "load-success") {
            assert(result == kIOReturnSuccess);
            assert(p.memory.words[(p.cmdOff + PHX_PSP_GFX_CMD_UNION_OFFSET) / 4] == 0xC004);
        } else if (test == "load-address-overflow") {
            assert(result == kIOReturnBadArgument && !p.writes && !p.reads && p.memory.words == before);
        } else {
            assert(result == kIOReturnError);
            assert_fault_stays_terminal(p);
        }
    } else if (test == "create-timeout" || test == "destroy-timeout") {
        if (test == "create-timeout") p.ringMc = 0;
        const uint64_t previousRing = p.ringMc;
        result = p.pspRing(test == "create-timeout" ? 1 : 2, 0, out);
        assert(result == kIOReturnTimeout);
        if (test == "destroy-timeout") assert(p.ringMc == previousRing);
        assert_fault_stays_terminal(p);
    } else {
        const uint32_t *input = words;
        uint32_t count = 4;
        if (test == "last-fence") p.fenceCounter = UINT32_MAX - 1;
        else if (test == "fence-exhausted") p.fenceCounter = UINT32_MAX;
        else if (test == "bad-wptr") p.wptr = 1;
        else if (test == "high-wptr") p.wptr = UINT32_MAX;
        else if (test == "last-slot") p.wptr = 1008;
        else if (test == "wrap-sentinel") p.wptr = 1024;
        else if (test == "max-words") count = 14;
        else if (test == "too-many-words") count = 15;
        else if (test == "null-words") input = nullptr;
        else if (test == "cmd-overflow") p.cmdOff = p.fbAperLen - 1020;
        else if (test == "fence-overflow") p.fenceOff = p.fbAperLen;
        else if (test == "ring-overflow") p.ringOff = UINT64_MAX - 63;
        else if (test == "unaligned-cmd") ++p.cmdOff;
        const auto before = p.memory.words;
        const uint32_t initialFence = p.fenceCounter;
        result = submit(p, input, count, test == "null-output" ? nullptr : out);
        bool success = test == "success" || test == "last-fence" || test == "last-slot" || test == "wrap-sentinel" || test == "max-words";
        bool completionFailure = test == "timeout" || test == "wrong-fence" || test == "psp-error";
        if (success) {
            assert(result == kIOReturnSuccess && !p.pspSubmissionFaulted && p.sleeps == 1 && p.writes == 1);
            assert(out[0] == 0 && out[2] == 0x12345678 && out[3] == 0xABCDEF01);
            assert(p.fenceCounter == initialFence + 1);
            assert(p.wptr == (test == "last-slot" ? 0 : 16));
            PhxGfxRbFrame frame;
            memcpy(&frame, p.memory.words.data() + (test == "last-slot" ? 1008 : 0), sizeof(frame));
            assert(frame.fence_value == p.fenceCounter && frame.cmd_buf_size == 0);
            assert((uint64_t(frame.cmd_buf_addr_hi) << 32 | frame.cmd_buf_addr_lo) == p.cmdMc);
            assert((uint64_t(frame.fence_addr_hi) << 32 | frame.fence_addr_lo) == p.fenceMc);
            assert(p.memory.words[(p.cmdOff + PHX_PSP_CMD_HDR_CMD_ID_OFFSET) / 4] == PHX_PSP_GFX_CMD_LOAD_IP_FW);
            for (unsigned i = 0; i < count; ++i)
                assert(p.memory.words[(p.cmdOff + PHX_PSP_GFX_CMD_UNION_OFFSET) / 4 + i] == words[i]);
        } else if (completionFailure) {
            assert(result == (test == "psp-error" ? kIOReturnError : kIOReturnTimeout));
            assert(p.sleeps == (test == "psp-error" ? 1u : 5000u));
            assert(out[2] == 0 && out[3] == 0);
            assert_fault_stays_terminal(p);
        } else {
            assert(result == (test == "fence-exhausted" ? kIOReturnNoResources : kIOReturnBadArgument));
            assert(!p.writes && !p.sleeps && p.memory.words == before && p.fenceCounter == initialFence);
        }
    }
    assert(p.lock == 0 && p.gpuMutex == 0);
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
