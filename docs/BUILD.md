# Source build and tests

## Windows / Linux / macOS: source preparation tests
Requires Python 3.10+ and Git. No driver is loaded.

```sh
git submodule update --init
python tools/prepare_source.py build/review-source
python -m unittest discover -s tests -v
```

The output directory must not exist. Use a fresh directory for another preparation; the tool never recursively deletes a previous build. The nullarc submodule must match upstream.lock.json exactly and be clean. Source is exported from the pinned Git objects, not copied from an arbitrary worktree.

With clang++ installed:

```sh
mkdir -p build
clang++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -Isrc tests/test_hardware_policy.cpp -o build/test-policy
build/test-policy
```

## Native macOS: actual kernel binaries
Requires Xcode Command Line Tools, pinned MacKernelSDK, pinned Vulkan-Headers, Rust 1.90.0 and the hash-locked translator source archive. This is a build host; it need not contain a 780M. Building on a hosted Mac does not test the target laptop.

```sh
git clone https://github.com/acidanthera/MacKernelSDK.git build-sdk
git -C build-sdk checkout --detach 3f750085caa17ec3a7880f11c11bf4f48cd6a164
git clone --depth 1 --branch v1.4.363 https://github.com/KhronosGroup/Vulkan-Headers.git build-vulkan-headers
python3 tools/translator_source.py build/inputs/nvmtl-translator-source.tar.gz
rustup toolchain install 1.90.0 --profile minimal --target x86_64-apple-darwin
python3 tools/build_macos.py --sdk build-sdk --vulkan-headers build-vulkan-headers --translator-source build/inputs/nvmtl-translator-source.tar.gz --out build/experimental
```

Outputs under build/experimental/artifacts: PhxBringup.kext, PhxAccel.kext, NVMTLDriver.bundle with libnvmtl_translate.dylib, metal-smoke, provenance and license notices. The build targets x86_64, preserves the upstream kernel ABI/identifiers for integration, applies the downstream gate, signs ad hoc, and checks Mach-O architecture/type. Never load the upstream and downstream variants together. This is not a complete Metal runtime: RADV, the AIR bitcode-reader runtime and firmware/bring-up are still missing.

The Metal plugin is compiled from the pinned `src/nmplugin/NVMTLDevice.m` translation unit (which includes the other plugin sources), not copied from an installed system or a release archive. It uses the upstream release-mode ARC/bundle recipe and normal linker symbol resolution; undefined-symbol escape flags and mock device stubs are not used. Its exported NVMTLDevice class/metaclass and x86_64 MH_BUNDLE structure are checked. The project-authored bundle metadata matches the kernel's plugin name/class, declares Tahoe as its supported deployment target, and has a distinct downstream bundle identifier. Runtime plugin discovery/loading remains untested.

Vulkan-Headers is verified against commit `6802bb4733b63ed5efd3adb308a6c885ef180ea1`, not merely a movable tag. Headers are not a Vulkan loader or a RADV implementation. Their license notices accompany the build output.

## Real AIR translator build and host tests

The translator is built from the LGPL source attached to nullarc v0.3.0-alpha, SHA-256 `1252d982578b19e18144266aab994bb354a757c7491dcb33c15518b6791c3f3c`. The fetcher verifies bytes before extraction and will not replace a different existing cache. The build uses the unmodified source and its Cargo.lock with `cargo +1.90.0 build --locked`, checks every translator symbol requested by the pinned plugin, and bundles the dylib next to the plugin executable. The source archive, original NOTICE, LGPL and GPL text accompany local artifacts; they are not automatically published.

To exercise the actual C ABI without a GPU, install SPIRV-Tools on the build host and run:

```sh
python3 tools/test_translator_runtime.py --library build/experimental/artifacts/NVMTLDriver.bundle/Contents/MacOS/libnvmtl_translate.dylib --plugin-source build/experimental/stage/src/nmplugin/NVMTLLibraryLoad.m --fixture tests/fixtures/compute_increment.ll --validator spirv-val --out build/experimental/translator-tests
```

This loads the real dylib, resolves all 16 dynamic symbols (not a behavioral test of every export), requires malformed input/invalid stages to fail, translates two different AIR arithmetic kernels, checks their compute/store/add instructions, and runs `spirv-val --target-env vulkan1.2`. Test output records the validator version. Successful validation is not GPU execution or Metal pipeline integration; the test explicitly reports hardware_executed=false.

The deployment minimum compiler setting follows upstream for kext SDK compatibility; the runtime gate permits Darwin 25 only. macOS 15 Intel CI is only a compilation host, not a Tahoe runtime validation.

## Tests are deliberately separated
- Python: exact patch application, no fake completion branches, opt-in order, source provenance, malformed Mach-O rejection.
- C++: execute the same device/queue policy included in the patched drivers, including wrong-engine and unavailable-queue cases.
- macOS build: actually compile/link two kexts, the Metal plugin and a Metal compute probe; verify structure, plugin exports and signing.
- Target hardware: NOT performed by CI. The Metal probe refuses another/default GPU, checks every output for six problem sizes, and times out waiting for a command.

See EXPERIMENTAL.md before considering any hardware test. This repository does not yet provide a complete Metal runtime or an installation package.

## CI retention limitation
The first native build succeeded but GitHub rejected artifact upload because Actions storage was full. Default push runs now compile, sign, inspect and test without retaining binaries; they do not claim to deliver a downloadable package. Build reports and hashes are printed in the job log. When storage is available, manually dispatch with retain_artifacts=true to retain the experimental outputs for seven days. Requested upload failures are not suppressed. No account data is deleted or billing changed automatically.

## Public repository policy (2026-10-30)
The owner authorized public source visibility. Public runs remain compile/test-only. Requesting binary artifact retention on a public repository fails explicitly until the outstanding upstream license/provenance audit and publication approval are resolved. Existing run 41056667927 passed both source-tests and macos-kexts (including the no-device refusal test); it retained no binary artifacts.
