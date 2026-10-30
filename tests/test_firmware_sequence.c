/* Actual CLI, synthetic inputs and fake IOKit/crypto. Never accesses hardware. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define main phxctl_reference_main
#include "phxctl.c"
#undef main

static const char *fault, *directory;
static unsigned hashes, step, staged, stages, accepted, loads;
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
    fprintf(stderr, "],\"stages\":%u,\"accepted_bytes\":%u}\n", stages, accepted);
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
    assert(connection == 7 && input && output && output_count && *output_count == 4);
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
    assert(connection == 7 && !output_data && !output_size);
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
    assert(argc == 3); fault = argv[1]; directory = argv[2];
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
    char *args[] = {"phxctl", "firmware-sequence", (char *)directory, ring, tmr, capacity, stage_offset, stage_capacity, NULL};
    return phxctl_reference_main(is("arg-count") ? 7 : 8, args);
}
