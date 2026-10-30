// A real Metal compute correctness test; never substitutes the default GPU or a CPU implementation.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <dispatch/dispatch.h>
#import <IOKit/IOKitLib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/utsname.h>
#include "PhxComputeProbe.h"

static int pci_value(io_registry_entry_t entry, CFStringRef key, uint32_t *value) {
    CFTypeRef property = IORegistryEntryCreateCFProperty(entry, key, kCFAllocatorDefault, 0);
    if (!property) return 0;
    int valid = 0;
    if (CFGetTypeID(property) == CFDataGetTypeID()) {
        CFDataRef data = (CFDataRef)property;
        if (CFDataGetLength(data) == 4) {
            const UInt8 *bytes = CFDataGetBytePtr(data);
            *value = (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
            valid = 1;
        }
    } else if (CFGetTypeID(property) == CFNumberGetTypeID()) {
        int64_t number = -1;
        if (CFNumberGetValue((CFNumberRef)property, kCFNumberSInt64Type, &number) && number >= 0 && number <= UINT32_MAX) {
            *value = (uint32_t)number; valid = 1;
        }
    }
    CFRelease(property);
    return valid;
}

static int device_pci(id<MTLDevice> device, uint32_t *vendor, uint32_t *product) {
    if (!device.registryID) return 0;
    CFMutableDictionaryRef matching = IORegistryEntryIDMatching(device.registryID);
    if (!matching) return 0;
    io_registry_entry_t entry = IOServiceGetMatchingService(kIOMainPortDefault, matching);
    for (unsigned depth = 0; entry && depth < 32; ++depth) {
        if (IOObjectConformsTo(entry, "IOPCIDevice")) {
            int found = pci_value(entry, CFSTR("vendor-id"), vendor) && pci_value(entry, CFSTR("device-id"), product);
            IOObjectRelease(entry);
            return found;
        }
        io_registry_entry_t parent = IO_OBJECT_NULL;
        kern_return_t status = IORegistryEntryGetParentEntry(entry, kIOServicePlane, &parent);
        IOObjectRelease(entry);
        entry = status == KERN_SUCCESS ? parent : IO_OBJECT_NULL;
    }
    if (entry) IOObjectRelease(entry);
    return 0;
}

static NSString *const source = @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "kernel void verify(device const uint *in [[buffer(0)]], device uint *out [[buffer(1)]], "
    "constant uint &n [[buffer(2)]], uint i [[thread_position_in_grid]]) { "
    "if (i < n) out[i] = (in[i] * 1664525u + 1013904223u) ^ (i * 2654435761u); }\n";

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 1 && !(argc == 2 && strcmp(argv[1], "--list") == 0)) {
            fprintf(stderr, "usage: metal-smoke [--list]\n"); return 2;
        }
        NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
        id<MTLDevice> chosen = nil;
        for (id<MTLDevice> device in devices) {
            uint32_t vendor = 0, product = 0;
            int known = device_pci(device, &vendor, &product);
            printf("device: %s", device.name.UTF8String);
            if (known) printf(" pci=%04x:%04x", vendor, product);
            else printf(" pci=unverified");
            int target = known && phxProbeTarget(vendor, product);
            printf(" target=%s\n", target ? "yes" : "no");
            if (target) {
                if (chosen) { fprintf(stderr, "Ambiguous 780M devices; refusing to guess\n"); return 3; }
                chosen = device;
            }
        }
        if (argc == 2) return 0;
        if (!chosen) { fprintf(stderr, "FAIL: no PCI-verified 1002:1900 Metal device; no fallback\n"); return 4; }
        struct utsname host;
        if (uname(&host) || strtol(host.release, NULL, 10) != 25) {
            fprintf(stderr, "FAIL: GPU submission requires Darwin 25; no work submitted\n"); return 13;
        }
        NSError *error = nil;
        id<MTLLibrary> library = [chosen newLibraryWithSource:source options:nil error:&error];
        if (!library) { fprintf(stderr, "Shader compile failed: %s\n", error.description.UTF8String); return 5; }
        id<MTLFunction> function = [library newFunctionWithName:@"verify"];
        if (!function) { fprintf(stderr, "Kernel function missing\n"); return 5; }
        id<MTLComputePipelineState> pipeline = [chosen newComputePipelineStateWithFunction:function error:&error];
        id<MTLCommandQueue> queue = [chosen newCommandQueue];
        if (!pipeline || !queue) { fprintf(stderr, "Pipeline/queue unavailable\n"); return 6; }
        const uint32_t sizes[] = {1, 63, 64, 257, 4097, 65537};
        for (unsigned pass = 0; pass < sizeof(sizes) / sizeof(sizes[0]); ++pass) {
            uint32_t n = sizes[pass];
            NSUInteger bytes = (NSUInteger)n * sizeof(uint32_t);
            size_t prefix = pass % 2 ? PHX_PROBE_GUARD_WORDS : 0;
            size_t outputWords = prefix + n + PHX_PROBE_GUARD_WORDS;
            id<MTLBuffer> input = [chosen newBufferWithLength:bytes options:MTLResourceStorageModeShared];
            id<MTLBuffer> output = [chosen newBufferWithLength:outputWords * sizeof(uint32_t) options:MTLResourceStorageModeShared];
            if (!input || !output || !input.contents || !output.contents) return 7;
            uint32_t *in = input.contents, *out = output.contents;
            for (uint32_t i = 0; i < n; ++i) in[i] = phxProbeInput(i, pass);
            for (size_t i = 0; i < outputWords; ++i) out[i] = PHX_PROBE_GUARD_VALUE;
            for (uint32_t i = 0; i < n; ++i) out[prefix + i] = ~phxProbeExpected(i, pass);
            id<MTLCommandBuffer> command = [queue commandBuffer];
            id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
            if (!command || !encoder) return 8;
            [encoder setComputePipelineState:pipeline];
            [encoder setBuffer:input offset:0 atIndex:0];
            [encoder setBuffer:output offset:prefix * sizeof(uint32_t) atIndex:1];
            [encoder setBytes:&n length:sizeof(n) atIndex:2];
            NSUInteger width = MIN((NSUInteger)64, pipeline.maxTotalThreadsPerThreadgroup);
            if (!width) return 9;
            [encoder dispatchThreadgroups:MTLSizeMake((n + width - 1) / width, 1, 1)
                     threadsPerThreadgroup:MTLSizeMake(width, 1, 1)];
            [encoder endEncoding];
            dispatch_semaphore_t done = dispatch_semaphore_create(0);
            [command addCompletedHandler:^(id<MTLCommandBuffer> completed) {
                (void)completed; dispatch_semaphore_signal(done);
            }];
            [command commit];
            if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 30LL * NSEC_PER_SEC))) {
                fprintf(stderr, "FAIL: GPU command timeout (30s); hardware recovery may be required\n"); return 10;
            }
            if (command.status != MTLCommandBufferStatusCompleted) {
                fprintf(stderr, "FAIL: command status=%lu error=%s\n", (unsigned long)command.status,
                        command.error.description.UTF8String); return 11;
            }
            struct PhxProbeCheck check = phxProbeCheck(in, n, out, outputWords, n, pass, prefix);
            if (check.error != PhxProbeOK) {
                fprintf(stderr, "FAIL: n=%u kind=%d index=%zu got=%08x expected=%08x\n",
                        n, check.error, check.index, check.actual, check.expected); return 12;
            }
            printf("PASS: %u uint32 results, unchanged input and guards verified; output offset=%zu\n", n, prefix * sizeof(uint32_t));
        }
        printf("PASS: Metal compute correctness; not a WindowServer, video, power or stability certification\n");
        return 0;
    }
}
