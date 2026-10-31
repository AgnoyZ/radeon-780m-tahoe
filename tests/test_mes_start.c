/* Actual CLI, synthetic IOKit/registers; no GPU or firmware execution. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef PHX_TEST_ALT
#define phxFirmwareMes auditedFirmwareMes
#include "PhxFirmwareProfile.h"
#undef phxFirmwareMes
static const struct PhxFirmwareMes phxFirmwareMes[2] = {
    {0, 4, 0x123456789abcdef0ull}, {1, 3, 0xfedcba9876543210ull}
};
#endif
static int fake_usleep(useconds_t);
#define usleep fake_usleep
#define main mesboot_reference_main
#include "mesboot.c"
#undef main
#undef usleep

static const char *fault;
static struct PhxBootMemory observation;
static uint32_t registers[0x20000], pc_words[2][2];
static unsigned lookups, opens, hellos, snapshots, reads, vreads, writes, polls, sleeps, closes;
static int is(const char *name) { return !strcmp(fault, name); }
static int indexed(const char *name, unsigned index) {
    char text[40]; snprintf(text, sizeof(text), "%s-%u", name, index); return is(text);
}
static void summary(void) {
    fprintf(stderr, "fake-mes-start-summary {\"lookups\":%u,\"opens\":%u,\"hellos\":%u,\"snapshots\":%u,"
        "\"reads\":%u,\"vreads\":%u,\"writes\":%u,\"polls\":%u,\"sleeps\":%u,\"closes\":%u}\n",
        lookups, opens, hellos, snapshots, reads, vreads, writes, polls, sleeps, closes);
}
static int fake_usleep(useconds_t delay) {
    assert(writes == 9 && delay == (sleeps ? 1000 : 500)); ++sleeps;
    if (is("initial-delay-error") || (is("poll-delay-error") && sleeps == 2)) { errno = EIO; return -1; }
    if (is("delay-interrupted")) { errno = EINTR; return -1; }
    return 0;
}
void *IOServiceMatching(const char *name) { assert(!strcmp(name, "PhxBringup")); return (void *)1; }
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching) {
    assert(port == 0 && matching); ++lookups; return is("no-service") ? 0 : 1;
}
mach_port_t mach_task_self(void) { return 42; }
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection) {
    assert(service == 1 && task == 42 && type == UC_TYPE); ++opens; *connection = 7; return is("open-status") ? 5 : 0;
}
kern_return_t IOObjectRelease(io_service_t service) { assert(service == 1); return 0; }
kern_return_t IOServiceClose(io_connect_t connection) {
    assert(connection == 7);
    if (is("hello-abi")) assert(!snapshots && !reads && !writes);
    else assert(writes == 9 && polls && vreads == 4 && registers[0xa900] == 0);
    ++closes; return is("close-status") ? 5 : 0;
}
kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count) {
    assert(connection == 7 && input);
    if (selector == SEL_HELLO) {
        assert(input_count == 2 && input[0] == 1 && output && *output_count == 4); ++hellos;
        memset(output, 0, 4 * sizeof(*output)); output[0] = is("hello-abi") ? 2 : 1;
        if (is("hello-short")) --*output_count;
        if (is("hello-long")) ++*output_count;
        return is("hello-status") ? 5 : 0;
    }
    assert(selector == SEL_DBG_WRITE_REG && input_count == 2 && output && *output_count == 1);
    assert(snapshots == 1 && reads >= 17 && vreads == 4 && writes < 9);
    const uint64_t a = phxFirmwareMes[0].instruction_start >> 2, b = phxFirmwareMes[1].instruction_start >> 2;
    const uint32_t expected[][2] = {
        {0xc807, 0x40030000}, {0xa900, 12}, {0xc800, (uint32_t)a}, {0xc89d, (uint32_t)(a >> 32)},
        {0xa900, 13}, {0xc800, (uint32_t)b}, {0xc89d, (uint32_t)(b >> 32)}, {0xa900, 0}, {0xc807, 0x0c000000}
    };
    assert(input[0] == expected[writes][0] && input[1] == expected[writes][1]); ++writes;
    if (indexed("write", writes)) return 5;
    if (is("write-short")) --*output_count;
    if (is("write-long")) ++*output_count;
    if (input[0] == 0xc800 || input[0] == 0xc89d) {
        assert(registers[0xa900] == 12 || registers[0xa900] == 13);
        pc_words[registers[0xa900] - 12][input[0] == 0xc89d] = (uint32_t)input[1];
    } else registers[input[0]] = (uint32_t)input[1];
    output[0] = input[1]; return 0;
}
kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7 && !input_data && !input_size && !output && !output_count && output_data && output_size);
    if (selector == PHX_BOOT_MEMORY_SELECTOR) {
        assert(!input && !input_count && *output_size == sizeof(observation)); ++snapshots;
        memcpy(output_data, &observation, sizeof(observation));
        if (is("snapshot-short")) --*output_size;
        if (is("snapshot-long")) ++*output_size;
        return is("snapshot-status") ? 5 : 0;
    }
    assert(input);
    if (selector == SEL_DBG_VRAM_READ) {
        assert(input_count == 2 && input[1] == 2 && *output_size == 8 && !writes && reads == 15);
        const uint64_t offsets[] = {0x700000, 0x700020, 0x700028, 0x710000};
        const uint64_t words[] = {0x600000071ull, 0x600004071ull, 0, 0};
        assert(vreads < 4 && input[0] == offsets[vreads]);
        uint64_t value = words[vreads++];
        if (indexed("vread-bad", vreads)) value ^= 1;
        memcpy(output_data, &value, 8);
        if (is("vread-short")) --*output_size;
        if (is("vread-long")) ++*output_size;
        return indexed("vread", vreads) ? 5 : 0;
    }
    assert(selector == SEL_READREGS && input_count == 3 && input[1] == 1 && *output_size == 4);
    const uint32_t expected[] = {0x21a0, 0xee7e, 0x2953, 0x2954, 0x2973, 0x2974, 0x2993, 0x2994,
        0x28dd, 0x28de, 0x2808, 0x2809, 0x282b, 0x282c, 0x28e8, 0xc807, 0xa900,
        0xa900, 0xc800, 0xc89d, 0xa900, 0xc800, 0xc89d, 0xa900};
    assert(input[0] == (reads < 24 ? expected[reads] : 0xc807)); ++reads;
    uint32_t value = registers[input[0]];
    if (input[0] == 0xc800 || input[0] == 0xc89d) value = pc_words[registers[0xa900] - 12][input[0] == 0xc89d];
    if (reads >= 25) {
        assert(writes == 9 && sleeps); ++polls;
        if (is("poll-all-ones")) value = UINT32_MAX;
        if (is("poll-timeout") || is("poll-wrong-pipe")) value = is("poll-timeout") ? 0 : 0x14000000;
        if (is("poll-reset-stuck")) value |= 0x10000;
        if (is("poll-halted")) value |= 0x40000000;
        if ((is("poll-delayed") || is("delay-interrupted") || is("poll-delay-error")) && polls < 3) value = 0;
    }
    if (indexed("bad", reads)) value ^= 1;
    memcpy(output_data, &value, 4);
    if (is("read-short")) --*output_size;
    if (is("read-long")) ++*output_size;
    return indexed("read", reads) ? 5 : 0;
}
int main(int argc, char **argv) {
    assert(argc == 2); fault = argv[1]; atexit(summary);
    observation.version = PHX_BOOT_MEMORY_VERSION; observation.flags = 7;
    observation.mcBase = 0x8000000000ull; observation.physicalBase = 0x600000000ull;
    observation.vramBytes = observation.apertureBytes = 0x10000000;
    observation.tmrBytes = 0x100000;
    observation.psp = (struct PhxPspLayout){PHX_PSP_LAYOUT_VERSION, 0x100000, 0x200000, 0x100000, 0x400000, 0x100000, {0, 0}};
    if (is("snapshot-faulted")) observation.flags |= PHX_BOOT_PSP_FAULTED;
    if (is("snapshot-adopted")) observation.flags |= PHX_BOOT_GPU_ACTIVE;
    if (is("snapshot-missing-tmr")) observation.flags &= ~PHX_BOOT_TMR_ACTIVE;
    registers[0xee7e] = is("rlc-not-ready") ? 0 : is("rlc-all-ones") ? UINT32_MAX : 0x80000000;
    registers[0x21a0] = is("cp-busy") ? 1 : 0;
    registers[0x2953] = 0x700001; registers[0x2954] = 6;
    registers[0x2973] = 0x04000000; registers[0x2993] = 0x04000004;
    registers[0x28dd] = 0x200000; registers[0x28de] = 0x2003ff;
    registers[0x2808] = registers[0x282b] = 0x600710;
    registers[0x28e8] = 0x01fffe01;
    registers[0xc807] = is("mes-active") ? 0x04000000 : is("mes-all-ones") ? UINT32_MAX : 0x40000000;
    registers[0xa900] = is("selection-busy") ? 12 : 0;
    if (is("env-pte")) setenv("PTE_SYS", "1", 1);
    if (is("env-default")) setenv("FAULT_DEFAULT", "1", 1);
    if (is("env-mc")) setenv("MESBOOT_MC", "1", 1);
    char *args[] = {"mesboot", "mes", "0x4000000000", "0x5000", "0x700000", "0x710000"};
    if (is("arg-invalid")) args[2] = "-1";
    if (is("arg-unaligned")) args[4] = "0x700001";
    if (is("arg-overlap")) args[4] = "0x100000";
    if (is("arg-mapping-mismatch")) args[2] = "0x4000010000";
    return mesboot_reference_main(is("arg-count") ? 2 : 6, args);
}
