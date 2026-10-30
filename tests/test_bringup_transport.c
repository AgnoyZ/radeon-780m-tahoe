/* Include the actual patched tool; all IOKit calls resolve to this fake transport. */
#define main mesboot_reference_main
#include "mesboot.c"
#undef main
#include <assert.h>

static const char *fault;
static unsigned calls, releases, closes;
static uint32_t returned_word = 0x12345678u;

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
    fprintf(stderr, "fake-transport call=%u selector=%u\n", calls, selector);
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
    for (size_t i = 0; i < *output_size / sizeof(uint32_t); ++i) words[i] = returned_word + (uint32_t)i;
    if (!strcmp(fault, "short")) --*output_size;
    if (!strcmp(fault, "long")) ++*output_size;
    return !strcmp(fault, "status") ? 5 : KERN_SUCCESS;
}

int main(int argc, char **argv) {
    assert(argc == 3);
    const char *operation = argv[1];
    fault = argv[2];
    conn = 7;
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
