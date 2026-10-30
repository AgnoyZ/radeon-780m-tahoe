/* Include the actual patched tool; all IOKit calls resolve to this fake transport. */
#define main mesboot_reference_main
#define usleep fake_usleep
#include "mesboot.c"
#undef main
#undef usleep
#include <assert.h>

static const char *fault;
static unsigned calls, releases, closes;
static uint32_t returned_word = 0x12345678u;
static const char *gpu_operation;
static unsigned sleeps, scheduler_bells, work_bells, adoptions, writes_after_failure;
static int gpu_failed;
static uint64_t completion_fence, completion_token;
static uint32_t scratch0, scratch1;
static uint32_t compute_word = 0xFEEDF00D, graphics_word = 0x6F7A6F7A;

int fake_usleep(useconds_t usec) { (void)usec; ++sleeps; return 0; }

static void gpu_summary(void) {
    fprintf(stderr, "fake-gpu-summary {\"scheduler_bells\":%u,\"work_bells\":%u,\"adoptions\":%u,"
                    "\"writes_after_failure\":%u,\"sleeps\":%u}\n",
                    scheduler_bells, work_bells, adoptions, writes_after_failure, sleeps);
}

/* Deliberately injected observations, not emulation or evidence of working GPU packets. */
static void gpu_scalar(uint32_t selector, const uint64_t *input, uint64_t *output) {
    if (gpu_failed) {
        ++writes_after_failure;
        fprintf(stderr, "write attempted after failed synthetic completion\n");
        exit(91);
    }
    if (selector == SEL_DBG_VRAM_WRITE) {
        if (input[0] == TESTBUF) compute_word = (uint32_t)input[1];
        if (input[0] == TESTBUF + 0x40) graphics_word = (uint32_t)input[1];
        if (input[0] == SCH_WB + 32) completion_fence = (uint32_t)input[1];
        if (input[0] == SCH_WB + 64) completion_token = (uint32_t)input[1];
    } else if (selector == SEL_DBG_WRITE_REG) {
        if (input[0] == SEG1(0x2040)) scratch0 = (uint32_t)input[1];
        if (input[0] == SEG1(0x2041)) scratch1 = (uint32_t)input[1];
        *output = input[1];
    } else if (selector == SEL_DBG_ADOPTQ) {
        ++adoptions;
    } else if (selector == SEL_DBG_DOORBELL) {
        if (input[0] == 0x16 * 4) {
            ++scheduler_bells;
            completion_fence = sch_seq;
            completion_token = 1;
            if ((!strcmp(gpu_operation, "mes") || !strcmp(gpu_operation, "sched")) && strcmp(fault, "ok")) {
                if (!strcmp(fault, "timeout")) --completion_fence;
                else if (!strcmp(fault, "zero-token")) completion_token = 0;
                else if (!strcmp(fault, "wrong-token")) completion_token = 2;
                else if (!strcmp(fault, "wrong-fence-high")) completion_fence |= 1ull << 32;
                else if (!strcmp(fault, "wrong-token-high")) completion_token |= 1ull << 32;
                else assert(0);
                gpu_failed = 1;
            }
        } else {
            assert(input[0] == 6 * 4 || input[0] == GFX_DB * 4);
            ++work_bells;
            if (strcmp(fault, "timeout") && strcmp(fault, "wrong-scratch")) {
                if (input[0] == 6 * 4) scratch0 = 0xDEADBEEF;
                else scratch1 = 0xDEADBEEF;
            }
            if (strcmp(fault, "timeout") && strcmp(fault, "wrong-memory")) {
                if (input[0] == 6 * 4) compute_word = 0xFEEDF00D;
                else graphics_word = 0x6F7A6F7A;
            }
            gpu_failed = strcmp(fault, "ok") != 0;
        }
    } else assert(0);
}

static uint32_t gpu_read(uint32_t selector, uint64_t address) {
    if (selector == SEL_READREGS) {
        if (address == SEG1(0x2040)) return scratch0;
        if (address == SEG1(0x2041)) return scratch1;
    } else {
        if (address == SCH_WB + 32) return (uint32_t)completion_fence;
        if (address == SCH_WB + 36) return (uint32_t)(completion_fence >> 32);
        if (address == SCH_WB + 64) return (uint32_t)completion_token;
        if (address == SCH_WB + 68) return (uint32_t)(completion_token >> 32);
        if (address == TESTBUF) return compute_word;
        if (address == TESTBUF + 0x40) return graphics_word;
    }
    return 0;
}

void *IOServiceMatching(const char *name) { assert(!strcmp(name, "PhxBringup")); return (void *)1; }
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching) {
    assert(port == kIOMainPortDefault && matching); return !strcmp(fault, "no-service") ? 0 : 1;
}
mach_port_t mach_task_self(void) { return 42; }
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection) {
    assert(service == 1 && task == 42 && type == UC_TYPE);
    *connection = 7; return !strcmp(fault, "open-failure") ? 5 : KERN_SUCCESS;
}
kern_return_t IOObjectRelease(io_service_t service) { assert(service == 1); ++releases; return 0; }
kern_return_t IOServiceClose(io_connect_t connection) { assert(connection == 7); ++closes; return 0; }

static void called(uint32_t selector) {
    ++calls;
    if (!gpu_operation) fprintf(stderr, "fake-transport call=%u selector=%u\n", calls, selector);
}

kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count) {
    assert(connection == 7 && input);
    called(selector);
    uint32_t expected_in = 0, expected_out = 0;
    switch (selector) {
        case SEL_HELLO: expected_in = 2; expected_out = 4; break;
        case SEL_DBG_WRITE_REG: expected_in = 2; expected_out = 1; break;
        case SEL_DBG_SYSMEM: expected_in = 3; expected_out = 2; break;
        case SEL_DBG_DOORBELL: expected_in = 3; break;
        case SEL_DBG_VRAM_WRITE: expected_in = 2; break;
        case SEL_DBG_ADOPTQ: expected_in = 6; break;
        case 113: expected_in = 1; break;
        default: assert(0);
    }
    assert(input_count == expected_in);
    assert((output_count ? *output_count : 0) == expected_out);
    if (gpu_operation) { gpu_scalar(selector, input, output); return KERN_SUCCESS; }
    if (output_count) {
        assert(output);
        for (uint32_t i = 0; i < *output_count; ++i) output[i] = returned_word + i;
        if (selector == SEL_HELLO) output[0] = !strcmp(fault, "bad-abi") ? 2 : input[0];
        if (!strcmp(fault, "short")) --*output_count;
        if (!strcmp(fault, "long")) ++*output_count;
    }
    return !strcmp(fault, "status") ? 5 : KERN_SUCCESS;
}

kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7 && input && !input_data && !input_size && !output && !output_count);
    assert(selector == SEL_READREGS || selector == SEL_DBG_VRAM_READ);
    assert(input_count == (selector == SEL_READREGS ? 3u : 2u));
    if (selector == SEL_READREGS) assert(input[2] == 0xffffffffu);
    assert(output_data && output_size && *output_size == input[1] * sizeof(uint32_t));
    called(selector);
    uint32_t *words = output_data;
    for (size_t i = 0; i < *output_size / sizeof(uint32_t); ++i)
        words[i] = gpu_operation ? gpu_read(selector, input[0] + i * (selector == SEL_READREGS ? 1u : 4u))
                                 : returned_word + (uint32_t)i;
    if (!strcmp(fault, "short")) --*output_size;
    if (!strcmp(fault, "long")) ++*output_size;
    return !strcmp(fault, "status") ? 5 : KERN_SUCCESS;
}

int main(int argc, char **argv) {
    assert(argc == 3);
    const char *operation = argv[1];
    fault = argv[2];
    conn = 7;
    if (!strcmp(operation, "mes") || !strcmp(operation, "sched") || !strcmp(operation, "compute") || !strcmp(operation, "gfx")) {
        gpu_operation = operation;
        assert(atexit(gpu_summary) == 0);
        assert(setenv("ADOPT", "1", 1) == 0 && setenv("ADOPT_GFX", "1", 1) == 0);
        unsetenv("MESBOOT_CS"); unsetenv("MESBOOT_GFX"); unsetenv("NO_CSB");
        if (!strcmp(operation, "mes")) {
            _Alignas(8) struct { uint32_t pad; union MESAPI__QUERY_MES_STATUS packet; } storage;
            union MESAPI__QUERY_MES_STATUS *packet = &storage.packet;
            assert((uintptr_t)packet % 8 == 4);
            memset(packet, 0, sizeof(*packet));
            packet->header.type = MES_API_TYPE_SCHEDULER;
            packet->header.opcode = MES_SCH_API_QUERY_SCHEDULER_STATUS;
            packet->header.dwsize = API_FRAME_SIZE_IN_DWORDS;
            assert(mes_submit(packet, sizeof(*packet), offsetof(union MESAPI__QUERY_MES_STATUS, api_status), "fixture") == 0);
            assert(packet->api_status.api_completion_fence_addr == VA(SCH_WB + 64));
            assert(packet->api_status.api_completion_fence_value == 1);
        } else if (!strcmp(operation, "sched")) sched_test();
        else if (!strcmp(operation, "compute")) compute_via_mes();
        else gfx_via_mes();
        puts("gpu-returned");
        return 0;
    }
    if (!strcmp(fault, "zero")) returned_word = 0;
    if (!strcmp(operation, "open")) {
        int result = open_kext();
        if (!strcmp(fault, "no-service")) { assert(result == -1 && !calls && !releases); return 1; }
        assert(releases == 1);
        if (!strcmp(fault, "open-failure")) { assert(result == -1 && !calls); return 1; }
        if (!strcmp(fault, "bad-abi")) { assert(result == -1 && closes == 1); return 1; }
        assert(result == 0);
    } else if (!strcmp(operation, "rd")) assert(rd(0x123) == returned_word);
    else if (!strcmp(operation, "vr")) assert(vr(0x1000) == returned_word);
    else if (!strcmp(operation, "vr64")) assert(vr64(0x1000) == (((uint64_t)(returned_word + 1) << 32) | returned_word));
    else if (!strcmp(operation, "wr")) assert(wr(0x123, 4) == returned_word);
    else if (!strcmp(operation, "vw")) vw(0x1000, 4);
    else if (!strcmp(operation, "db")) assert(db(0x60, 0x100000001ull) == 0);
    else if (!strcmp(operation, "sm")) {
        uint64_t a = 0, b = 0; assert(sm(2, 0, 0, &a, &b) == 0);
        assert(a == returned_word && b == (uint64_t)returned_word + 1);
    } else if (!strcmp(operation, "read-then-write")) wr(0x123, rd(0x456));
    else if (!strcmp(operation, "vram-read-then-write")) vw(0x1000, vr(0x2000));
    else if (!strcmp(operation, "write-then-doorbell")) { vw(0x1000, 4); db(0x60, 5); }
    else if (!strcmp(operation, "claim")) {
        uint64_t input[] = {1}; checked_scalar(conn, 113, input, 1, NULL, NULL);
    } else if (!strcmp(operation, "adopt")) {
        uint64_t input[6] = {0}; checked_scalar(conn, SEL_DBG_ADOPTQ, input, 6, NULL, NULL);
    } else assert(0);
    puts("transport-returned");
    return 0;
}
