// Exercise real tree walks and client cleanup together; hardware and OS services remain explicit fakes.
#define PHX_REAL_PAGE_TABLES
#define PHX_NO_BO_TEST_MAIN
#include <algorithm>
#include "test_bo_retirement.cpp"

static uint64_t *leaf(PhxBringup &p, uint64_t va, bool alloc = false, IOReturn *status = nullptr) {
    IOLockLock(p.gpuLock);
    auto *result = p.vmPte(p.vm[0], va, alloc, status);
    IOLockUnlock(p.gpuLock);
    return result;
}
static uint64_t *table(PhxBringup &p, unsigned i = 0) {
    auto &c = p.vm[0]; assert(c.chunk[i / 16]);
    return reinterpret_cast<uint64_t *>(static_cast<uint8_t *>(c.chunk[i / 16]->storage) + (i % 16) * 4096);
}
struct TreeImage {
    uint64_t phys, chunkPhys, backingPhysical;
    uint32_t used, pages;
    uint64_t length;
    void *cpu;
    std::vector<uint8_t> bytes;
    explicit TreeImage(PhxBringup &p) : phys(p.vm[0].phys), chunkPhys(p.vm[0].chunkPhys[0]),
        backingPhysical(p.vm[0].chunk[0]->physical), used(p.vm[0].used), pages(p.vm[0].pages),
        length(p.vm[0].chunk[0]->length), cpu(p.vm[0].chunk[0]->cpu) {
        const auto *data = static_cast<const uint8_t *>(p.vm[0].chunk[0]->storage);
        bytes.assign(data, data + 65536);
    }
    void restore(PhxBringup &p) const {
        auto &c = p.vm[0];
        c.phys = phys; c.chunkPhys[0] = chunkPhys; c.used = used; c.pages = pages;
        c.chunk[0]->physical = backingPhysical; c.chunk[0]->length = length; c.chunk[0]->cpu = cpu;
        std::memcpy(c.chunk[0]->storage, bytes.data(), bytes.size());
        p.regs[kRegCtx0BaseLo + 16] = static_cast<uint32_t>(phys | 3);
        p.regs[kRegCtx0BaseLo + 17] = static_cast<uint32_t>(phys >> 32);
    }
};
static void damage(PhxBringup &p, const std::string &mode, uint64_t *pte) {
    auto &c = p.vm[0]; auto *b = c.chunk[0];
    if (mode == "root-mismatch") {
        c.phys += 4096; p.regs[kRegCtx0BaseLo + 16] = static_cast<uint32_t>(c.phys | 3);
    } else if (mode == "null-cpu") b->cpu = nullptr;
    else if (mode == "short-descriptor") b->length = 65535;
    else if (mode == "changed-physical") b->physical += 65536;
    else if (mode == "bad-flags") table(p)[0] ^= 2;
    else if (mode == "invalid-entry") table(p)[0] = 2;
    else if (mode == "foreign-child") table(p)[0] = 0x900007;
    else if (mode == "unused-child") table(p)[0] = (c.phys + 8 * 4096) | 7;
    else if (mode == "cycle") table(p)[0] = c.phys | 7;
    else if (mode == "zero-child") table(p)[0] = 7;
    else if (mode == "missing-chunk") c.used = 17;
    else if (mode == "leaf-invalid") *pte = 2;
    else if (mode == "leaf-flags") *pte ^= 0x20;
    else if (mode == "leaf-zero-physical") *pte = kPteSysFlags;
    else assert(false);
}
static void mapHealthy(PhxBringup &p, IOAccelPhxNativeClient &c, const phxn_gem_va &v) {
    assert(gemCall(c, v) == kIOReturnSuccess && c.maps[0].used && !c.maps[0].pending);
    assert(*leaf(p, v.va_address) == (0x400000 | kPteSysFlags));
    assert(*leaf(p, v.va_address + 4096) == (0x401000 | kPteSysFlags));
    assert(p.vm[0].used >= 4 && p.leaves.empty());
}
static void pending(IOAccelPhxNativeClient &c, const IOMemoryDescriptor &md) {
    assert(c.maps[0].used && c.maps[0].pending && c.bos[1].md == &md);
    assert(!md.releases && !md.completes && c.hasPending() && !c.ibCovered(c.maps[0].va, 4));
}
int main(int argc, char **argv) {
    assert(argc == 2); const std::string test = argv[1]; PhxBringup p; IOAccelPhxNativeClient c(p);
    IOMemoryDescriptor md;
    c.bos[1] = {&md, 8192, 2, 0, nullptr, false, false}; c.gttUsed = 8192;
    auto v = gem();
    if (test.rfind("status-", 0) == 0) {
        IOReturn status = kIOReturnBadArgument;
        if (test == "status-present") mapHealthy(p, c, v);
        if (test == "status-capacity") p.vm[0].pages = 1;
        if (test == "status-corrupt" || test == "status-no-output") table(p)[0] = 2;
        auto *pte = leaf(p, v.va_address, test == "status-capacity", test == "status-no-output" ? nullptr : &status);
        if (test == "status-present") assert(pte && status == kIOReturnSuccess);
        else if (test == "status-absent") assert(!pte && status == kIOReturnSuccess);
        else if (test == "status-capacity") assert(!pte && status == kIOReturnNoMemory);
        else if (test == "status-corrupt") assert(!pte && status == kIOReturnVMError);
        else { assert(test == "status-no-output"); assert(!pte && status == kIOReturnBadArgument); }
        assert(!md.releases && p.leaves.empty());
    } else if (test == "map-real" || test == "unmap-real" || test == "free-real" ||
               test == "map-unbound-real" || test == "free-busy-real") {
        if (test == "map-unbound-real") { p.vm[0].hw = 0; p.hwv[0] = {}; }
        mapHealthy(p, c, v);
        if (test == "map-unbound-real") assert(!p.writes);
        if (test == "unmap-real") {
            auto u = gem(true); assert(gemCall(c, u) == kIOReturnSuccess);
            assert(!c.maps[0].used && !*leaf(p, v.va_address) && !*leaf(p, v.va_address + 4096));
            assert(!md.releases && gemCall(c, u) == kIOReturnSuccess);
        }
        if (test == "free-busy-real") p.aperture.words[32] = 4;
        assert(freeBo(c) == kIOReturnSuccess);
        if (test == "free-busy-real") {
            retained(c, md); pending(c, md); assert(*leaf(p, v.va_address));
            p.aperture.words[32] = 5; c.reapPending();
        }
        released(c, md); assert(!c.maps[0].used);
    } else if (test == "unmap-empty") {
        assert(p.vmUnmap(1, v.va_address, v.map_size) == kIOReturnSuccess);
        assert(p.vm[0].used == 1 && !md.releases && !c.maps[0].used);
    } else if (test == "map-conflicting-leaf") {
        auto *pte = leaf(p, v.va_address, true); *pte = 0x500000 | kPteSysFlags;
        const unsigned before = flushes;
        assert(gemCall(c, v) == kIOReturnExclusiveAccess && !c.maps[0].used);
        assert(*pte == (0x500000 | kPteSysFlags) && !md.releases && flushes == before);
    } else if (test == "map-oom" || test == "map-partial-oom") {
        p.vm[0].pages = test == "map-oom" ? 1 : 4;
        if (test == "map-partial-oom") v.va_address = 0x1ff000;
        assert(gemCall(c, v) == kIOReturnNoMemory && !c.maps[0].used && !c.hasPending());
        if (test == "map-partial-oom") { assert(p.vm[0].used == 4 && !*leaf(p, v.va_address)); }
        assert(freeBo(c) == kIOReturnSuccess); released(c, md);
    } else if (test == "unmap-late-corrupt") {
        v.va_address = 0x1ff000; mapHealthy(p, c, v);
        const TreeImage image(p); auto *first = leaf(p, v.va_address);
        const uint64_t value = *first; table(p, 2)[1] = 2;
        const unsigned before = flushes; auto u = v; u.operation = PHX_AMDGPU_VA_OP_UNMAP;
        assert(gemCall(c, u) == kIOReturnVMError && *first == value && flushes == before);
        pending(c, md); assert(freeBo(c) == kIOReturnSuccess); retained(c, md);
        image.restore(p); c.reapPending(); released(c, md);
    } else if (test == "unmap-changes-during-clear") {
        mapHealthy(p, c, v); const TreeImage image(p);
        auto *first = leaf(p, v.va_address), *second = leaf(p, v.va_address + 4096);
        flushHook = [&](void *address) { if (address == first && !*first) table(p)[0] = 2; };
        auto u = gem(true); assert(gemCall(c, u) == kIOReturnVMError);
        assert(!*first && *second && !p.hwv[0].faulted); pending(c, md);
        flushHook = nullptr; assert(freeBo(c) == kIOReturnSuccess); retained(c, md);
        image.restore(p); c.reapPending(); released(c, md);
    } else if (test == "free-host-corrupt") {
        c.bos[1].host = true; c.hostUsed = 8192; c.gttUsed = 0;
        mapHealthy(p, c, v); const TreeImage image(p); table(p)[0] = 2;
        assert(freeBo(c) == kIOReturnSuccess); pending(c, md);
        assert(c.bos[1].pendingFree && c.hostUsed == 8192 && !md.completes && !md.releases);
        image.restore(p); c.reapPending(); released(c, md, true);
    } else if (test == "submit-corrupt-map") {
        mapHealthy(p, c, v); const TreeImage image(p); table(p)[0] = 2;
        auto u = gem(true); assert(gemCall(c, u) == kIOReturnVMError); pending(c, md);
        struct { phxn_cs_in h; phxn_cs_ib ib; } packet{};
        packet.h.abi = PHXN_ABI_VERSION; packet.h.ctx_id = 1; packet.h.num_ibs = 1;
        packet.ib.va_start = v.va_address; packet.ib.ib_bytes = 16; packet.ib.ip_type = PHX_AMDGPU_HW_IP_COMPUTE;
        IOExternalMethodArguments a; a.scalarOutputCount = 1; a.structureInput = &packet; a.structureInputSize = sizeof(packet);
        assert(c.doSubmit(&a) == kIOReturnBusy && !p.submissions && !c.flushCalls && !md.releases);
        image.restore(p); assert(freeBo(c) == kIOReturnSuccess); released(c, md);
    } else if (test == "map-corrupt-after-preflight" || test == "map-corrupt-after-first-write" ||
               test == "map-rollback-missing-branch" || test == "map-rollback-invalid-branch" ||
               test == "map-rollback-leaf-mismatch" || test == "map-rollback-segment-changed" ||
               test == "map-rollback-segment-unavailable" ||
               test == "map-leaf-became-occupied" || test == "map-rollback-success" || test == "map-rollback-timeout") {
        auto *first = leaf(p, v.va_address, true); const TreeImage image(p);
        if (test == "map-rollback-success" || test == "map-rollback-timeout" ||
            test.rfind("map-rollback-", 0) == 0) md.badCall = 4;
        if (test == "map-rollback-timeout") p.timeout = true;
        if (test == "map-corrupt-after-first-write")
            flushHook = [&](void *address) { if (address == first && *first) table(p)[0] = 2; };
        segmentHook = [&](IOMemoryDescriptor &b, uint64_t) {
            if (&b != &md) return;
            if (test == "map-corrupt-after-preflight" && b.calls == 3) table(p)[0] = 2;
            if (test == "map-leaf-became-occupied" && b.calls == 3) *first = 0x500000 | kPteSysFlags;
            if (b.calls == 4) {
                if (test == "map-rollback-missing-branch") table(p)[0] = 0;
                if (test == "map-rollback-invalid-branch") table(p)[0] = 2;
                if (test == "map-rollback-leaf-mismatch") *first = 0x500000 | kPteSysFlags;
            }
            if (test == "map-rollback-segment-changed" && b.calls == 5) b.physical = 0x500000;
            if (test == "map-rollback-segment-unavailable" && b.calls == 5) b.physical = 0;
        };
        assert(gemCall(c, v) == (test == "map-rollback-timeout" ? kIOReturnTimeout : kIOReturnVMError));
        flushHook = nullptr; segmentHook = nullptr;
        if (test == "map-rollback-success") {
            assert(!c.maps[0].used && !c.hasPending() && !*first && !md.releases);
        } else {
            pending(c, md);
            if (test == "map-corrupt-after-first-write" || test == "map-rollback-missing-branch" ||
                test == "map-rollback-invalid-branch" || test == "map-rollback-leaf-mismatch" ||
                test == "map-rollback-segment-changed" || test == "map-rollback-segment-unavailable" ||
                test == "map-leaf-became-occupied") assert(*first);
            if (test == "map-rollback-timeout") assert(p.hwv[0].faulted);
        }
        image.restore(p); md.physical = 0x400000; p.timeout = false;
        assert(freeBo(c) == kIOReturnSuccess); released(c, md); assert(!c.maps[0].used);
    } else if (test == "unmap-timeout-real") {
        mapHealthy(p, c, v); p.timeout = true; auto u = gem(true);
        assert(gemCall(c, u) == kIOReturnTimeout && p.hwv[0].faulted); pending(c, md);
        p.timeout = false; assert(freeBo(c) == kIOReturnSuccess); released(c, md);
    } else if (test.rfind("map-corrupt-", 0) == 0 || test.rfind("unmap-corrupt-", 0) == 0) {
        const bool unmap = test.rfind("unmap-corrupt-", 0) == 0;
        if (unmap) mapHealthy(p, c, v);
        auto *pte = leaf(p, v.va_address, true); const TreeImage image(p);
        const std::string mode = test.substr(unmap ? 14 : 12);
        damage(p, mode, pte); const unsigned before = flushes;
        const auto *bytes = static_cast<const uint8_t *>(p.vm[0].chunk[0]->storage);
        const std::vector<uint8_t> damaged(bytes, bytes + 65536);
        auto operation = v; if (unmap) operation.operation = PHX_AMDGPU_VA_OP_UNMAP;
        assert(gemCall(c, operation) == kIOReturnVMError && flushes == before);
        assert(std::equal(damaged.begin(), damaged.end(), bytes)); pending(c, md);
        assert(freeBo(c) == kIOReturnSuccess); retained(c, md);
        image.restore(p); c.reapPending(); released(c, md);
    } else assert(false);
    assert(p.mutex == 0 && p.leaves.empty());
    for (const auto &b : pageDescriptors) assert(!b->releases && !b->completes);
    std::cout << "{\"case\":\"" << test << "\",\"passed\":true,\"hardware_executed\":false}\n";
}
