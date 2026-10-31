// Actual native submission diagnostics with small/red-zoned CPU allocations.
#define PHX_NO_BO_TEST_MAIN
#include "test_bo_retirement.cpp"
#include <algorithm>

static unsigned logRows, expectedLogWords, expectedLogIbs;
static unsigned initialEmission;
static const uint32_t *expectedLogData;
static void inspectLog(const char *format, va_list arguments) {
    assert(!std::strcmp(format, "PhxIB %u.%u +%02x: %08x %08x %08x %08x %08x %08x %08x %08x\n"));
    const auto sequence = va_arg(arguments, unsigned);
    const auto ib = va_arg(arguments, unsigned);
    const auto offset = va_arg(arguments, unsigned);
    const unsigned rowsPerIb = (expectedLogWords + 7) / 8;
    assert(rowsPerIb && ib < expectedLogIbs && sequence == initialEmission + 1);
    assert(ib == logRows / rowsPerIb && offset == (logRows % rowsPerIb) * 8);
    for (unsigned j = 0; j < 8; ++j) {
        const auto word = va_arg(arguments, unsigned);
        assert(word == (offset + j < expectedLogWords ? expectedLogData[offset + j] : 0));
    }
    ++logRows;
}
int main(int argc, char **argv) {
    assert(argc == 3);
    const bool upper = !std::strcmp(argv[1], "upper"); assert(upper || !std::strcmp(argv[1], "low"));
    const std::string test = argv[2];
    PhxBringup p; IOAccelPhxNativeClient c(p);
    p.debug = true; c.emitted = c.lastSeq = 0;
    IOMemoryDescriptor first, second;
    std::vector<uint32_t> storage(1024), peer(1024);
    for (unsigned i = 0; i < storage.size(); ++i) storage[i] = 0x78000000u + i;
    for (unsigned i = 0; i < peer.size(); ++i) peer[i] = 0x78100000u + i;
    uint64_t start = 0x30000, mapOffset = 0;
    unsigned dwords = 4, ibs = 1, prefix = 4;
    bool crosses = false, reject = false;
    if (test.rfind("cross-", 0) == 0) {
        prefix = static_cast<unsigned>(std::stoul(test.substr(6))); assert(prefix <= 1024 && prefix);
        start += 4096 - prefix * 4; dwords = prefix + 16; crosses = true;
    } else if (test.rfind("length-", 0) == 0) {
        dwords = static_cast<unsigned>(std::stoul(test.substr(7))); assert(dwords && dwords <= 1024);
    } else if (test == "offset-map") {
        storage.resize(2048); mapOffset = 4096;
        for (unsigned i = 1024; i < storage.size(); ++i) storage[i] = 0x78000000u + i;
        start += 4092; dwords = 17; prefix = 1; crosses = true;
    } else if (test == "multi-two" || test == "multi-max" || test == "graphics" || test == "debug-disabled" ||
               test == "emission-limit" || test == "emission-last" || test == "opaque-first" || test == "opaque-peer") {
        start += 4092; dwords = 17; prefix = 1; crosses = true;
        if (test == "multi-two") ibs = 2;
        if (test == "multi-max") ibs = PHXN_MAX_IBS;
        if (test == "graphics") { p.expectedSubmitGfx = true; p.gq[1].ready = true; }
        if (test == "debug-disabled") p.debug = false;
        if (test == "emission-limit") c.emitted = 4;
        if (test == "emission-last") c.emitted = 3;
    } else {
        const std::vector<std::string> faults = {"descriptor-prefix", "descriptor-offset-end", "descriptor-offset-past", "bo-prefix",
            "offset-overflow", "pointer-offset-overflow", "pointer-span-overflow", "pointer-unaligned", "missing-md", "unknown"};
        assert(std::find(faults.begin(), faults.end(), test) != faults.end() && test != "unknown");
    }
    if (upper) start |= 0xffffc00000000000ull;
    const uint64_t mapVa = (upper ? 0xc00000000000ull : 0) + 0x30000;
    first.length = storage.size() * 4; second.length = peer.size() * 4;
    c.bos[1] = {&first, storage.size() * 4, 2, 0, reinterpret_cast<uint8_t *>(storage.data()), false, false};
    c.bos[2] = {&second, peer.size() * 4, 2, 0, reinterpret_cast<uint8_t *>(peer.data()), false, false};
    c.maps[0] = {true, 1, mapVa, 4096, mapOffset, PHX_AMDGPU_VM_PAGE_EXECUTABLE, false};
    c.maps[1] = {true, 2, mapVa + 4096, 4096, 0, PHX_AMDGPU_VM_PAGE_EXECUTABLE, false};
    c.gttUsed = c.bos[1].size + c.bos[2].size;
    expectedLogWords = std::min(96u, crosses ? prefix : dwords);
    expectedLogData = storage.data() + mapOffset / 4 + ((start & kVaMask) - mapVa) / 4;
    if (test == "opaque-first") c.bos[1].kva = nullptr;
    if (test == "opaque-peer") c.bos[2].kva = nullptr;
    if (test == "descriptor-prefix") { first.length = 4; expectedLogWords = 1; }
    if (test == "bo-prefix") { c.bos[1].size = 4; expectedLogWords = 1; }
    if (test == "descriptor-offset-end" || test == "descriptor-offset-past") {
        c.maps[0].off = 4096; first.length = test == "descriptor-offset-end" ? 4096 : 4095;
        c.bos[1].size = 8192; expectedLogWords = 0;
    }
    if (test == "offset-overflow") { c.maps[0].off = UINT64_MAX - 1; expectedLogWords = 0; }
    if (test == "pointer-offset-overflow") {
        c.bos[1].kva = reinterpret_cast<uint8_t *>(UINTPTR_MAX - 3); c.maps[0].off = 8; expectedLogWords = 0;
    }
    if (test == "pointer-span-overflow") {
        c.bos[1].kva = reinterpret_cast<uint8_t *>(UINTPTR_MAX - 3); expectedLogWords = 0;
    }
    if (test == "pointer-unaligned") { ++c.bos[1].kva; expectedLogWords = 0; }
    if (test == "missing-md") { c.bos[1].md = nullptr; expectedLogWords = 0; reject = true; }
    if (!p.debug || c.emitted >= 4 || test == "opaque-first") expectedLogWords = 0;
    expectedLogIbs = ibs; initialEmission = static_cast<unsigned>(c.emitted); logHook = inspectLog;
    struct Request { phxn_cs_in header; phxn_cs_ib ib[PHXN_MAX_IBS]; } packet{};
    packet.header.abi = PHXN_ABI_VERSION; packet.header.ctx_id = 1; packet.header.num_ibs = ibs;
    for (unsigned i = 0; i < ibs; ++i) {
        packet.ib[i].va_start = start; packet.ib[i].ib_bytes = dwords * 4;
        packet.ib[i].ip_type = p.expectedSubmitGfx ? PHX_AMDGPU_HW_IP_GFX : PHX_AMDGPU_HW_IP_COMPUTE;
    }
    p.expectedSubmitVa.assign(ibs, start & kVaMask); p.expectedSubmitDw.assign(ibs, dwords);
    IOExternalMethodArguments args; args.scalarOutputCount = 1; args.scalarOutput[0] = UINT64_MAX;
    args.structureInput = &packet; args.structureInputSize = sizeof(packet.header) + ibs * sizeof(phxn_cs_ib);
    const auto firstImage = storage, peerImage = peer;
    const auto mapImage = c.mapStorage;
    const auto result = c.doSubmit(&args);
    assert(result == (reject ? kIOReturnBadArgument : kIOReturnSuccess));
    assert(logRows == ((expectedLogWords + 7) / 8) * ibs);
    assert(storage == firstImage && peer == peerImage && !first.releases && !second.releases);
    assert(c.mapStorage.size() == mapImage.size());
    for (unsigned i = 0; i < c.mapStorage.size(); ++i) {
        const auto &a = c.maps[i], &b = mapImage[i];
        assert(a.used == b.used && a.handle == b.handle && a.va == b.va && a.size == b.size && a.off == b.off &&
            a.flags == b.flags && a.pending == b.pending);
    }
    assert(p.submissions == unsigned(!reject) && c.flushCalls == unsigned(!reject));
    assert(args.scalarOutput[0] == (reject ? UINT64_MAX : 6));
    assert(!p.mutex);
    std::cout << "{\"case\":\"" << test << "\",\"variant\":\"" << argv[1] << "\",\"log_rows\":" << logRows <<
        ",\"prefix_words\":" << expectedLogWords << ",\"ibs\":" << ibs << ",\"submissions\":" << p.submissions <<
        ",\"passed\":true,\"hardware_executed\":false}\n";
}
