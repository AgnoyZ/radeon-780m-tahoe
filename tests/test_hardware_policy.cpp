#include "PhxHardwarePolicy.hpp"
#include "PhxComputeProbe.h"
#include "PhxRuntimePath.h"
#include <cassert>
#include <iostream>
#include <vector>

static void aperture_bounds_tests() {
    using phx780m::rangeWithin;
    static_assert(rangeWithin(0, 8, 8), "exact-fit access");
    static_assert(!rangeWithin(UINT64_MAX - 7, 8, 4096), "doorbell end must not wrap");
    static_assert(!rangeWithin(UINT64_MAX - 0x5fff, 0x6000, 0x1400000), "ring extent must not wrap");
    static_assert(!rangeWithin(UINT64_MAX, 1, UINT64_MAX), "end beyond addressable bound");
    assert(rangeWithin(0, 0, 0));
    assert(rangeWithin(4096, 0, 4096));
    assert(!rangeWithin(4097, 0, 4096));
    assert(rangeWithin(4088, 8, 4096));
    assert(!rangeWithin(4089, 8, 4096));
    assert(!rangeWithin(0, UINT64_MAX, 4096));
    assert(rangeWithin(UINT64_MAX - 1, 1, UINT64_MAX));
    // Exhaustively compare small ranges without invoking MMIO or loading a driver.
    for (uint64_t limit = 0; limit <= 32; ++limit)
        for (uint64_t offset = 0; offset <= 40; ++offset)
            for (uint64_t bytes = 0; bytes <= 40; ++bytes)
                assert(rangeWithin(offset, bytes, limit) == (offset <= limit && offset + bytes <= limit));
}

static void runtime_path_tests() {
    char path[128];
    assert(phxRuntimeLibraryPath("/tmp/test bundle/Contents/MacOS/NVMTLDriver", path, sizeof(path)));
    assert(!strcmp(path, "/tmp/test bundle/Contents/MacOS/libvulkan_radeon.dylib"));
    assert(!phxRuntimeLibraryPath("relative/NVMTLDriver", path, sizeof(path)) && !path[0]);
    assert(!phxRuntimeLibraryPath("/directory/", path, sizeof(path)) && !path[0]);
    assert(!phxRuntimeLibraryPath(nullptr, path, sizeof(path)) && !path[0]);
    assert(!phxRuntimeLibraryPath("/image", nullptr, sizeof(path)));
    assert(!phxRuntimeLibraryPath("/image", path, 0));
    const size_t required = strlen("/libvulkan_radeon.dylib") + 1;
    assert(!phxRuntimeLibraryPath("/image", path, required - 1) && !path[0]);
    assert(phxRuntimeLibraryPath("/image", path, required));
    assert(!strcmp(path, "/libvulkan_radeon.dylib"));
}

static void compute_check_tests() {
    assert(phxProbeTarget(0x1002, 0x1900));
    assert(!phxProbeTarget(0x10de, 0x1900));
    assert(!phxProbeTarget(0x1002, 0x15bf));
    assert(!phxProbeTarget(0, 0));
    assert(!phxProbeTarget(0x11002, 0x1900));
    assert(phxProbeExpected(0, 0) == 0x75432777u);
    const uint32_t sizes[] = {1, 63, 64, 257, 4097, 65537};
    for (unsigned pass = 0; pass < 6; ++pass) {
        const uint32_t n = sizes[pass];
        const size_t prefix = pass % 2 ? PHX_PROBE_GUARD_WORDS : 0;
        std::vector<uint32_t> input(n), output(prefix + n + PHX_PROBE_GUARD_WORDS, PHX_PROBE_GUARD_VALUE);
        for (uint32_t i = 0; i < n; ++i) {
            input[i] = phxProbeInput(i, pass);
            output[prefix + i] = ~phxProbeExpected(i, pass);
        }
        auto check = [&] { return phxProbeCheck(input.data(), input.size(), output.data(), output.size(), n, pass, prefix); };
        assert(check().error == PhxProbeResultMismatch); // No GPU writes cannot pass.
        for (uint32_t i = 0; i < n; ++i) output[prefix + i] = phxProbeExpected(i, pass);
        assert(check().error == PhxProbeOK); // Synthetic CPU fixture, not hardware evidence.
        input[0] ^= 1;
        assert(check().error == PhxProbeInputChanged);
        input[0] ^= 1;
        output[prefix + n - 1] ^= 1;
        assert(check().error == PhxProbeResultMismatch);
        assert(check().index == n - 1);
        output[prefix + n - 1] ^= 1;
        output[prefix + n] ^= 1;
        assert(check().error == PhxProbeGuardChanged);
        output[prefix + n] ^= 1;
        if (prefix) {
            output[0] ^= 1;
            assert(check().error == PhxProbeGuardChanged);
            output[0] ^= 1;
        }
        assert(check().error == PhxProbeOK);
        assert(phxProbeCheck(input.data(), n, output.data(), output.size() - 1, n, pass, prefix).error == PhxProbeInvalidSize);
        assert(phxProbeCheck(input.data(), n, output.data(), output.size(), n, pass, SIZE_MAX).error == PhxProbeInvalidSize);
        assert(phxProbeCheck(input.data(), n - 1, output.data(), output.size(), n, pass, prefix).error == PhxProbeInvalidSize);
        assert(phxProbeCheck(nullptr, n, output.data(), output.size(), n, pass, prefix).error == PhxProbeInvalidSize);
        assert(phxProbeCheck(input.data(), n, nullptr, output.size(), n, pass, prefix).error == PhxProbeInvalidSize);
        assert(phxProbeCheck(input.data(), n, output.data(), output.size(), 0, pass, prefix).error == PhxProbeInvalidSize);
    }
}
int main() {
    using namespace phx780m;
    assert(allowDevice(25, 0x1002, 0x1900, true));
    assert(!allowDevice(25, 0x1002, 0x1900, false));
    assert(!allowDevice(23, 0x1002, 0x1900, true));
    assert(!allowDevice(26, 0x1002, 0x1900, true));
    assert(!allowDevice(25, 0x10de, 0x1900, true));
    assert(!allowDevice(25, 0x1002, 0x15bf, true));
    for (int c = 0; c <= 1; ++c) for (int g = 0; g <= 1; ++g) {
        assert(queueIndex(false, c, g) == (c ? 0 : -1));
        assert(queueIndex(true, c, g) == (g ? 1 : -1));
    }
    for (unsigned a = 0; a < 4; ++a) for (unsigned b = 0; b < 4; ++b)
        assert(sameEngine(a, b) == (a <= 1 && a == b));
    assert(!sameEngine(UINT32_MAX, UINT32_MAX));
    compute_check_tests();
    runtime_path_tests();
    aperture_bounds_tests();
    std::cout << "Hardware policy, aperture bounds and compute-check assertions passed (not a GPU execution test).\n";
}
