// Manual target acceptance probe. No raw debug writes, queue adoption or driver installation.
#include <IOKit/IOKitLib.h>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/utsname.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "PhxNativeABI.h"
#include "PhxMesQueueLayout.h"
#include "gfx11_shader_probe.h"

static constexpr size_t bytes = 16384;
static constexpr uint64_t vaMask = (1ull << 48) - 1;

static int reject(const char *reason) {
    fprintf(stderr, "FAIL: native shader probe %s; stopping\n", reason);
    return 75;
}

static int pciValue(io_registry_entry_t entry, CFStringRef key, uint32_t *out) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(entry, key, kCFAllocatorDefault, 0);
    if (!value) return 0;
    int valid = 0;
    if (CFGetTypeID(value) == CFDataGetTypeID() && CFDataGetLength((CFDataRef)value) == 4) {
        const UInt8 *p = CFDataGetBytePtr((CFDataRef)value);
        if (p) { *out = p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; valid = 1; }
    } else if (CFGetTypeID(value) == CFNumberGetTypeID()) {
        int64_t number = -1;
        if (CFNumberGetValue((CFNumberRef)value, kCFNumberSInt64Type, &number) && number >= 0 && number <= UINT32_MAX) {
            *out = (uint32_t)number; valid = 1;
        }
    }
    CFRelease(value);
    return valid;
}

static int targetService(io_service_t *chosen) {
    *chosen = IO_OBJECT_NULL;
    CFMutableDictionaryRef matching = IOServiceMatching("PhxBringup");
    if (!matching) return 4;
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iterator) != KERN_SUCCESS) return 74;
    if (!iterator) return 74;
    unsigned count = 0;
    int status = 0;
    for (io_service_t service; (service = IOIteratorNext(iterator));) {
        io_registry_entry_t parent = IO_OBJECT_NULL;
        uint32_t vendor = 0, product = 0;
        bool target = false;
        if (IORegistryEntryGetParentEntry(service, kIOServicePlane, &parent) == KERN_SUCCESS) {
            target = IOObjectConformsTo(parent, "IOPCIDevice") &&
                pciValue(parent, CFSTR("vendor-id"), &vendor) && pciValue(parent, CFSTR("device-id"), &product) &&
                vendor == 0x1002 && product == 0x1900;
            if (IOObjectRelease(parent) != KERN_SUCCESS) status = 74;
        }
        if (target && ++count == 1) *chosen = service;
        else if (IOObjectRelease(service) != KERN_SUCCESS) status = 74;
    }
    if (IOObjectRelease(iterator) != KERN_SUCCESS) status = 74;
    if (status || count != 1) {
        if (*chosen) IOObjectRelease(*chosen);
        *chosen = IO_OBJECT_NULL;
        return status ? status : 4;
    }
    return 0;
}

static bool call(io_connect_t connection, uint32_t selector, const uint64_t *input, uint32_t inputCount,
    const void *data, size_t dataBytes, uint64_t *output, uint32_t outputCount, void *reply, size_t replyBytes) {
    uint32_t count = outputCount;
    size_t size = replyBytes;
    const kern_return_t result = IOConnectCallMethod(connection, selector, input, inputCount, data, dataBytes,
        output, outputCount ? &count : nullptr, reply, replyBytes ? &size : nullptr);
    if (result != KERN_SUCCESS || count != outputCount || size != replyBytes) {
        fprintf(stderr, "FAIL: native selector %u status/shape; stopping\n", selector);
        return false;
    }
    return true;
}

struct Session {
    io_connect_t connection{};
    uint32_t handle{}, context{};
    uint64_t gpuVA{};
    mach_vm_address_t cpu{};
    mach_vm_size_t cpuBytes{};
    bool cpuMapped{false};
};

static int exercise(Session &s, bool execute, bool upper) {
    const uint64_t helloIn[] = {PHXN_ABI_VERSION, PHXN_HELLO_F_MINOR};
    uint64_t hello[4]{};
    if (!call(s.connection, PHXN_SEL_HELLO, helloIn, 2, nullptr, 0, hello, 4, nullptr, 0)) return 74;
    if (hello[0] != (PHXN_ABI_VERSION | (uint64_t)PHXN_ABI_MINOR << 16) ||
        hello[2] != PHXN_MAX_IBS || hello[3] != PHXN_VMID) return reject("HELLO ABI/limits mismatch");
    phxn_info info{};
    if (!call(s.connection, PHXN_SEL_QUERYINFO, nullptr, 0, nullptr, 0, nullptr, 0, &info, sizeof(info))) return 74;
    if (info.abi_version != PHXN_ABI_VERSION || info.reserved[2] != PHXN_ABI_MINOR ||
        info.kext_build != hello[1] || info.vmid != PHXN_VMID || info.gc_version != ((11u << 16) | 1u) ||
        (info.flags & (PHXN_INFO_HUNG | PHXN_INFO_NATIVE_BOOT | PHXN_INFO_S1B_POSITIVE)) !=
        (PHXN_INFO_NATIVE_BOOT | PHXN_INFO_S1B_POSITIVE) || info.max_ibs != PHXN_MAX_IBS)
        return reject("QUERYINFO ABI, IP or readiness mismatch");
    if (!execute) return 0;
    const uint64_t first = upper ? info.va_high_first : info.va_low_first;
    const uint64_t last = upper ? info.va_high_last : info.va_low_last;
    if ((first & 4095) || first > last || bytes - 1 > last - first ||
        (!upper && (first < 0x10000 || last > 0x7fffffffffffull)) ||
        (upper && first < 0xffff800000000000ull) ||
        (first & vaMask) > vaMask - (bytes - 1)) return reject("reported VA range invalid");
    s.gpuVA = first;
    phxn_ctx ctx{PHX_AMDGPU_CTX_OP_ALLOC_CTX, 0, 0, 0}, ctxOut{};
    if (!call(s.connection, PHXN_SEL_CTX, nullptr, 0, &ctx, sizeof(ctx), nullptr, 0, &ctxOut, sizeof(ctxOut))) return 74;
    if (!ctxOut.op || ctxOut.op > PHXN_MAX_CTX || ctxOut.flags || ctxOut.ctx_id || ctxOut.priority)
        return reject("allocated context reply invalid");
    s.context = ctxOut.op;
    const phxn_gem_create_in create{bytes, 4096, PHX_AMDGPU_GEM_DOMAIN_GTT, PHX_AMDGPU_GEM_CREATE_CPU_ACCESS_REQUIRED};
    uint64_t bo[4]{};
    if (!call(s.connection, PHXN_SEL_BOCREATE, nullptr, 0, &create, sizeof(create), bo, 4, nullptr, 0)) return 74;
    if (!bo[0] || bo[0] >= PHXN_MAX_BOS || bo[1] != bytes || bo[2] != PHX_AMDGPU_GEM_DOMAIN_GTT ||
        !(bo[3] & PHXN_PLACED_ZEROED) || (bo[3] & ~(uint64_t)(PHXN_PLACED_ZEROED | PHXN_PLACED_CPU_MAPPABLE)))
        return reject("created BO reply invalid");
    s.handle = (uint32_t)bo[0];
    if (IOConnectMapMemory64(s.connection, s.handle, mach_task_self(), &s.cpu, &s.cpuBytes, kIOMapAnywhere) != KERN_SUCCESS)
        return 74;
    s.cpuMapped = true;
    if (!s.cpu || (s.cpu & 4095) || s.cpuBytes != bytes || s.cpu > UINTPTR_MAX - bytes)
        return reject("CPU mapping geometry invalid");
    phxn_gem_va map{};
    map.handle = s.handle; map.operation = PHX_AMDGPU_VA_OP_MAP; map.flags = PHX_AMDGPU_VM_PAGE_EXECUTABLE;
    map.va_address = s.gpuVA; map.map_size = bytes;
    if (!call(s.connection, PHXN_SEL_GEMVA, nullptr, 0, &map, sizeof(map), nullptr, 0, nullptr, 0)) return 74;
    uint8_t expected[bytes];
    uint64_t previous = 0;
    for (unsigned pass = 0; pass < 2; ++pass) {
        const uint32_t pattern[4] = {0x7800c0deu ^ pass, 0x13579bdfu + pass, 0x2468ace0u ^ (pass << 16), 0xc001d00du - pass};
        memset(expected, 0xa5, bytes);
        memset(expected, 0, 8192);
        memcpy(expected, phxGfx11ClearShader, sizeof(phxGfx11ClearShader));
        uint32_t commands[80]{};
        const uint64_t base = s.gpuVA & vaMask;
        if (phxGfx11DispatchCommands(commands, 80, base, base + 0x2010, pattern) != PHX_SHADER_DISPATCH_DWORDS)
            return reject("dispatch packet construction invalid");
        // The kernel appends its own retirement fence outside this user-VM IB.
        commands[78] = commands[79] = 0xffff1000u;
        memcpy(expected + 4096, commands, sizeof(commands));
        for (unsigned i = 0; i < 256; ++i) {
            const uint32_t poison = ~pattern[i & 3];
            memcpy(expected + 0x2010 + i * 4, &poison, 4);
        }
        memcpy(reinterpret_cast<void *>(s.cpu), expected, bytes);
        __sync_synchronize();
        for (unsigned i = 0; i < 256; ++i) memcpy(expected + 0x2010 + i * 4, &pattern[i & 3], 4);
        struct Request { phxn_cs_in header; phxn_cs_ib ib; } request{};
        static_assert(sizeof(Request) == 64, "one native IB request");
        request.header.abi = PHXN_ABI_VERSION; request.header.ctx_id = s.context; request.header.num_ibs = 1;
        request.ib.va_start = s.gpuVA + 4096; request.ib.ib_bytes = sizeof(commands);
        request.ib.ip_type = PHX_AMDGPU_HW_IP_COMPUTE;
        uint64_t sequence = 0;
        if (!call(s.connection, PHXN_SEL_SUBMIT, nullptr, 0, &request, sizeof(request), &sequence, 1, nullptr, 0)) return 74;
        if (!sequence || sequence == PHXN_SEQ_LAST || sequence <= previous) return reject("submitted sequence invalid");
        const uint64_t waitIn[] = {sequence, PHXN_WAIT_CAP_NS, 0};
        uint64_t waitOut[3]{};
        if (!call(s.connection, PHXN_SEL_WAITSEQ, waitIn, 3, nullptr, 0, waitOut, 3, nullptr, 0)) return 74;
        if (waitOut[0] || waitOut[1] < sequence || waitOut[2] != sequence || waitOut[1] == PHXN_SEQ_LAST)
            return reject("positive retirement not established");
        __sync_synchronize();
        const volatile uint8_t *actual = reinterpret_cast<const volatile uint8_t *>(s.cpu);
        for (size_t i = 0; i < bytes; ++i) if (actual[i] != expected[i]) {
            fprintf(stderr, "FAIL: native shader output/code/IB/guard mismatch at byte %zu\n", i);
            return 75;
        }
        previous = sequence;
    }
    return 0;
}

static int finish(Session &s, int result, bool execute) {
    if (s.cpuMapped && IOConnectUnmapMemory64(s.connection, s.handle, mach_task_self(), s.cpu) != KERN_SUCCESS) result = 74;
    if (!result && execute) {
        phxn_gem_va unmap{};
        unmap.handle = s.handle; unmap.operation = PHX_AMDGPU_VA_OP_UNMAP; unmap.va_address = s.gpuVA; unmap.map_size = bytes;
        if (!call(s.connection, PHXN_SEL_GEMVA, nullptr, 0, &unmap, sizeof(unmap), nullptr, 0, nullptr, 0)) result = 74;
        const uint64_t freeIn[] = {s.handle};
        if (!result && !call(s.connection, PHXN_SEL_BOFREE, freeIn, 1, nullptr, 0, nullptr, 0, nullptr, 0)) result = 74;
        phxn_ctx ctx{PHX_AMDGPU_CTX_OP_FREE_CTX, 0, s.context, 0}, reply{};
        if (!result && !call(s.connection, PHXN_SEL_CTX, nullptr, 0, &ctx, sizeof(ctx), nullptr, 0, &reply, sizeof(reply))) result = 74;
        if (!result && (reply.op || reply.flags || reply.ctx_id || reply.priority)) result = reject("context release reply invalid");
    }
    if (IOServiceClose(s.connection) != KERN_SUCCESS) result = 74;
    return result;
}

int main(int argc, char *argv[]) {
    const bool execute = argc >= 2 && !strcmp(argv[1], "--run");
    const bool upper = argc == 3 && !strcmp(argv[2], "--upper");
    if ((argc != 2 && argc != 3) || (!execute && strcmp(argv[1], "--check")) || (argc == 3 && !upper)) {
        fprintf(stderr, "usage: native-shader-probe --check|--run [--upper]\n"); return 64;
    }
    utsname host{};
    if (uname(&host) || strcmp(host.sysname, "Darwin") || strcmp(host.machine, "x86_64") || strncmp(host.release, "25.", 3)) {
        fprintf(stderr, "REFUSED: requires Intel Darwin 25; no GPU work submitted\n"); return 4;
    }
    io_service_t service = IO_OBJECT_NULL;
    int result = targetService(&service);
    if (result) { fprintf(stderr, "REFUSED: requires exactly one PCI-verified 1002:1900 PhxBringup service\n"); return result; }
    Session s;
    const kern_return_t opened = IOServiceOpen(service, mach_task_self(), PHXN_UC_TYPE, &s.connection);
    const kern_return_t released = IOObjectRelease(service);
    if (opened != KERN_SUCCESS || !s.connection) return 74;
    if (released != KERN_SUCCESS) return finish(s, 74, false);
    result = finish(s, exercise(s, execute, upper), execute);
    if (!result) puts(execute ? "PASS: native GPUVM shader probe; two guarded dispatches, not Metal or display acceptance" :
        "CHECK: target identity and ABI readiness only; no GPU work submitted");
    return result;
}
