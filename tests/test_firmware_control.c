/* Actual CLI source; explicit fake IOKit/crypto and injected POSIX read failures. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static ssize_t injected_read(int, void *, size_t);
#define read injected_read
#define main phxctl_reference_main
#include "phxctl.c"
#undef main
#undef read
#include <assert.h>

static const char *fault, *path, *reference_hash;
static unsigned hellos, stages, accepted_bytes, loads, opens, hashes, reads, smus, reg_reads, layouts;

static void summary(void) {
    fprintf(stderr, "fake-control-summary {\"hellos\":%u,\"stages\":%u,\"accepted_bytes\":%u,"
                    "\"loads\":%u,\"opens\":%u,\"hashes\":%u,\"reads\":%u,\"smus\":%u,\"reg_reads\":%u,\"layouts\":%u}\n",
            hellos, stages, accepted_bytes, loads, opens, hashes, reads, smus, reg_reads, layouts);
}

static ssize_t injected_read(int fd, void *buffer, size_t length) {
    ++reads;
    if (!strcmp(fault, "read-eintr") && reads == 1) { errno = EINTR; return -1; }
    if (!strcmp(fault, "read-error") && reads == 2) { errno = EIO; return -1; }
    if (!strcmp(fault, "read-short") && reads == 2) return 0;
    return read(fd, buffer, length > 4096 ? 4096 : length);
}

unsigned char *CC_SHA256(const void *bytes, CC_LONG length, unsigned char *digest) {
    ++hashes;
    assert(length == 8221);
    const unsigned char *input = bytes;
    for (unsigned i = 0; i < length; ++i) assert(input[i] == i % 251);
    if (!strcmp(fault, "hash-api")) return NULL;
    for (unsigned i = 0; i < 32; ++i) {
        char hex[3] = {reference_hash[2*i], reference_hash[2*i+1], 0};
        digest[i] = (unsigned char)strtoul(hex, NULL, 16);
    }
    return digest;
}

void *IOServiceMatching(const char *name) { assert(!strcmp(name, "PhxBringup")); return (void *)1; }
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching) { assert(!port && matching); return 1; }
mach_port_t mach_task_self(void) { return 42; }
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection) {
    assert(service == 1 && task == 42 && type == UC_TYPE); ++opens; *connection = 7; return 0;
}
kern_return_t IOObjectRelease(io_service_t service) { assert(service == 1); return 0; }
kern_return_t IOServiceClose(io_connect_t connection) { assert(connection == 7); return 0; }

kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count) {
    assert(connection == 7 && input && output && output_count);
    if (selector == SEL_HELLO) {
        assert(input_count == 2 && *output_count == 4); ++hellos;
        memset(output, 0, 4 * sizeof(*output)); output[0] = !strcmp(fault, "hello-abi") ? 2 : 1;
        if (!strcmp(fault, "hello-short")) --*output_count;
        if (!strcmp(fault, "hello-long")) ++*output_count;
        return !strcmp(fault, "hello-status") ? 5 : 0;
    }
    if (selector == SEL_DBG_SMU) {
        assert(input_count == 2 && *output_count == 2); ++smus;
        output[0] = !strcmp(fault, "smu-status") ? 0 : 1; output[1] = 0;
        return !strcmp(fault, "smu-transport") ? 5 : 0;
    }
    assert(selector == SEL_DBG_PSP_LOADIPFW);
    assert(input_count == 3 && *output_count == 4 && accepted_bytes == 8209);
    assert(input[0] == 4 && input[1] == 4096 && input[2] == 8209); ++loads;
    memset(output, 0, 4 * sizeof(*output));
    if (!strcmp(fault, "psp-status")) output[0] = 0x100;
    if (!strcmp(fault, "psp-timeout")) output[0] = 0xFFFFFFFF;
    if (!strcmp(fault, "load-short")) --*output_count;
    if (!strcmp(fault, "load-long")) ++*output_count;
    return !strcmp(fault, "load-status") ? 5 : 0;
}

kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size) {
    assert(connection == 7);
    if (selector == PHX_PSP_LAYOUT_SELECTOR) {
        assert(!input && !input_count && input_data && input_size == 64);
        assert(output && output_count && *output_count == 4 && !output_data && !output_size);
        struct PhxPspLayout layout;
        memcpy(&layout, input_data, sizeof(layout));
        assert(layout.version == 1 && !layout.reserved[0] && !layout.reserved[1]);
        assert(layout.ringOffset == 0x1000 && layout.tmrOffset == 0xA000 && layout.tmrCapacity == 0x2000);
        assert(layout.stagingOffset == 0xD000 && layout.stagingCapacity == 0x2000);
        assert(!stages && !loads); ++layouts;
        memset(output, 0, 4 * sizeof(*output));
        if (!strcmp(fault, "layout-short")) --*output_count;
        if (!strcmp(fault, "layout-long")) ++*output_count;
        return !strcmp(fault, "layout-status") ? 5 : 0;
    }
    assert(!output && !output_count);
    if (selector == SEL_READREGS) {
        assert(input_count == 3 && !input_data && !input_size && output_data && *output_size == 4);
        ++reg_reads; *(uint32_t *)output_data = 0;
        if (!strcmp(fault, "reg-short")) --*output_size;
        if (!strcmp(fault, "reg-long")) ++*output_size;
        return !strcmp(fault, "reg-status") ? 5 : 0;
    }
    assert(selector == SEL_DBG_FW_STAGE && input_count == 1 && input_data && !output_data && !output_size);
    assert(hashes == 1 && input[0] == 4096 + accepted_bytes && input_size <= 4096 && input_size > 0);
    const unsigned char *bytes = input_data;
    for (unsigned i = 0; i < input_size; ++i) assert(bytes[i] == (4 + accepted_bytes + i) % 251);
    ++stages;
    if ((!strcmp(fault, "stage-first") && stages == 1) || (!strcmp(fault, "stage-second") && stages == 2)) return 5;
    accepted_bytes += (unsigned)input_size;
    if (!strcmp(fault, "mutate-file") && stages == 1) {
        int fd = open(path, O_WRONLY | O_TRUNC); assert(fd >= 0);
        assert(write(fd, "x", 1) == 1); assert(close(fd) == 0);
    }
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 5);
    const char *mode = argv[1]; fault = argv[2]; path = argv[3]; reference_hash = argv[4];
    assert(atexit(summary) == 0);
    char *hash = (char *)reference_hash;
    if (!strcmp(fault, "hash-mismatch")) hash = "0000000000000000000000000000000000000000000000000000000000000000";
    if (!strcmp(fault, "hash-format")) hash = "invalid";
    char *offset = "4", *size = "8209", *destination = "4096";
    if (!strcmp(fault, "arg-negative")) size = "-1";
    if (!strcmp(fault, "arg-overflow")) size = "4294967296";
    if (!strcmp(fault, "arg-junk")) size = "8209x";
    if (!strcmp(fault, "zero-size")) size = "0";
    if (!strcmp(fault, "slice-overflow")) offset = "4294967295";
    if (!strcmp(fault, "destination-overflow")) destination = "16777212";
    if (!strcmp(fault, "destination-alignment")) destination = "4097";
    if (!strcmp(mode, "layout")) {
        char *ring = !strcmp(fault, "arg-overflow") ? "18446744073709551616" :
                     !strcmp(fault, "arg-negative") ? "-1" : "0x1000";
        char *args[] = {"phxctl", "psp-layout", ring, "0xA000", "8192", "0xD000", "8192", NULL};
        return phxctl_reference_main(!strcmp(fault, "missing-layout") ? 6 : 7, args);
    }
    if (!strcmp(mode, "verify")) {
        char *args[] = {"phxctl", "verify-file", (char *)path, hash, NULL};
        return phxctl_reference_main(4, args);
    }
    if (!strcmp(mode, "smu")) {
        char *args[] = {"phxctl", "smuinfo", NULL}; return phxctl_reference_main(2, args);
    }
    if (!strcmp(mode, "reg")) {
        char *args[] = {"phxctl", "regs", "0x123", "0x124", NULL}; return phxctl_reference_main(4, args);
    }
    if (!strcmp(mode, "stage")) {
        char *args[] = {"phxctl", "stage", (char *)path, offset, size, destination, hash, NULL};
        return phxctl_reference_main(7, args);
    }
    assert(!strcmp(mode, "load"));
    char *args[] = {"phxctl", "loadfw", (char *)path, offset, size, "4", destination, hash, NULL};
    return phxctl_reference_main(!strcmp(fault, "missing-hash") ? 7 : 8, args);
}
