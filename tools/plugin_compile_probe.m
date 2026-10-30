// Exercise the real plugin's library compiler without creating a Metal/Vulkan device.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef NSDictionary *(*IndexFn)(NSData *, NSDictionary *__autoreleasing *, NSDictionary *__autoreleasing *);
typedef NSData *(*CompileFn)(NSData *, NSString *, NSString *, NSString *, NSString *__autoreleasing *);
typedef void (*CountsFn)(uint64_t *, uint64_t *, uint64_t *);
typedef int (*InitializeFn)(void);

static BOOL same_image(const void *symbol, NSString *expected) {
    Dl_info info;
    if (!symbol || !dladdr(symbol, &info) || !info.dli_fname) return NO;
    NSString *actual = [@(info.dli_fname) stringByResolvingSymlinksInPath];
    return [actual isEqualToString:[expected stringByResolvingSymlinksInPath]];
}

static BOOL already_loaded(NSString *path, const char *symbol) {
    void *handle = dlopen(path.fileSystemRepresentation, RTLD_NOLOAD | RTLD_NOW | RTLD_LOCAL);
    if (!handle) return NO;
    BOOL correct = same_image(dlsym(handle, symbol), path);
    dlclose(handle);
    return correct;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 4) {
            fprintf(stderr, "usage: plugin-compile-probe /plugin/executable /input.metallib /fresh-output-directory\n");
            return 2;
        }
        NSString *executable = @(argv[1]), *input = @(argv[2]), *out = @(argv[3]);
        if (!executable.isAbsolutePath || !input.isAbsolutePath || !out.isAbsolutePath) return 2;
        NSFileManager *files = [NSFileManager defaultManager];
        if ([files fileExistsAtPath:@"/Library/GPUBundles/nvmtl"] || objc_getClass("NVMTLDevice")) {
            fprintf(stderr, "Refusing contaminated host: installed runtime or plugin already present\n"); return 3;
        }
        const char *services[] = {"PhxBringup", "NMXAccel", "Navi48Bringup", "Navi48Accelerator"};
        for (unsigned i = 0; i < sizeof(services) / sizeof(services[0]); ++i) {
            io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching(services[i]));
            if (service) {
                IOObjectRelease(service);
                fprintf(stderr, "Refusing compiler-only test: target service present\n"); return 77;
            }
        }
        NSData *container = [NSData dataWithContentsOfFile:input];
        if (!container || container.length > 16u * 1024u * 1024u) return 4;
        void *plugin = dlopen(executable.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
        if (!plugin) { fprintf(stderr, "Plugin load failed: %s\n", dlerror()); return 5; }
        IndexFn index = (IndexFn)dlsym(plugin, "nvmtl_translate_metallib");
        CompileFn compile = (CompileFn)dlsym(plugin, "nvmtl_compile_library_entry");
        CountsFn counts = (CountsFn)dlsym(plugin, "nvmtl_vk_cmd_counts");
        InitializeFn initialize = (InitializeFn)dlsym(plugin, "nvmtl_vk_init");
        Class device = objc_getClass("NVMTLDevice");
        const char *classImage = device ? class_getImageName(device) : NULL;
        if (!same_image((const void *)index, executable) || !same_image((const void *)compile, executable) ||
            !same_image((const void *)counts, executable) || !same_image((const void *)initialize, executable) || !classImage ||
            ![[@(classImage) stringByResolvingSymlinksInPath] isEqualToString:[executable stringByResolvingSymlinksInPath]]) return 6;

        // Release-mode constructors clear NVMTL_*; set isolated caches only after dlopen.
        for (NSString *name in @[@"aircache", @"spvcache", @"mesacache"]) {
            NSString *directory = [out stringByAppendingPathComponent:name];
            if ([files fileExistsAtPath:directory] ||
                ![files createDirectoryAtPath:directory withIntermediateDirectories:NO attributes:nil error:NULL]) return 7;
            if ([name isEqualToString:@"aircache"] && setenv("NVMTL_AIRCACHE", directory.fileSystemRepresentation, 1)) return 7;
            if ([name isEqualToString:@"mesacache"] && setenv("MESA_SHADER_CACHE_DIR", directory.fileSystemRepresentation, 1)) return 7;
        }
        if (setenv("NVMTL_IDXCACHE_OFF", "1", 1) || setenv("NVMTL_SPVCACHE_OFF", "1", 1) ||
            setenv("NVMTL_SPVCACHE_KEEP_STALE", "1", 1)) return 7;
        NSDictionary *stages = nil, *airs = nil;
        NSDictionary *entries = index(container, &stages, &airs);
        if (entries.count != 1 || ![entries[@"increment"] isKindOfClass:NSData.class] ||
            ![stages[@"increment"] isEqualToString:@"kernel"] ||
            ![airs[@"increment"] isKindOfClass:NSString.class]) {
            fprintf(stderr, "Plugin library index failed\n"); return 20;
        }
        NSString *diagnostic = nil;
        NSData *spirv = compile(entries[@"increment"], airs[@"increment"], stages[@"increment"], @"increment", &diagnostic);
        if (spirv.length < 20 || spirv.length > 16u * 1024u * 1024u) {
            fprintf(stderr, "Plugin compilation failed: %s\n", diagnostic.UTF8String ?: "no SPIR-V"); return 21;
        }
        NSString *directory = executable.stringByDeletingLastPathComponent;
        if (!already_loaded([directory stringByAppendingPathComponent:@"libnvmtl_translate.dylib"], "nvmtl_translate") ||
            !already_loaded([directory stringByAppendingPathComponent:@"air-runtime/libLLVM.dylib"], "LLVMParseBitcodeInContext2")) {
            fprintf(stderr, "Plugin did not load its own translator/LLVM runtime\n"); return 22;
        }
        // This host has no target service. Exercise real plugin ICD loading, not GPU work.
        NSString *ignored = [out stringByAppendingPathComponent:@"ignored-external-driver"];
        if (setenv("NVMTL_ICD_LIB", ignored.fileSystemRepresentation, 1) ||
            setenv("VK_ICD_FILENAMES", ignored.fileSystemRepresentation, 1)) return 7;
        if (initialize() == 0) { fprintf(stderr, "Unexpected plugin device initialization on a no-device host\n"); return 26; }
        if (!already_loaded([directory stringByAppendingPathComponent:@"libvulkan_radeon.dylib"], "vk_icdGetInstanceProcAddr")) {
            fprintf(stderr, "Plugin RADV runtime missing\n"); return 25;
        }
        uint64_t begun = 0, submitted = 0, abandoned = 0;
        counts(&begun, &submitted, &abandoned);
        if (begun || submitted || abandoned) { fprintf(stderr, "Unexpected GPU command activity\n"); return 23; }
        NSString *path = [out stringByAppendingPathComponent:@"compiled.spv"];
        if ([files fileExistsAtPath:path] || ![spirv writeToFile:path options:NSDataWritingWithoutOverwriting error:NULL]) return 24;
        puts("{\"plugin_loaded\":true,\"plugin_compiler_executed\":true,\"bundled_runtimes_loaded\":true,\"bundled_radv_loaded\":true,\"no_device_init_rejected\":true,\"gpu_commands_begun\":0,\"gpu_commands_submitted\":0,\"gpu_commands_abandoned\":0}");
        // Objective-C classes and registered image callbacks live until this process exits.
        return 0;
    }
}
