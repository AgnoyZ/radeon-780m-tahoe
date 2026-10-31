/* Actual CLI, synthetic inputs and fake IOKit/crypto. Never accesses hardware. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
static int injected_clock_gettime(clockid_t, struct timespec *);
static int injected_nanosleep(const struct timespec *, struct timespec *);
#define clock_gettime injected_clock_gettime
#define nanosleep injected_nanosleep
#define main phxctl_reference_main
#include "phxctl.c"
#undef main
#undef clock_gettime
#undef nanosleep

static const char *fault, *directory;
static unsigned hashes, step, staged, stages, accepted, loads;
static int power_up;
static unsigned smus, clocks, sleeps, cp_reads, rlc_reads;
static unsigned event_count;
static char events[96][24];
static const uint64_t mc = 0x80000000ull, physical = 0x180000000ull;

static int is(const char *name) { return !strcmp(fault, name); }
static int indexed(const char *name, unsigned index) {
    char buffer[40];
    assert(snprintf(buffer, sizeof(buffer), "%s-%u", name, index) > 0);
    return is(buffer);
}
static void event(const char *name, int index) {
    assert(event_count < 96);
    if (index < 0) snprintf(events[event_count], 24, "%s", name);
    else snprintf(events[event_count], 24, "%s-%d", name, index);
    ++event_count;
}
static void summary(void) {
    assert(!staging_snapshot);
    for (unsigned i = 0; i < PHX_FW_FILE_COUNT; ++i) assert(!sequence_images[i]);
    fprintf(stderr, "fake-sequence-summary {\"events\":[");
    for (unsigned i = 0; i < event_count; ++i)
        fprintf(stderr, "%s\"%s\"", i ? "," : "", events[i]);
    fprintf(stderr, "],\"stages\":%u,\"accepted_bytes\":%u", stages, accepted);
    if (power_up)
        fprintf(stderr, ",\"smus\":%u,\"clocks\":%u,\"sleeps\":%u,\"cp_reads\":%u,\"rlc_reads\":%u",
                smus, clocks, sleeps, cp_reads, rlc_reads);
    fprintf(stderr, "}\n");
}

static int slow_poll(void) {
    return is("cp-busy") || is("rlc-not-ready") || is("rlc-wrong-bit") || is("read-all-ones");
}
static int injected_clock_gettime(clockid_t which, struct timespec *value) {
    assert(power_up && smus == 3 && which == CLOCK_MONOTONIC);
    ++clocks;
    if ((is("clock-error") && clocks == 1) || (is("clock-before-error") && clocks == 2) ||
        (is("clock-after-error") && clocks == 3)) { errno = EIO; return -1; }
    uint64_t time_us = 1000000ull + (clocks - 1) * (slow_poll() ? 250000ull : 100ull);
    if (is("clock-frozen")) time_us = 1000000;
    if (is("clock-before-backwards") && clocks == 2) time_us = 999999;
    if (is("clock-after-backwards") && clocks == 3) time_us = 1000099;
    if ((is("clock-before-deadline") && clocks == 2) || (is("clock-after-deadline") && clocks == 3)) time_us = 3000000;
    value->tv_sec = (time_t)(time_us / 1000000);
    value->tv_nsec = (long)((time_us % 1000000) * 1000);
    if (is("clock-bad-nanos")) value->tv_nsec = 1000000000L;
    if (is("clock-negative")) value->tv_sec = -1;
    if (is("clock-overflow")) value->tv_sec = (time_t)(UINT64_MAX / 1000000ull + 1);
    return 0;
}
static int injected_nanosleep(const struct timespec *request, struct timespec *remaining) {
    assert(power_up && request->tv_sec == 0 && request->tv_nsec == 1000000L && !remaining);
    ++sleeps;
    if (is("sleep-error")) { errno = EIO; return -1; }
    if (is("sleep-eintr") && sleeps == 1) { errno = EINTR; return -1; }
    return 0;
}

unsigned char *CC_SHA256(const void *data, CC_LONG length, unsigned char *digest) {
    assert(hashes < PHX_FW_FILE_COUNT);
    const unsigned index = hashes++;
    event("hash", (int)index);
    const unsigned expected = phxFirmwareFiles[index].bytes;
    assert(length == expected || (is("size-mismatch") && index == 4 && length == expected - 4));
    const unsigned char *bytes = data;
    int valid = 1;
    for (unsigned i = 0; i < length; ++i) if (bytes[i] != (index + i) % 251) valid = 0;
    if (indexed("hash-api", index)) return NULL;
    for (unsigned i = 0; i < 32; ++i) {
        char hex[3] = {phxFirmwareFiles[index].sha256[2*i], phxFirmwareFiles[index].sha256[2*i+1], 0};
        digest[i] = (unsigned char)strtoul(hex, NULL, 16);
    }
    if (!valid || indexed("hash", index)) digest[0] ^= 1;
    return digest;
}

void *IOServiceMatching(const char *name) {
    assert(hashes == PHX_FW_FILE_COUNT && !strcmp(name, "PhxBringup"));
    return (void *)1;
}
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching) {
    assert(!port && matching); event("lookup", -1); return is("service-missing") ? 0 : 1;
}
mach_port_t mach_task_self(void) { return 42; }
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection) {
    assert(service == 1 && task == 42 && type == UC_TYPE);
    event("open", -1); *connection = 7; return is("open-status") ? 5 : 0;
}
kern_return_t IOObjectRelease(io_service_t service) { assert(service == 1); return 0; }
kern_return_t IOServiceClose(io_connect_t connection) {
    assert(connection == 7 && step == PHX_FW_STEP_COUNT && loads == 17);
    if (power_up) assert(smus == 3 && cp_reads && rlc_reads);
    event("close", -1); return is("close-status") ? 5 : 0;
}

static kern_return_t reply(const char *operation, uint32_t *count, uint64_t *output) {
    char name[40];
    snprintf(name, sizeof(name), "%s-short", operation);
    if (is(name)) --*count;
    snprintf(name, sizeof(name), "%s-long", operation);
    if (is(name)) ++*count;
    snprintf(name, sizeof(name), "%s-psp", operation);
    if (is(name)) output[0] = 0x100;
    snprintf(name, sizeof(name), "%s-timeout", operation);
    if (is(name)) output[0] = 0xffffffff;
    snprintf(name, sizeof(name), "%s-status", operation);
    return is(name) ? 5 : 0;
}

kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count) {
    assert(connection == 7 && input && output && output_count);
    if (selector == SEL_DBG_SMU) {
        assert(power_up && input_count == 2 && *output_count == 2 && smus < 3);
        const char *operation = smus == 0 ? "smu-if" : smus == 1 ? "smu-version" : "smu-enable";
        assert(input[0] == (smus == 0 ? 3u : smus == 1 ? 2u : 0x16u));
        assert(input[1] == (smus == 2 ? 1u : 0u));
        if (smus < 2) assert(step == 0 && !stages);
        else assert(step == PHX_FW_STEP_COUNT && !strcmp(events[event_count-1], "autoload"));
        event(operation, -1);
        output[0] = 1;
        output[1] = smus == 0 ? 8 : smus == 1 ? 0x13004001 : 0;
        if (is("smu-if-mismatch") && smus == 0) output[1] = 9;
        char fault_name[40];
        snprintf(fault_name, sizeof(fault_name), "%s-wide", operation);
        if (is(fault_name)) output[1] = 1ull << 32;
        ++smus;
        return reply(operation, output_count, output);
    }
    assert(*output_count == 4);
    memset(output, 0, 4 * sizeof(*output));
    if (selector == SEL_HELLO) {
        assert(input_count == 2 && input[0] == 1 && input[1] == 0);
        event("hello", -1); output[0] = is("hello-abi") ? 2 : 1;
        return reply("hello", output_count, output);
    }
    if (selector == SEL_DBG_PSP_RING) {
        assert(input_count == 2 && input[0] == 1 && input[1] == 0x10000);
        event("ring", -1); output[0] = 0x80000000;
        output[1] = is("ring-address") ? 0 : mc + input[1];
        return reply("ring", output_count, output);
    }
    if (selector == PHX_PSP_LOAD_TOC_SELECTOR) {
        assert(step == 0 && input_count == 2 && !input[0] && input[1] == phxFirmwareSteps[0].bytes);
        assert(staged == phxFirmwareSteps[0].bytes);
        event("toc", -1); staged = 0; ++step;
        output[2] = is("toc-zero") ? 0 : is("toc-large") ? 1ull << 32 :
                    is("toc-capacity") ? 0x500000 : 0x300000;
        output[3] = is("toc-no-fit") ? 0 : is("toc-unknown-fit") ? 2 : 1;
        return reply("toc", output_count, output);
    }
    if (selector == SEL_DBG_PSP_LOADIPFW) {
        assert(step > 0 && step < PHX_FW_STEP_COUNT && input_count == 3);
        assert(input[0] == phxFirmwareSteps[step].fw_type && input[1] == 0 && input[2] == phxFirmwareSteps[step].bytes);
        assert(staged == input[2]);
        event("load", (int)step); ++loads;
        if (indexed("load", step)) output[0] = 0x100;
        staged = 0; ++step;
        return reply("load", output_count, output);
    }
    assert(selector == SEL_DBG_PSP_CTL && input_count == 2);
    if (input[0] == 1) {
        assert(step == 1 && !staged && !loads && input[1] == 0x300000);
        event("tmr", -1); return reply("tmr", output_count, output);
    }
    assert(input[0] == 2 && input[1] == 0 && step == PHX_FW_STEP_COUNT && loads == 17);
    event("autoload", -1); return reply("autoload", output_count, output);
}

kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7);
    if (selector == SEL_READREGS) {
        assert(power_up && smus == 3 && step == PHX_FW_STEP_COUNT);
        assert(input_count == 3 && input && input[1] == 1 && input[2] == 0xffffffff);
        assert(!input_data && !input_size && !output && !output_count && output_data && output_size && *output_size == 4);
        const int cp = input[0] == 0x21a0;
        assert(cp || input[0] == 0xee7e);
        if (!cp_reads && cp) event("readiness", -1);
        if (cp) { assert(cp_reads == rlc_reads); ++cp_reads; }
        else { assert(cp_reads == rlc_reads + 1); ++rlc_reads; }
        uint32_t value = cp ? (is("cp-busy") ? 1 : 0) : 0x80000000;
        if (!cp && (is("rlc-not-ready") || is("clock-frozen") || is("sleep-error"))) value = 0;
        if (!cp && (is("ready-delayed") || is("sleep-eintr")) && rlc_reads < 3) value = 0;
        if (!cp && is("rlc-wrong-bit")) value = 1;
        if (is("read-all-ones")) value = 0xffffffff;
        memcpy(output_data, &value, sizeof(value));
        char name[40];
        snprintf(name, sizeof(name), "read-%s-short", cp ? "cp" : "rlc");
        if (is(name)) --*output_size;
        snprintf(name, sizeof(name), "read-%s-long", cp ? "cp" : "rlc");
        if (is(name)) ++*output_size;
        snprintf(name, sizeof(name), "read-%s-status", cp ? "cp" : "rlc");
        return is(name) ? 5 : 0;
    }
    assert(!output_data && !output_size);
    if (selector == PHX_PSP_LAYOUT_SELECTOR) {
        assert(!input && !input_count && input_data && input_size == 64);
        assert(output && output_count && *output_count == 4);
        struct PhxPspLayout layout;
        memcpy(&layout, input_data, sizeof(layout));
        assert(layout.version == 1 && !layout.reserved[0] && !layout.reserved[1]);
        assert(layout.ringOffset == 0x10000 && layout.tmrOffset == 0x100000 && layout.tmrCapacity == 0x400000);
        assert(layout.stagingOffset == 0x600000 && layout.stagingCapacity == 0x100000);
        event("layout", -1);
        output[0] = is("layout-zero") ? 0 : is("tmr-alignment") ? mc + 4096 : mc;
        output[1] = physical;
        output[2] = is("layout-overflow") ? UINT64_MAX : 0x1000000;
        output[3] = is("layout-aperture") ? 0x20000 : 0x1000000;
        return reply("layout", output_count, output);
    }
    assert(selector == SEL_DBG_FW_STAGE && !output && !output_count && input_count == 1 && input);
    assert(step < PHX_FW_STEP_COUNT && input[0] == staged);
    const struct PhxFirmwareStep *s = &phxFirmwareSteps[step];
    assert(input_data && input_size > 0 && input_size <= 4096 && input_size <= s->bytes - staged);
    if (!staged) event("stage", (int)step);
    const unsigned char *bytes = input_data;
    for (unsigned i = 0; i < input_size; ++i)
        assert(bytes[i] == (s->file_index + s->offset + staged + i) % 251);
    ++stages;
    if (indexed("stage", step) || (is("stage-second") && stages == 2)) return 5;
    staged += (unsigned)input_size; accepted += (unsigned)input_size;
    if (is("mutate-files") && stages == 1) {
        for (unsigned i = 0; i < PHX_FW_FILE_COUNT; ++i) {
            char path[4096];
            assert(snprintf(path, sizeof(path), "%s/%s", directory, phxFirmwareFiles[i].name) < (int)sizeof(path));
            int fd = open(path, O_WRONLY | O_TRUNC); assert(fd >= 0);
            assert(write(fd, "x", 1) == 1); assert(close(fd) == 0);
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 3 || argc == 4); fault = argv[1]; directory = argv[2];
    power_up = argc == 4;
    if (power_up) assert(!strcmp(argv[3], "power"));
    assert(atexit(summary) == 0);
    char *ring = "0x10000", *tmr = "0x100000", *capacity = "0x400000", *stage_offset = "0x600000", *stage_capacity = "0x100000";
    if (is("arg-negative")) ring = "-1";
    if (is("arg-overflow")) ring = "18446744073709551616";
    if (is("arg-junk")) ring = "4096x";
    if (is("arg-unaligned")) ring = "0x10001";
    if (is("arg-span")) ring = "0xfffffffffffff000";
    if (is("arg-overlap")) tmr = "0x10000";
    if (is("arg-zero")) capacity = "0";
    if (is("arg-tmr-large")) capacity = "0x100000000";
    if (is("arg-stage-large")) stage_capacity = "0x1001000";
    if (is("arg-stage-small")) stage_capacity = "0x1000";
    if (is("arg-stage-overlap")) stage_offset = "0x100000";
    char *args[] = {"phxctl", power_up ? "gfx-power-sequence" : "firmware-sequence", (char *)directory,
                    ring, tmr, capacity, stage_offset, stage_capacity, NULL};
    return phxctl_reference_main(is("arg-count") ? 7 : 8, args);
}
