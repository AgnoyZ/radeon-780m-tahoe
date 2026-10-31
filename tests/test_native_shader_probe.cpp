// Runs the actual userspace probe with injected ABI responses; no ISA execution.
#include <assert.h>
#include <stdlib.h>
#include <string>
#include <vector>
#include <sys/utsname.h>
static int fake_uname(struct utsname *);
#define uname fake_uname
#define main native_probe_main
#include "../tools/native_shader_probe.cpp"
#undef main
#undef uname

static std::string fault;
static bool upper, failed, opened, mapped, gpuMapped;
static unsigned nextService, propertyLive, allocated, created, submitted, waited;
static mach_vm_address_t mappedAddress;
static std::vector<std::string> events;
alignas(4096) static uint8_t backing[16384];
static bool is(const std::string &name) { return fault == name; }
static void event(const std::string &name) { events.push_back(name); }
static uint64_t virtualBase() { return upper ? 0xffffc02134500000ull : 0x402134500000ull; }
static int fake_uname(struct utsname *host) {
    event("host");
    strcpy(host->sysname, is("host-linux") ? "Linux" : "Darwin");
    strcpy(host->machine, is("host-arm") ? "arm64" : "x86_64");
    strcpy(host->release, is("host-sonoma") ? "23.6.0" : is("host-prefix") ? "250.0" : "25.1.0");
    return is("host-status") ? -1 : 0;
}
mach_port_t mach_task_self() { return 1; }
CFMutableDictionaryRef IOServiceMatching(const char *name) {
    event("matching"); assert(!strcmp(name, "PhxBringup"));
    return is("matching-null") ? nullptr : reinterpret_cast<void *>(1);
}
kern_return_t IOServiceGetMatchingServices(mach_port_t port, CFMutableDictionaryRef dictionary, io_iterator_t *out) {
    event("enumerate"); assert(!port && dictionary && out);
    *out = is("iterator-null") ? 0 : 10;
    return is("enumerate-status") ? 1 : 0;
}
io_object_t IOIteratorNext(io_iterator_t iterator) {
    assert(iterator == 10);
    if (is("no-service")) return 0;
    const unsigned count = (is("ambiguous") || is("mixed-services")) ? 2 : 1;
    return nextService < count ? 11 + nextService++ : 0;
}
kern_return_t IORegistryEntryGetParentEntry(io_registry_entry_t service, const char *plane, io_registry_entry_t *out) {
    event("parent"); assert((service == 11 || service == 12) && !strcmp(plane, kIOServicePlane));
    *out = service + 10;
    return is("parent-status") ? 1 : 0;
}
bool IOObjectConformsTo(io_object_t parent, const char *name) {
    assert((parent == 21 || parent == 22) && !strcmp(name, "IOPCIDevice"));
    return !is("non-pci") && !(is("mixed-services") && parent == 21);
}
struct FakeCF { unsigned kind; int64_t number; uint8_t data[4]; bool device; };
static FakeCF property;
CFTypeRef IORegistryEntryCreateCFProperty(io_registry_entry_t parent, CFStringRef key, CFAllocatorRef allocator, uint32_t options) {
    assert((parent == 21 || parent == 22) && !allocator && !options && !propertyLive);
    const bool device = !strcmp(key, "device-id");
    assert(device || !strcmp(key, "vendor-id"));
    const std::string prefix = device ? "device" : "vendor";
    event(prefix);
    if (is(prefix + "-missing")) return nullptr;
    int64_t value = device ? 0x1900 : 0x1002;
    if (is(prefix + "-wrong")) ++value;
    if (is(prefix + "-negative")) value = -1;
    if (is(prefix + "-wide")) value = 1ll << 32;
    const unsigned kind = (is("number-ok") || is(prefix + "-negative") || is(prefix + "-wide") ||
        is(prefix + "-number-status")) ? 2 : is(prefix + "-type") ? 3 : 1;
    property = {kind, value, {static_cast<uint8_t>(value), static_cast<uint8_t>(value >> 8),
        static_cast<uint8_t>(value >> 16), static_cast<uint8_t>(value >> 24)}, device};
    ++propertyLive; return &property;
}
CFTypeID CFGetTypeID(CFTypeRef p) { assert(p == &property && propertyLive); return p->kind; }
CFTypeID CFDataGetTypeID() { return 1; }
CFTypeID CFNumberGetTypeID() { return 2; }
CFIndex CFDataGetLength(CFDataRef p) {
    return is(std::string(p->device ? "device" : "vendor") + "-short") ? 3 :
        is(std::string(p->device ? "device" : "vendor") + "-long") ? 5 : 4;
}
const UInt8 *CFDataGetBytePtr(CFDataRef p) {
    return is(std::string(p->device ? "device" : "vendor") + "-null") ? nullptr : p->data;
}
bool CFNumberGetValue(CFNumberRef p, int type, void *out) {
    assert(type == kCFNumberSInt64Type && out); *static_cast<int64_t *>(out) = p->number;
    return !is(std::string(p->device ? "device" : "vendor") + "-number-status");
}
void CFRelease(CFTypeRef p) { assert(p == &property && propertyLive == 1); --propertyLive; }
kern_return_t IOObjectRelease(io_object_t object) {
    const char *kind = object == 10 ? "release-iterator" : object == 21 || object == 22 ? "release-parent" : "release-service";
    assert(object >= 10 && object <= 22); event(kind);
    if (is(kind) || (is("release-open-service") && opened && object == 11)) return 1;
    return 0;
}
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *out) {
    event("open"); assert((service == 11 || service == 12) && task == 1 && type == PHXN_UC_TYPE);
    *out = is("open-null") ? 0 : 99;
    opened = !is("open-status") && *out;
    return is("open-status") ? 1 : 0;
}
kern_return_t IOServiceClose(io_connect_t connection) {
    event("close"); assert(connection == 99 && opened); opened = false;
    return is("close-status") ? 1 : 0;
}
static kern_return_t respond(const std::string &name, uint32_t *count, size_t *size) {
    if (is(name + "-status")) { failed = true; return 1; }
    if (is(name + "-short") || is(name + "-long")) {
        const int delta = is(name + "-short") ? -1 : 1;
        if (count) *count += delta;
        else { assert(size); *size += delta; }
        failed = true;
    }
    return 0;
}
static void checkStaged(unsigned pass) {
    const uint32_t pattern[] = {0x7800c0deu ^ pass, 0x13579bdfu + pass, 0x2468ace0u ^ (pass << 16), 0xc001d00du - pass};
    const uint64_t code = virtualBase() & ((1ull << 48) - 1), target = code + 0x2010;
    const uint32_t packet[] = {
        0xc0065800u, 0, 0xffffffffu, 0xff, 0, 0, 10, 0xc381,
        0xc0037602u, 0x204, 0, 0, 0, 0xc0017602u, 0x218, 0, 0xc0017602u, 0x222, 0,
        0xc0047602u, 0x224, 0, 0, 0, 0, 0xc0017900u, 0x22a, 0,
        0xc0029b02u, 0x30000216, 0xffffffffu, 0xffffffffu, 0xc0029b02u, 0x30000219, 0xffffffffu, 0xffffffffu,
        0xc0027602u, 0x20c, static_cast<uint32_t>(code >> 8), static_cast<uint32_t>(code >> 40),
        0xc0017602u, 0x212, 0x400c0041, 0xc0017602u, 0x213, 0x90,
        0xc0017602u, 0x207, 64, 0xc0017602u, 0x208, 1, 0xc0017602u, 0x209, 1,
        0xc0017602u, 0x228, 0x3f0, 0xc0047602u, 0x240, static_cast<uint32_t>(target),
        static_cast<uint32_t>(target >> 32) | 0x100000u, 64, 0x1003dfac,
        0xc0047602u, 0x244, pattern[0], pattern[1], pattern[2], pattern[3],
        0xc0017602u, 0x215, 0, 0xc0031502u, 1, 1, 1, 1, 0xffff1000u, 0xffff1000u
    };
    static_assert(sizeof(packet) == 320, "independent native IB recipe");
    uint8_t image[16384]; memset(image, 0xa5, sizeof(image)); memset(image, 0, 8192);
    memcpy(image, phxGfx11ClearShader, sizeof(phxGfx11ClearShader));
    memcpy(image + 4096, packet, sizeof(packet));
    for (unsigned i = 0; i < 256; ++i) {
        const uint32_t value = ~pattern[i & 3]; memcpy(image + 0x2010 + i * 4, &value, 4);
    }
    assert(!memcmp(image, backing, sizeof(image)));
}
kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector, const uint64_t *in, uint32_t inCount,
    const void *data, size_t dataBytes, uint64_t *out, uint32_t *outCount, void *reply, size_t *replyBytes) {
    assert(connection == 99 && opened && !failed);
    std::string name;
    switch (selector) {
    case PHXN_SEL_HELLO:
        name = "hello"; event(name);
        assert(in && inCount == 2 && in[0] == 1 && in[1] == PHXN_HELLO_F_MINOR && !data && !dataBytes &&
            out && outCount && *outCount == 4 && !reply && !replyBytes);
        out[0] = PHXN_ABI_VERSION | (uint64_t)PHXN_ABI_MINOR << 16; out[1] = 12; out[2] = 64; out[3] = 8;
        if (is("hello-abi")) ++out[0];
        if (is("hello-limit")) --out[2];
        if (is("hello-vmid")) --out[3];
        break;
    case PHXN_SEL_QUERYINFO: {
        name = "info"; event(name);
        assert(!in && !inCount && !data && !dataBytes && !out && !outCount && reply && replyBytes && *replyBytes == 192);
        auto &info = *static_cast<phxn_info *>(reply); info = {};
        info.abi_version = 1; info.kext_build = 12; info.vmid = 8; info.gc_version = (11u << 16) | 1;
        info.reserved[2] = PHXN_ABI_MINOR; info.max_ibs = 64;
        info.flags = PHXN_INFO_NATIVE_BOOT | PHXN_INFO_S1B_POSITIVE;
        info.va_low_first = 0x402134500000ull; info.va_low_last = info.va_low_first + 0xffff;
        info.va_high_first = 0xffffc02134500000ull; info.va_high_last = info.va_high_first + 0xffff;
        if (is("info-abi")) ++info.abi_version;
        if (is("info-minor")) --info.reserved[2];
        if (is("info-build")) ++info.kext_build;
        if (is("info-vmid")) --info.vmid;
        if (is("info-gc")) ++info.gc_version;
        if (is("info-limit")) --info.max_ibs;
        if (is("info-hung")) info.flags |= PHXN_INFO_HUNG;
        if (is("info-not-native")) info.flags &= ~PHXN_INFO_NATIVE_BOOT;
        if (is("info-not-ready")) info.flags &= ~PHXN_INFO_S1B_POSITIVE;
        uint64_t &first = upper ? info.va_high_first : info.va_low_first;
        uint64_t &last = upper ? info.va_high_last : info.va_low_last;
        if (is("va-unaligned")) ++first;
        if (is("va-reversed")) last = first - 1;
        if (is("va-short")) last = first + 16382;
        if (is("va-hole")) first = 0x800000000000ull;
        if (is("va-noncanonical")) { first = 0xfffe800000000000ull; last = UINT64_MAX; }
        if (is("va-null")) { first = 0; last = 0xffff; }
        if (is("va-wrap")) { first = 0xfffffffffffff000ull; last = UINT64_MAX; }
        if (is("va-exact")) last = first + 16383;
        if (is("va-low-wide")) last = 0x800000000000ull;
        break;
    }
    case PHXN_SEL_CTX: {
        assert(!in && !inCount && data && dataBytes == 16 && !out && !outCount && reply && replyBytes && *replyBytes == 16);
        const auto &ctx = *static_cast<const phxn_ctx *>(data); auto &result = *static_cast<phxn_ctx *>(reply); result = {};
        if (ctx.op == PHX_AMDGPU_CTX_OP_ALLOC_CTX) {
            name = "ctx-alloc"; event(name); assert(!ctx.flags && !ctx.ctx_id && !ctx.priority && !allocated);
            result.op = 7; ++allocated;
            if (is("ctx-alloc-zero")) result.op = 0;
            if (is("ctx-alloc-wide")) result.op = PHXN_MAX_CTX + 1;
        } else {
            name = "ctx-free"; event(name);
            assert(ctx.op == PHX_AMDGPU_CTX_OP_FREE_CTX && ctx.ctx_id == 7 && !ctx.flags && !ctx.priority && allocated && !created);
            --allocated;
            if (is("ctx-free-nonzero")) result.op = 7;
        }
        if (is(name + "-flags")) result.flags = 1;
        if (is(name + "-id")) result.ctx_id = 7;
        if (is(name + "-priority")) result.priority = -1;
        break;
    }
    case PHXN_SEL_BOCREATE: {
        name = "create"; event(name);
        assert(!in && !inCount && data && dataBytes == 32 && out && outCount && *outCount == 4 && !reply && !replyBytes && allocated);
        const auto &create = *static_cast<const phxn_gem_create_in *>(data);
        assert(create.bo_size == 16384 && create.alignment == 4096 && create.domains == 2 && create.domain_flags == 1);
        out[0] = 9; out[1] = 16384; out[2] = 2; out[3] = PHXN_PLACED_ZEROED; ++created;
        if (is("create-zero")) out[0] = 0;
        if (is("create-wide")) out[0] = 1ull << 32;
        if (is("create-limit")) out[0] = PHXN_MAX_BOS;
        if (is("create-size")) --out[1];
        if (is("create-domain")) out[2] = 4;
        if (is("create-unzeroed")) out[3] = 0;
        if (is("create-bits")) out[3] |= 0x100;
        if (is("create-mappable")) out[3] |= PHXN_PLACED_CPU_MAPPABLE;
        break;
    }
    case PHXN_SEL_GEMVA: {
        assert(!in && !inCount && data && dataBytes == 64 && !out && !outCount && !reply && !replyBytes && created);
        const auto &map = *static_cast<const phxn_gem_va *>(data);
        assert(map.handle == 9 && !map._pad && map.va_address == virtualBase() && !map.offset_in_bo && map.map_size == 16384 &&
            !map.vm_timeline_point && !map.vm_timeline_syncobj_out && !map.num_syncobj_handles && !map.input_fence_syncobj_handles);
        if (map.operation == PHX_AMDGPU_VA_OP_MAP) {
            name = "gpu-map"; assert(map.flags == 8 && mapped && !gpuMapped); gpuMapped = true;
        } else {
            name = "gpu-unmap"; assert(map.operation == 2 && !map.flags && gpuMapped && !mapped && waited == 2); gpuMapped = false;
        }
        event(name); break;
    }
    case PHXN_SEL_SUBMIT: {
        name = "submit-" + std::to_string(++submitted); event(name);
        assert(mapped && gpuMapped && submitted <= 2 && waited == submitted - 1);
        assert(!in && !inCount && data && dataBytes == 64 && out && outCount && *outCount == 1 && !reply && !replyBytes);
        phxn_cs_in header; phxn_cs_ib ib;
        memcpy(&header, data, 32); memcpy(&ib, static_cast<const uint8_t *>(data) + 32, 32);
        assert(header.abi == 1 && header.ctx_id == 7 && header.num_ibs == 1 && !header.flags && !header.fence_handle &&
            !header.fence_offset && !header.reserved && !ib._pad && !ib.flags && ib.va_start == virtualBase() + 4096 &&
            ib.ib_bytes == 320 && ib.ip_type == 1 && !ib.ip_instance && !ib.ring);
        checkStaged(submitted - 1); out[0] = 0x100000000ull + submitted;
        if (is(name + "-zero")) out[0] = 0;
        if (is(name + "-last")) out[0] = UINT64_MAX;
        if (is(name + "-repeat")) --out[0];
        break;
    }
    case PHXN_SEL_WAITSEQ: {
        name = "wait-" + std::to_string(++waited); event(name);
        const uint64_t sequence = 0x100000000ull + waited;
        assert(waited == submitted && in && inCount == 3 && in[0] == sequence && in[1] == PHXN_WAIT_CAP_NS && !in[2] &&
            !data && !dataBytes && out && outCount && *outCount == 3 && !reply && !replyBytes);
        out[0] = 0; out[1] = out[2] = sequence;
        if (is(name + "-timeout")) out[0] = 1;
        if (is(name + "-retired")) --out[1];
        if (is(name + "-last")) out[1] = UINT64_MAX;
        if (is(name + "-emitted")) ++out[2];
        if (is(name + "-missing")) break;
        const unsigned pass = waited - 1;
        const uint32_t pattern[] = {0x7800c0deu ^ pass, 0x13579bdfu + pass, 0x2468ace0u ^ (pass << 16), 0xc001d00du - pass};
        for (unsigned i = 0; i < 256; ++i) memcpy(backing + 0x2010 + i * 4, &pattern[i & 3], 4);
        for (const auto &prefix : {std::string("code"), std::string("ib"), std::string("output"), std::string("byte")}) {
            const std::string start = prefix + "-" + std::to_string(waited) + "-";
            if (fault.compare(0, start.size(), start) == 0) {
                const unsigned index = static_cast<unsigned>(std::stoul(fault.substr(start.size())));
                const unsigned offset = prefix == "code" ? index * 4 : prefix == "ib" ? 4096 + index * 4 :
                    prefix == "output" ? 0x2010 + index * 4 : index;
                assert(offset < sizeof(backing)); backing[offset] ^= 1;
            }
        }
        break;
    }
    case PHXN_SEL_BOFREE:
        name = "free"; event(name);
        assert(in && inCount == 1 && in[0] == 9 && !data && !dataBytes && !out && !outCount && !reply && !replyBytes &&
            !mapped && !gpuMapped && created); --created; break;
    default: assert(false);
    }
    return respond(name, outCount, replyBytes);
}
kern_return_t IOConnectMapMemory64(io_connect_t connection, uint32_t handle, mach_port_t task,
    mach_vm_address_t *address, mach_vm_size_t *size, unsigned options) {
    event("cpu-map"); assert(!failed && connection == 99 && handle == 9 && task == 1 && options == kIOMapAnywhere && created);
    if (is("cpu-map-status")) { failed = true; return 1; }
    mapped = true; *address = reinterpret_cast<uintptr_t>(backing); *size = sizeof(backing);
    if (is("cpu-map-zero")) *address = 0;
    if (is("cpu-map-unaligned")) ++*address;
    if (is("cpu-map-wrap")) *address = 0xfffffffffffff000ull;
    if (is("cpu-map-short")) --*size;
    if (is("cpu-map-long")) ++*size;
    mappedAddress = *address; return 0;
}
kern_return_t IOConnectUnmapMemory64(io_connect_t connection, uint32_t handle, mach_port_t task, mach_vm_address_t address) {
    event("cpu-unmap"); assert(connection == 99 && handle == 9 && task == 1 && mapped && address == mappedAddress);
    mapped = false;
    return is("cpu-unmap-status") ? 1 : 0;
}
static void packetInputs() {
    const uint64_t code = 0x402134500000ull, target = code + 0x2010;
    const uint32_t pattern[] = {1, 2, 3, 4};
    uint32_t packet[81];
    const uint64_t badCode[] = {0, code + 1, 1ull << 48, (1ull << 48) - 256};
    const uint64_t badTarget[] = {0, target + 1, (1ull << 48) - 16, code + 4080};
    for (const auto c : badCode) {
        memset(packet, 0xa5, sizeof(packet)); assert(!phxGfx11DispatchCommands(packet, 80, c, target, pattern));
        for (auto word : packet) assert(word == 0xa5a5a5a5);
    }
    for (const auto t : badTarget) {
        memset(packet, 0xa5, sizeof(packet)); assert(!phxGfx11DispatchCommands(packet, 80, code, t, pattern));
        for (auto word : packet) assert(word == 0xa5a5a5a5);
    }
    memset(packet, 0xa5, sizeof(packet));
    assert(!phxGfx11DispatchCommands(nullptr, 80, code, target, pattern));
    assert(!phxGfx11DispatchCommands(packet, 80, code, target, nullptr));
    assert(!phxGfx11DispatchCommands(packet, 77, code, target, pattern));
    for (auto word : packet) assert(word == 0xa5a5a5a5);
    assert(phxGfx11DispatchCommands(packet, 80, code, target, pattern) == 78);
    assert(packet[78] == 0xa5a5a5a5 && packet[79] == 0xa5a5a5a5 && packet[80] == 0xa5a5a5a5);
}
int main(int argc, const char *argv[]) {
    assert(argc == 3); upper = !strcmp(argv[1], "upper"); assert(upper || !strcmp(argv[1], "low")); fault = argv[2];
    packetInputs();
    const char *args[] = {"native-shader-probe", "--run", "--upper", "extra"}; int count = upper ? 3 : 2;
    if (is("check-ok")) args[1] = "--check";
    if (is("arg-missing")) count = 1;
    if (is("arg-mode")) args[1] = "--wat";
    if (is("arg-option")) { count = 3; args[2] = "--wat"; }
    if (is("arg-many")) count = 4;
    char *arguments[4];
    for (unsigned i = 0; i < 4; ++i) arguments[i] = const_cast<char *>(args[i]);
    const int result = native_probe_main(count, arguments);
    assert(!propertyLive && !opened && !mapped);
    fputs("fake-native-shader-summary {\"events\":[", stderr);
    for (size_t i = 0; i < events.size(); ++i) fprintf(stderr, "%s\"%s\"", i ? "," : "", events[i].c_str());
    fputs("]}\n", stderr);
    return result;
}
