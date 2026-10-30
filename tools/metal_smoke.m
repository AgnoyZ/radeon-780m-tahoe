// A real Metal compute correctness test; never substitutes the default GPU or a CPU implementation.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <dispatch/dispatch.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

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
            printf("device: %s\n", device.name.UTF8String);
            if ([device.name rangeOfString:@"780M" options:NSCaseInsensitiveSearch].location != NSNotFound) {
                if (chosen) { fprintf(stderr, "Ambiguous 780M devices; refusing to guess\n"); return 3; }
                chosen = device;
            }
        }
        if (argc == 2) return 0;
        if (!chosen) { fprintf(stderr, "FAIL: no Radeon 780M Metal device; no fallback\n"); return 4; }
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
            id<MTLBuffer> input = [chosen newBufferWithLength:bytes options:MTLResourceStorageModeShared];
            id<MTLBuffer> output = [chosen newBufferWithLength:bytes options:MTLResourceStorageModeShared];
            if (!input || !output || !input.contents || !output.contents) return 7;
            uint32_t *in = input.contents, *out = output.contents;
            for (uint32_t i = 0; i < n; ++i) { in[i] = i ^ (0x12345678u + pass); out[i] = 0xdeadbeefu; }
            id<MTLCommandBuffer> command = [queue commandBuffer];
            id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
            if (!command || !encoder) return 8;
            [encoder setComputePipelineState:pipeline];
            [encoder setBuffer:input offset:0 atIndex:0];
            [encoder setBuffer:output offset:0 atIndex:1];
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
            for (uint32_t i = 0; i < n; ++i) {
                uint32_t expected = (in[i] * 1664525u + 1013904223u) ^ (i * 2654435761u);
                if (out[i] != expected) {
                    fprintf(stderr, "FAIL: n=%u index=%u got=%08x expected=%08x\n", n, i, out[i], expected); return 12;
                }
            }
            printf("PASS: %u uint32 results verified\n", n);
        }
        printf("PASS: Metal compute correctness; not a WindowServer, video, power or stability certification\n");
        return 0;
    }
}
