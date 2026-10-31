/* Actual scheduler-query CLI with fake IOKit, memory and completions. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int fake_usleep(useconds_t);
#define usleep fake_usleep
#define main mesboot_reference_main
#include "mesboot.c"
#undef main
#undef usleep
static const char *fault;
static struct PhxBootMemory memory;
static uint64_t arena, va;
static uint32_t doorbell, registers[0x20000], words[4096];
static unsigned lookups, opens, hellos, snapshots, reads, writes, vreads, vwrites, bells, sleeps, closes;
static int is(const char *s) { return !strcmp(fault, s); }
static int indexed(const char *s, unsigned i) { char name[40]; snprintf(name, sizeof(name), "%s-%u", s, i); return is(name); }
static void summary(void) {
    fprintf(stderr, "fake-mes-queue-summary {\"lookups\":%u,\"opens\":%u,\"hellos\":%u,\"snapshots\":%u,"
        "\"reads\":%u,\"writes\":%u,\"vreads\":%u,\"vwrites\":%u,\"bells\":%u,\"sleeps\":%u,\"closes\":%u}\n",
        lookups, opens, hellos, snapshots, reads, writes, vreads, vwrites, bells, sleeps, closes);
}
static int fake_usleep(useconds_t delay) {
    assert(delay == 5000 && bells); ++sleeps;
    if (is("delay-error")) { errno = EIO; return -1; }
    if (is("delay-eintr")) { errno = EINTR; return -1; }
    return 0;
}
void *IOServiceMatching(const char *name) { assert(!strcmp(name, "PhxBringup")); return (void *)1; }
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching) {
    assert(!port && matching); ++lookups; return is("no-service") ? 0 : 1;
}
mach_port_t mach_task_self(void) { return 42; }
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection) {
    assert(service == 1 && task == 42 && type == UC_TYPE); ++opens; *connection = 7; return is("open-status") ? 5 : 0;
}
kern_return_t IOObjectRelease(io_service_t service) { assert(service == 1); return 0; }
kern_return_t IOServiceClose(io_connect_t connection) {
    assert(connection == 7);
    if (is("hello-abi")) assert(!snapshots && !reads && !writes && !vwrites);
    else assert(bells == 2 && words[1024 + 8] == 2 && !registers[0xa900]);
    ++closes; return is("close-status") ? 5 : 0;
}
static void check_packet(void) {
    assert(bells == 1 || bells == 2);
    assert(words[1024 + 4] == bells * 128 && words[1024 + 5] == 0);
    assert(words[1024 + 16] == 0 && words[1024 + 17] == 0);
    assert(words[1024 + 32] == 0 && words[1024 + 33] == 0 && words[1024 + 34] == 0 && words[1024 + 35] == 0);
    const uint32_t *pkt = words + (bells - 1) * 128;
    if (bells == 1) {
        union MESAPI_SET_HW_RESOURCES r; memcpy(&r, pkt, sizeof(r));
        assert(r.header.opcode == MES_SCH_API_SET_HW_RSRC && r.header.type == MES_API_TYPE_SCHEDULER);
        assert(r.header.dwsize == API_FRAME_SIZE_IN_DWORDS && r.paging_vmid == 0);
        assert(r.g_sch_ctx_gpu_mc_ptr == va + arena + 4096 + 128);
        assert(r.query_status_fence_gpu_mc_ptr == va + arena + 4096 + 136);
        assert(r.api_status.api_completion_fence_addr == va + arena + 4096 + 64);
        assert(r.api_status.api_completion_fence_value == 1);
        assert(r.vmid_mask_gfxhub == 0xffffff00 && r.vmid_mask_mmhub == 0xffffff00);
        for (unsigned i = 0; i < 4; ++i) assert(r.compute_hqd_mask[i] == 0xc);
        assert(r.gfx_hqd_mask[0] == 0xfffffffe && r.sdma_hqd_mask[0] == 0xfc);
    } else {
        union MESAPI__QUERY_MES_STATUS q; memcpy(&q, pkt, sizeof(q));
        assert(q.header.opcode == MES_SCH_API_QUERY_SCHEDULER_STATUS);
        assert(q.api_status.api_completion_fence_addr == va + arena + 4096 + 64);
        assert(q.api_status.api_completion_fence_value == 1);
    }
    union MESAPI__QUERY_MES_STATUS fence; memcpy(&fence, pkt + 64, sizeof(fence));
    assert(fence.header.type == MES_API_TYPE_SCHEDULER && fence.header.opcode == MES_SCH_API_QUERY_SCHEDULER_STATUS);
    assert(fence.api_status.api_completion_fence_addr == va + arena + 4096 + 32);
    assert(fence.api_status.api_completion_fence_value == bells);
    assert(words[2048 + 128] == (uint32_t)(va + arena + 8192));
    assert(words[2048 + 129] == (uint32_t)((va + arena + 8192) >> 32));
    assert(words[2048 + 136] == (uint32_t)((va + arena) >> 8));
    assert(words[2048 + 137] == (uint32_t)((va + arena) >> 40));
    assert(words[2048 + 143] == ((doorbell << 2) | (1u << 30)));
    assert(words[2048 + 165] == (uint32_t)((va + arena + 12288) >> 8));
    assert(words[2048 + 166] == (uint32_t)((va + arena + 12288) >> 40));
    for (unsigned i = 3072; i < 4096; ++i) assert(words[i] == 0);
}
kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count) {
    assert(connection == 7 && input);
    if (selector == SEL_HELLO) {
        assert(input_count == 2 && output && *output_count == 4); ++hellos;
        memset(output, 0, 4 * sizeof(*output)); output[0] = is("hello-abi") ? 2 : 1;
        if (is("hello-short")) --*output_count;
        return is("hello-status") ? 5 : 0;
    }
    if (selector == SEL_DBG_VRAM_WRITE) {
        assert(input_count == 2 && !output && !output_count && reads >= 20);
        assert(!(input[0] & 3) && input[0] >= arena && input[0] + 4 <= arena + 16384 && input[1] <= UINT32_MAX);
        if (vwrites < 4096) assert(input[0] == arena + vwrites * 4 && input[1] == 0);
        ++vwrites;
        if (indexed("vwrite", vwrites)) return 5;
        words[(input[0] - arena) / 4] = (uint32_t)input[1]; return 0;
    }
    if (selector == SEL_DBG_WRITE_REG) {
        assert(input_count == 2 && output && *output_count == 1 && input[0] < 0x20000);
        ++writes;
        if (indexed("write", writes)) return 5;
        if (is("write-short")) --*output_count;
        if (input[0] != 0xa900) assert(registers[0xa900] == 12 && vwrites >= 5694);
        registers[input[0]] = (uint32_t)input[1]; output[0] = input[1]; return 0;
    }
    assert(selector == SEL_DBG_DOORBELL && input_count == 3 && !output && !output_count);
    assert(input[0] == (uint64_t)doorbell * 4 && input[1] == (bells + 1) * 128 && !input[2]);
    ++bells; check_packet();
    if (indexed("bell", bells)) return 5;
    words[1024 + 8] = is("timeout") ? 0 : bells;
    words[1024 + 9] = is("fence-high") ? 1 : 0;
    words[1024 + 16] = is("bad-token") ? 2 : 1;
    words[1024 + 17] = is("token-high") ? 1 : 0;
    return 0;
}
kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7 && !input_data && !input_size && !output && !output_count && output_data && output_size);
    if (selector == PHX_BOOT_MEMORY_SELECTOR) {
        assert(!input_count && !input && *output_size == sizeof(memory)); ++snapshots;
        memcpy(output_data, &memory, sizeof(memory));
        if (is("snapshot-short")) --*output_size;
        return is("snapshot-status") ? 5 : 0;
    }
    assert(input);
    if (selector == SEL_DBG_VRAM_READ) {
        assert(input_count == 2 && input[1] == 2 && *output_size == 8); ++vreads;
        uint64_t value = 0;
        if (vreads <= 7) {
            const uint64_t entry = 0x700000 + (arena >> 12) * 8;
            const uint64_t offsets[] = {0x700000, 0x707ff8, 0x710000, entry, entry + 8, entry + 16, entry + 24};
            const uint64_t values[] = {memory.physicalBase | 0x71, (memory.physicalBase + 0xfff000) | 0x71, 0,
                (memory.physicalBase + arena) | 0x71, (memory.physicalBase + arena + 4096) | 0x71,
                (memory.physicalBase + arena + 8192) | 0x71, (memory.physicalBase + arena + 12288) | 0x71};
            assert(input[0] == offsets[vreads - 1] && !writes && !vwrites);
            value = values[vreads - 1];
            if (indexed("vbad", vreads)) value ^= 1;
        } else {
            assert(bells && input[0] >= arena && input[0] + 8 <= arena + 16384);
            unsigned i = (unsigned)((input[0] - arena) / 4);
            value = words[i] | ((uint64_t)words[i + 1] << 32);
        }
        memcpy(output_data, &value, 8);
        if (is("vread-short")) --*output_size;
        return indexed("vread", vreads) ? 5 : 0;
    }
    assert(selector == SEL_READREGS && input_count == 3 && input[1] == 1 && *output_size == 4 && input[0] < 0x20000);
    ++reads; uint32_t value = registers[input[0]];
    if (indexed("bad", reads)) value ^= 1;
    memcpy(output_data, &value, 4);
    if (is("read-short")) --*output_size;
    return indexed("read", reads) ? 5 : 0;
}
int main(int argc, char **argv) {
    assert(argc == 3); fault = argv[2]; assert(atexit(summary) == 0);
    int relocated = !strcmp(argv[1], "relocated");
    arena = relocated ? 0xa00000 : 0x800000; va = relocated ? 0x400000000000ull : 0x4000000000ull;
    doorbell = relocated ? 0x100 : 0x22;
    memset(words, 0xa5, sizeof(words));
    memory = (struct PhxBootMemory){1, 7, relocated ? 0x234500000000ull : 0x8000000000ull,
        relocated ? 0x123400000000ull : 0x600000000ull, 0x10000000, 0x10000000, 0x100000, 0,
        {1, 0x100000, 0x200000, 0x100000, 0x400000, 0x100000, {0, 0}}};
    if (is("ok")) {
        struct PhxGartLayout gart = {1, va, 0x1000000, 0x700000, 0x710000};
        struct PhxMesQueueLayout q = {1, 0xffc000, 0x3fffffe};
        assert(phxMesQueueLayoutValid(&q, &gart, &memory));
        q.arenaOffset += 4096; assert(!phxMesQueueLayoutValid(&q, &gart, &memory));
        q.arenaOffset = 0x70c000; assert(phxMesQueueLayoutValid(&q, &gart, &memory));
        q.doorbellIndex += 2; assert(!phxMesQueueInputsValid(&q));
        q.doorbellIndex = 2; q.version = 2; assert(!phxMesQueueInputsValid(&q));
        assert(!phxMesQueueInputsValid(NULL));
        q.version = 1; assert(!phxMesQueueLayoutValid(&q, NULL, &memory));
        assert(!phxMesQueueLayoutValid(&q, &gart, NULL));
    }
    if (is("snapshot-faulted")) memory.flags |= 16;
    if (is("snapshot-adopted")) memory.flags |= 8;
    if (is("small-aperture")) memory.apertureBytes = 0x720000;
    registers[0x21a0] = is("cp-busy") ? 1 : 0;
    registers[0xee7e] = is("rlc-not-ready") ? 0 : 0x80000000;
    uint64_t table = memory.physicalBase + 0x700000, dummy = memory.physicalBase + 0x710000, end = va + 0xffffff;
    registers[0x2953] = (uint32_t)(table | 1); registers[0x2954] = (uint32_t)(table >> 32);
    registers[0x2973] = (uint32_t)(va >> 12); registers[0x2974] = (uint32_t)(va >> 44);
    registers[0x2993] = (uint32_t)(end >> 12); registers[0x2994] = (uint32_t)(end >> 44);
    registers[0x28dd] = (uint32_t)(memory.mcBase >> 18); registers[0x28de] = (uint32_t)((memory.mcBase + memory.vramBytes - 1) >> 18);
    registers[0x2808] = registers[0x282b] = (uint32_t)(dummy >> 12);
    registers[0x2809] = registers[0x282c] = (uint32_t)(dummy >> 44);
    registers[0x28e8] = 0x01fffe01;
    registers[0xc807] = is("mes-inactive") ? 0 : is("mes-all-ones") ? UINT32_MAX : 0x0c000000;
    registers[0xa900] = is("selection-busy") ? 12 : 0;
    registers[0x320b] = is("hqd-active") ? 1 : is("hqd-all-ones") ? UINT32_MAX : 0;
    char *args[] = {"mesboot", "sched-query", relocated ? "0x400000000000" : "0x4000000000", "0x1000000",
        "0x700000", "0x710000", relocated ? "0xa00000" : "0x800000", relocated ? "0x100" : "0x22"};
    if (is("arg-unaligned")) args[6] = "0x800001";
    if (is("arg-overflow")) args[6] = "18446744073709551616";
    if (is("arg-wide")) args[6] = "0xfffff000";
    if (is("arg-bell-odd")) args[7] = "3";
    if (is("arg-bell-wide")) args[7] = "0x4000000";
    if (is("arena-table")) args[6] = "0x700000";
    if (is("arena-default")) args[6] = "0x710000";
    if (is("arena-ring")) args[6] = "0x100000";
    if (is("arena-tmr")) args[6] = "0x200000";
    if (is("arena-stage")) args[6] = "0x400000";
    if (is("arena-unmapped")) args[6] = "0xffd000";
    if (is("env-mc")) setenv("MESBOOT_MC", "1", 1);
    if (is("env-adopt")) setenv("ADOPT", "1", 1);
    return mesboot_reference_main(is("arg-count") ? 2 : 8, args);
}
