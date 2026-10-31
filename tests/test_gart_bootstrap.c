/* Actual mesboot source; synthetic kernel snapshot, register/memory transport only. */
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
static struct PhxBootMemory observation;
static uint64_t table_off = 0x700000, default_off = 0x710000, virtual_base = 0x4000000000ull;
static uint32_t table_words[1024], default_words[1024], registers[0x20000];
static unsigned lookups, opens, hellos, snapshots, reg_reads, vram_reads, vram_writes, accepted_words, reg_writes, ack_reads, sleeps, closes;
static int is(const char *name) { return !strcmp(fault, name); }
static int indexed(const char *name, unsigned index) {
    char text[40]; snprintf(text, sizeof(text), "%s-%u", name, index); return is(text);
}
static void summary(void) {
    fprintf(stderr, "fake-gart-summary {\"lookups\":%u,\"opens\":%u,\"hellos\":%u,\"snapshots\":%u,"
        "\"reg_reads\":%u,\"vram_reads\":%u,\"vram_writes\":%u,\"accepted_words\":%u,\"reg_writes\":%u,"
        "\"ack_reads\":%u,\"sleeps\":%u,\"closes\":%u}\n", lookups, opens, hellos, snapshots,
        reg_reads, vram_reads, vram_writes, accepted_words, reg_writes, ack_reads, sleeps, closes);
}
static int fake_usleep(useconds_t delay) {
    assert(delay == 1000 && ack_reads && reg_writes == 188); ++sleeps;
    if (is("sleep-error")) { errno = EIO; return -1; }
    if (is("sleep-eintr") && sleeps == 1) { errno = EINTR; return -1; }
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
    assert(connection == 7 && reg_writes == 188 && accepted_words == 2048 && ack_reads);
    const uint64_t table_pa = observation.physicalBase + table_off, dummy_pa = observation.physicalBase + default_off;
    assert(registers[0x2953] == (uint32_t)(table_pa | 1) && registers[0x2954] == (uint32_t)(table_pa >> 32));
    assert(registers[0x2973] == (uint32_t)(virtual_base >> 12) && registers[0x2974] == (uint32_t)(virtual_base >> 44));
    assert(registers[0x2993] == (uint32_t)((virtual_base + 0x4fff) >> 12));
    assert(registers[0x28dd] == (uint32_t)(observation.mcBase >> 18));
    assert(registers[0x28de] == (uint32_t)((observation.mcBase + observation.vramBytes - 1) >> 18));
    assert(registers[0x2808] == (uint32_t)(dummy_pa >> 12) && registers[0x2809] == (uint32_t)(dummy_pa >> 44));
    assert(registers[0x282b] == (uint32_t)(dummy_pa >> 12) && registers[0x282c] == (uint32_t)(dummy_pa >> 44));
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
    if (selector == SEL_DBG_VRAM_WRITE) {
        assert(input_count == 2 && !output && !output_count && reg_reads == 18 && snapshots == 1 && !reg_writes);
        const uint64_t expected_off = vram_writes < 1024 ? table_off + vram_writes * 4 : default_off + (vram_writes - 1024) * 4;
        assert(vram_writes < 2048 && input[0] == expected_off);
        uint32_t expected_value = 0;
        if (vram_writes < 10) {
            uint64_t pte = (observation.physicalBase + (vram_writes / 2) * 4096) | 0x71;
            expected_value = vram_writes & 1 ? (uint32_t)(pte >> 32) : (uint32_t)pte;
        }
        assert(input[1] == expected_value); ++vram_writes;
        if (indexed("vram-write", vram_writes)) return 5;
        if (accepted_words < 1024) table_words[accepted_words] = (uint32_t)input[1];
        else default_words[accepted_words - 1024] = (uint32_t)input[1];
        ++accepted_words; return 0;
    }
    assert(selector == SEL_DBG_WRITE_REG && input_count == 2 && output && *output_count == 1);
    assert(accepted_words == 2048 && vram_reads == 4 && input[0] < 0x20000 && input[1] <= UINT32_MAX);
    ++reg_writes;
    if (indexed("reg-write", reg_writes)) return 5;
    if (is("write-short")) --*output_count;
    if (is("write-long")) ++*output_count;
    registers[input[0]] = (uint32_t)input[1];
    output[0] = input[1];
    return 0;
}

kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7 && !input_data && !input_size && !output && !output_count && output_data && output_size);
    if (selector == PHX_BOOT_MEMORY_SELECTOR) {
        assert(!input && !input_count && *output_size == 128 && !reg_reads && !vram_writes); ++snapshots;
        memcpy(output_data, &observation, sizeof(observation));
        if (is("snapshot-short")) --*output_size;
        if (is("snapshot-long")) ++*output_size;
        return is("snapshot-status") ? 5 : 0;
    }
    if (selector == SEL_DBG_VRAM_READ) {
        assert(input_count == 2 && input[1] == 2 && *output_size == 8 && accepted_words == 2048 && !reg_writes);
        const uint64_t expected_offsets[] = {table_off, table_off + 32, table_off + 40, default_off};
        assert(vram_reads < 4 && input[0] == expected_offsets[vram_reads]); ++vram_reads;
        const uint32_t *words = input[0] == default_off ? default_words : table_words + (input[0] - table_off) / 4;
        memcpy(output_data, words, 8);
        if (indexed("vram-bad", vram_reads)) ((uint32_t *)output_data)[0] ^= 1;
        if (is("vram-read-short")) --*output_size;
        if (is("vram-read-long")) ++*output_size;
        return indexed("vram-read", vram_reads) ? 5 : 0;
    }
    assert(selector == SEL_READREGS && input_count == 3 && input[1] == 1 && input[2] == 0xffffffff && *output_size == 4);
    assert(input[0] < 0x20000); ++reg_reads;
    uint32_t value = registers[input[0]];
    if (input[0] == 0x21a0) value = is("cp-busy") ? 1 : 0;
    if (input[0] == 0xee7e) value = is("rlc-not-ready") ? 0 : is("rlc-all-ones") ? UINT32_MAX : 0x80000000;
    if (!vram_writes && input[0] == 0x28e8 && is("context-zero-active")) value = 1;
    if (!vram_writes && input[0] == 0x28f0 && is("context-eight-active")) value = 1;
    if (reg_writes == 187 && indexed("register-bad", reg_reads)) value ^= 1;
    if (input[0] == 0x292e) {
        assert(reg_writes == 188); ++ack_reads;
        value = is("ack-timeout") || is("sleep-error") ? 0 : is("ack-all-ones") ? UINT32_MAX :
                is("ack-wrong-bit") ? 2 : (is("ack-delayed") || is("sleep-eintr")) && ack_reads < 3 ? 0 : 1;
    }
    memcpy(output_data, &value, 4);
    if (is("read-short")) --*output_size;
    if (is("read-long")) ++*output_size;
    return indexed("reg-read", reg_reads) ? 5 : 0;
}

int main(int argc, char **argv) {
    assert(argc == 2); fault = argv[1]; assert(atexit(summary) == 0);
    memset(table_words, 0xa5, sizeof(table_words)); memset(default_words, 0xa5, sizeof(default_words));
    observation = (struct PhxBootMemory){1, 7, 0x1000000000ull, 0x2000000000ull, 0x1000000, 0x1000000, 0x300000, 0,
        {1, 0x10000, 0x100000, 0x400000, 0x600000, 0x100000, {0, 0}}};
    char *va = "0x4000000000", *bytes = "0x5000", *table = "0x700000", *dummy = "0x710000";
    if (is("relocated")) {
        observation.mcBase = 0x234500000000ull; observation.physicalBase = 0x123400000000ull;
        table_off = 0x900000; default_off = 0x920000; virtual_base = 0x400000000000ull;
        table = "0x900000"; dummy = "0x920000"; va = "0x400000000000";
    }
    if (is("arg-negative")) va = "-1";
    if (is("arg-overflow")) va = "18446744073709551616";
    if (is("arg-junk")) va = "8192x";
    if (is("arg-unaligned")) table = "1";
    if (is("arg-zero")) bytes = "0";
    if (is("arg-map-large")) bytes = "0x8001000";
    if (is("map-outside-vram")) bytes = "0x1100000";
    if (is("arg-va-overflow")) va = "0xfffffffff000";
    if (is("env-pte")) assert(setenv("PTE_SYS", "1", 1) == 0);
    if (is("env-default")) assert(setenv("FAULT_DEFAULT", "1", 1) == 0);
    if (is("env-zero")) { assert(setenv("PTE_SYS", "0", 1) == 0); assert(setenv("FAULT_DEFAULT", "0", 1) == 0); }
    if (is("snapshot-version")) observation.version = 2;
    if (is("snapshot-reserved")) observation.reserved = 1;
    if (is("snapshot-no-tmr")) observation.flags = 3;
    if (is("snapshot-no-ring")) observation.flags = 5;
    if (is("snapshot-gpu")) observation.flags |= 8;
    if (is("snapshot-faulted")) observation.flags |= 16;
    if (is("snapshot-unknown")) observation.flags |= 32;
    if (is("snapshot-zero-tmr")) observation.tmrBytes = 0;
    if (is("snapshot-large-tmr")) observation.tmrBytes = 0x500000;
    if (is("snapshot-wide-tmr")) observation.tmrBytes = 0x100000000ull;
    if (is("snapshot-zero-mc")) observation.mcBase = 0;
    if (is("snapshot-physical-align")) observation.physicalBase += 1;
    if (is("snapshot-physical-width")) observation.physicalBase = 0xfffffff00000ull;
    if (is("snapshot-mc-width")) observation.mcBase = 0xfffffff00000ull;
    if (is("snapshot-aperture-size-granularity")) observation.vramBytes -= 4096;
    if (is("snapshot-aperture-base-granularity")) {
        observation.mcBase += 4096; observation.physicalBase += 4096; observation.psp.tmrOffset -= 4096;
    }
    if (is("snapshot-aperture")) observation.apertureBytes = 0x700000;
    if (is("snapshot-map-size")) observation.vramBytes = 0x4000;
    if (is("table-ring")) table = "0x10000";
    if (is("table-tmr")) table = "0x100000";
    if (is("table-stage")) table = "0x600000";
    if (is("default-ring")) dummy = "0x10000";
    if (is("default-tmr")) dummy = "0x100000";
    if (is("default-stage")) dummy = "0x600000";
    if (is("table-default")) dummy = table;
    if (is("table-outside")) table = "0x1000000";
    if (is("table-wrap")) table = "0xfffffffffffff000";
    if (is("default-outside")) dummy = "0x1000000";
    if (is("virtual-mc-overlap")) va = "0x1000000000";
    if (is("table-offset-wide")) { table = "0x100000000"; observation.vramBytes = observation.apertureBytes = 0x200000000ull; }
    if (is("default-offset-wide")) { dummy = "0x100000000"; observation.vramBytes = observation.apertureBytes = 0x200000000ull; }
    char *args[] = {"mesboot", is("legacy-all") ? "all" : "gart", va, bytes, table, dummy, NULL};
    return mesboot_reference_main(is("arg-count") || is("legacy-all") ? 2 : 6, args);
}
