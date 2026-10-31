// Actual queue methods with checked host locks and synthetic, serialized device observations.
#include "PhxHardwarePolicy.hpp"
#include "PhxNativeABI.h"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
using IOReturn = int;
enum { kIOReturnSuccess, kIOReturnNotReady, kIOReturnBadArgument, kIOReturnBusy, kIOReturnNoResources };
struct IOBufferMemoryDescriptor {};
struct PhxRetiredBuffers;
static thread_local bool lockHeld = false;
struct IOLock { std::mutex mutex; std::atomic<unsigned> acquisitions{0}; };
static void afterLock();
static void IOLockLock(IOLock *p) {
    assert(p && !lockHeld); p->mutex.lock(); lockHeld = true; ++p->acquisitions; afterLock();
}
static void IOLockUnlock(IOLock *p) { assert(p && lockHeld); lockHeld = false; p->mutex.unlock(); }
static void IODelay(unsigned);
#include "queue-retire-constants.inc"
struct FakeMap {
    std::vector<uint64_t> words;
    unsigned observations{0};
    explicit FakeMap(size_t bytes) : words(bytes / 8, 0xa5a5a5a5a5a5a5a5ull) {}
    uintptr_t getVirtualAddress() { assert(lockHeld); ++observations; return reinterpret_cast<uintptr_t>(words.data()); }
};
class PhxBringup {
public:
#include "queue-retire-structures.inc"
    VmCtx vm[kMaxCtx]{};
    HwVmid hwv[kNumUserVmids]{};
    GpuQueue gq[2]{};
    IOLock mutex; IOLock *gpuLock{&mutex};
    FakeMap memory{0x10000}, bells{0x1000};
    FakeMap *fbAper{&memory}, *doorbellMap{&bells};
    void *mmio{reinterpret_cast<void *>(1)};
    uint64_t gSeq{42}, fbMcBase{0x100000000ull};
    bool stopping{false}, bindRefused{false}, completeOnDelay{false};
    unsigned binds{0}, reaps{0}, flushes{0}, delays{0};
    PhxBringup() {
        vm[0].busy = true;
        auto &q = gq[0]; q.ready = true; q.ringOff = 0x4000; q.ringDw = 1024;
        q.wbOff = 0x6000; q.fenceOff = 0x6100; q.dbByte = 8; q.retiredSeq = gSeq;
        memory.words[q.fenceOff / 8] = gSeq;
    }
    uint32_t vmBind(uint32_t handle) { assert(lockHeld && handle == 1); ++binds; return bindRefused ? 0 : 8; }
    void reapContextsLocked() { assert(lockHeld); ++reaps; }
    void hdpFlush() { assert(lockHeld); ++flushes; }
    uint64_t queueFence(const GpuQueue &) const;
    bool queueProgress(const GpuQueue &, uint64_t *) const;
    uint64_t gpuRetiredLocked() const;
    uint64_t gpuRetired() const;
    void ringPut(GpuQueue &, uint32_t, uint32_t);
    IOReturn gpuSubmit(uint32_t, bool, const uint64_t *, const uint32_t *, uint32_t, uint64_t *);
};
static PhxBringup *active = nullptr;
static bool stopOnLock = false;
static void afterLock() {
    if (stopOnLock) { assert(active); active->stopping = true; stopOnLock = false; }
}
static void IODelay(unsigned us) {
    assert(active && lockHeld && us == 50); ++active->delays;
    if (active->completeOnDelay && active->delays == 3) active->memory.words[active->gq[0].fenceOff / 8] = active->gSeq;
}
#include "queue-retire-methods.inc"

static void history(PhxBringup &p, const std::vector<uint64_t> &sequences, uint32_t head = 0, unsigned queue = 0) {
    auto &q = p.gq[queue]; q.head = head; q.tail = head + static_cast<uint32_t>(sequences.size());
    if (!sequences.empty()) q.retiredSeq = sequences[0] ? sequences[0] - 1 : 0;
    q.doneEnd = q.wptr; uint64_t end = q.doneEnd;
    for (unsigned i = 0; i < sequences.size(); ++i) {
        const uint32_t slot = (head + i) & 63;
        q.fseq[slot] = sequences[i]; q.fend[slot] = (end += 12);
    }
    q.wptr = end;
}
static void secondQueue(PhxBringup &p) {
    auto &q = p.gq[1]; q.ready = true; q.gfx = true; q.ringOff = 0x7000; q.ringDw = 1024;
    q.wbOff = 0x9000; q.fenceOff = 0x9100; q.dbByte = 16;
    p.memory.words[q.fenceOff / 8] = p.gSeq;
}
static IOReturn submit(PhxBringup &p, uint64_t *seq) {
    uint64_t va = 0x400000; uint32_t dw = 4;
    return p.gpuSubmit(1, false, &va, &dw, 1, seq);
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1]; PhxBringup p; active = &p;
    auto &q = p.gq[0]; auto &fence = p.memory.words[q.fenceOff / 8];
    if (test.rfind("read-", 0) == 0 || test.rfind("progress-", 0) == 0) {
        uint64_t expected = p.gSeq;
        if (test == "read-pending") { history(p, {42}); fence = 41; expected = 41; }
        if (test == "read-complete") history(p, {41, 42});
        if (test == "read-empty") assert(q.tail == q.head);
        if (test == "read-interleaved" || test == "read-other-pending") {
            secondQueue(p); history(p, {40, 42}); history(p, {41}, 0, 1); fence = 40;
            p.memory.words[p.gq[1].fenceOff / 8] = test == "read-interleaved" ? 41 : 40;
            expected = test == "read-interleaved" ? 41 : 40;
        }
        if (test == "read-high-word") { p.gSeq = 0x100000002ull; history(p, {p.gSeq}); fence = p.gSeq - 1; expected = fence; }
        if (test == "read-index-wrap") { history(p, {40, 41, 42}, UINT32_MAX - 1); fence = 41; expected = 41; }
        if (test == "read-no-lock") { p.gpuLock = nullptr; expected = 0; }
        if (test == "read-no-mmio") { p.mmio = nullptr; expected = 0; }
        if (test == "read-no-aperture" || test == "progress-no-aperture") { p.fbAper = nullptr; expected = 0; }
        if (test == "read-no-queues") { q.ready = false; expected = 0; }
        if (test == "read-future-fence") { fence = p.gSeq + 1; expected = 0; }
        if (test == "read-regressed-fence") { q.retiredSeq = 41; fence = 40; expected = 0; }
        if (test == "read-future-floor") { q.retiredSeq = p.gSeq + 1; expected = 0; }
        if (test == "read-too-many") { q.tail = 64; expected = 0; }
        if (test == "read-zero-sequence") { history(p, {0}); expected = 0; }
        if (test == "read-future-sequence") { history(p, {p.gSeq + 1}); expected = 0; }
        if (test == "read-duplicate-sequence") { history(p, {41, 41}); expected = 0; }
        if (test == "read-descending-sequence") { history(p, {42, 41}); expected = 0; }
        if (test == "read-late-invalid-sequence") { history(p, {41, 0}); fence = 40; expected = 0; }
        if (test == "read-unaligned-fence") { q.fenceOff++; expected = 0; }
        if (test == "read-gap-fence") { history(p, {40, 42}); fence = 41; expected = 0; }
        if (test == "read-fence-after-queue") { history(p, {40}); expected = 0; }
        if (test == "read-all-ones") { p.gSeq = fence = UINT64_MAX; q.retiredSeq = UINT64_MAX; expected = 0; }
        if (test.rfind("progress-", 0) == 0) {
            if (test == "progress-inactive") q.ready = false;
            uint64_t done = UINT64_MAX;
            IOLockLock(p.gpuLock);
            assert(!p.queueProgress(q, test == "progress-null-output" ? nullptr : &done));
            IOLockUnlock(p.gpuLock); assert(done == UINT64_MAX);
        } else {
            assert(p.gpuRetired() == expected);
            assert(p.mutex.acquisitions == (test == "read-no-lock" ? 0u : 1u));
            assert(!p.binds && !p.reaps && !p.flushes);
        }
    } else if (test.rfind("submit-", 0) == 0) {
        uint64_t va = 0x400000, seq = UINT64_MAX; uint32_t dw = 4, count = 1, handle = 1;
        const uint64_t *vas = &va; const uint32_t *sizes = &dw; uint64_t *out = &seq;
        bool gfx = false;
        IOReturn expected = kIOReturnSuccess;
        if (test == "submit-first") assert(!q.tail && !q.wptr);
        if (test == "submit-retires-history" || test == "submit-retired-floor") history(p, {41, 42});
        if (test == "submit-index-wrap") history(p, {40, 41, 42}, UINT32_MAX - 1);
        if (test == "submit-ring-wrap") q.wptr = q.doneEnd = 1020;
        if (test == "submit-future-fence") { history(p, {42}); fence = 43; expected = kIOReturnBusy; }
        if (test == "submit-regressed-fence") { q.retiredSeq = 41; fence = 40; expected = kIOReturnBusy; }
        if (test == "submit-gap-fence") { history(p, {40, 42}); fence = 41; expected = kIOReturnBusy; }
        if (test == "submit-fence-after-queue") { history(p, {40}); expected = kIOReturnBusy; }
        if (test == "submit-too-many") { q.tail = 64; expected = kIOReturnBusy; }
        if (test == "submit-zero-sequence") { history(p, {0}); expected = kIOReturnBusy; }
        if (test == "submit-future-sequence") { history(p, {43}); expected = kIOReturnBusy; }
        if (test == "submit-duplicate-sequence") { history(p, {42, 42}); expected = kIOReturnBusy; }
        if (test == "submit-end-before-done") { history(p, {42}); q.doneEnd = q.wptr + 1; expected = kIOReturnBusy; }
        if (test == "submit-end-descending") { history(p, {41, 42}); q.fend[1] = q.fend[0]; expected = kIOReturnBusy; }
        if (test == "submit-end-future") { history(p, {42}); q.fend[0] = q.wptr + 1; expected = kIOReturnBusy; }
        if (test == "submit-end-missing") { history(p, {42}); q.fend[0] = q.wptr - 1; expected = kIOReturnBusy; }
        if (test == "submit-empty-mismatch") { q.wptr = 1; expected = kIOReturnBusy; }
        if (test == "submit-zero-count") { count = 0; expected = kIOReturnBadArgument; }
        if (test == "submit-count-overflow") { count = 0x40000000; expected = kIOReturnBadArgument; }
        if (test == "submit-null-va") { vas = nullptr; expected = kIOReturnBadArgument; }
        if (test == "submit-null-size") { sizes = nullptr; expected = kIOReturnBadArgument; }
        if (test == "submit-null-output") { out = nullptr; expected = kIOReturnBadArgument; }
        if (test == "submit-no-lock") { p.gpuLock = nullptr; expected = kIOReturnNotReady; }
        if (test == "submit-no-mmio") { p.mmio = nullptr; expected = kIOReturnNotReady; }
        if (test == "submit-no-aperture") { p.fbAper = nullptr; expected = kIOReturnNotReady; }
        if (test == "submit-no-doorbell") { p.doorbellMap = nullptr; expected = kIOReturnNotReady; }
        if (test == "submit-no-queue") { q.ready = false; expected = kIOReturnNotReady; }
        if (test == "submit-graphics-unavailable") { gfx = true; expected = kIOReturnNotReady; }
        if (test == "submit-stopping") { p.stopping = true; expected = kIOReturnNotReady; }
        if (test == "submit-stop-after-lock") { stopOnLock = true; expected = kIOReturnNotReady; }
        if (test == "submit-invalid-context") { handle = 97; expected = kIOReturnNotReady; }
        if (test == "submit-small-ring") { q.ringDw = 16; expected = kIOReturnBadArgument; }
        if (test == "submit-nonpower-ring") { q.ringDw = 1000; expected = kIOReturnBadArgument; }
        if (test == "submit-sequence-exhausted") { p.gSeq = UINT64_MAX; expected = kIOReturnNoResources; }
        if (test == "submit-pointer-exhausted") { q.wptr = q.doneEnd = UINT64_MAX - 5; expected = kIOReturnNoResources; }
        if (test == "submit-history-full" || test == "submit-late-completion") {
            p.gSeq = 63; std::vector<uint64_t> rows; for (unsigned i = 1; i <= 63; ++i) rows.push_back(i);
            history(p, rows); fence = 0; p.completeOnDelay = test == "submit-late-completion";
            if (!p.completeOnDelay) expected = kIOReturnBusy;
        }
        if (test == "submit-ring-full") { q.ringDw = 32; history(p, {42}); q.wptr = q.fend[0] = 16; fence = 41; expected = kIOReturnBusy; }
        if (test == "submit-bind-refused") { p.bindRefused = true; expected = kIOReturnBusy; }
        const auto memory = p.memory.words, bells = p.bells.words;
        const auto initialSeq = p.gSeq, initialWptr = q.wptr, initialDone = q.doneEnd, initialFloor = q.retiredSeq;
        const auto initialHead = q.head, initialTail = q.tail;
        assert(p.gpuSubmit(handle, gfx, vas, sizes, count, out) == expected);
        if (expected == kIOReturnSuccess) {
            assert(seq == initialSeq + 1 && p.gSeq == seq && q.wptr == initialWptr + 12 && q.tail == initialTail + 1);
            assert(q.fseq[initialTail & 63] == seq && q.fend[initialTail & 63] == q.wptr);
            assert(p.vm[0].lastSeq == seq && p.hwv[0].lastSeq == seq && p.binds == 1 && p.flushes == 2);
            const uint32_t expectedPacket[] = {0xc0023f00, 0x400000, 0, 4u | (1u << 23) | (8u << 24),
                0xc0064900, 0x06603514, 0x40000000, 0x6100, 1, static_cast<uint32_t>(seq), static_cast<uint32_t>(seq >> 32), 0};
            const uint32_t *words = reinterpret_cast<const uint32_t *>(p.memory.words.data()) + q.ringOff / 4;
            for (unsigned i = 0; i < 12; ++i) assert(words[(initialWptr + i) & (q.ringDw - 1)] == expectedPacket[i]);
            assert(p.memory.words[(q.wbOff + 16) / 8] == q.wptr && p.bells.words[q.dbByte / 8] == q.wptr);
            if (test == "submit-retires-history" || test == "submit-index-wrap" || test == "submit-retired-floor" || test == "submit-late-completion") {
                assert(q.head == initialTail && q.retiredSeq == initialSeq && q.doneEnd == initialWptr);
            }
            if (test == "submit-late-completion") assert(p.delays == 3);
            if (test == "submit-retired-floor") { fence = 41; assert(p.gpuRetired() == 0); }
        } else {
            assert(seq == UINT64_MAX && p.gSeq == initialSeq && q.wptr == initialWptr && q.head == initialHead && q.tail == initialTail);
            assert(q.doneEnd == initialDone && q.retiredSeq == initialFloor && !p.flushes);
            assert(p.memory.words == memory && p.bells.words == bells);
            if (test == "submit-history-full" || test == "submit-ring-full") assert(p.delays == 40001);
            else assert(!p.delays);
            assert(p.binds == (test == "submit-bind-refused" ? 1u : 0u));
        }
    } else if (test == "concurrent-submit-retire") {
        std::atomic<bool> start{false};
        auto writer = [&]() {
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            for (unsigned i = 0; i < 128; ++i) {
                uint64_t seq = 0; assert(submit(p, &seq) == kIOReturnSuccess && seq > 42);
                IOLockLock(p.gpuLock); fence = p.gSeq; IOLockUnlock(p.gpuLock);
                std::this_thread::yield();
            }
        };
        std::thread one(writer), two(writer);
        std::thread reader([&]() {
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            uint64_t previous = 0;
            for (unsigned i = 0; i < 2048; ++i) {
                const uint64_t done = p.gpuRetired(); assert(done >= previous); previous = done;
                std::this_thread::yield();
            }
        });
        start.store(true, std::memory_order_release);
        one.join(); two.join(); reader.join();
        assert(p.gSeq == 42 + 256 && p.gpuRetired() == p.gSeq && p.binds == 256 && p.flushes == 512);
        assert(p.vm[0].lastSeq == p.gSeq && p.hwv[0].lastSeq == p.gSeq && q.wptr == 12 * 256 && q.tail == 256);
        assert(p.mutex.acquisitions >= 256 * 2 + 2049 && !p.delays);
    } else { std::cerr << "Unknown case: " << test << '\n'; return 2; }
    assert(!lockHeld);
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
