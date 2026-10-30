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
Requires an Intel Mac with Xcode Command Line Tools, pinned MacKernelSDK, Vulkan-Headers, Mesa/Cobalt sources, Rust 1.90.0, glslangValidator >= 12.2, pkg-config and the hash-locked translator source archive. This is a build host; it need not contain a 780M. Building on a hosted Mac does not test the target laptop.

```sh
git clone https://github.com/acidanthera/MacKernelSDK.git build-sdk
git -C build-sdk checkout --detach 3f750085caa17ec3a7880f11c11bf4f48cd6a164
git clone --depth 1 --branch v1.4.363 https://github.com/KhronosGroup/Vulkan-Headers.git build-vulkan-headers
python3 tools/translator_source.py build/inputs/nvmtl-translator-source.tar.gz
rustup toolchain install 1.90.0 --profile minimal --target x86_64-apple-darwin
python3 tools/fetch_radv.py build/inputs/radv
python3 -m venv build/radv-venv
. build/radv-venv/bin/activate
python -m pip install -r tools/radv-build-requirements.txt
# Install glslangValidator and pkg-config through your chosen build-host package manager.
python3 tools/build_macos.py --sdk build-sdk --vulkan-headers build-vulkan-headers --translator-source build/inputs/nvmtl-translator-source.tar.gz --mesa build/inputs/radv/mesa --cobalt build/inputs/radv/cobalt --out build/experimental
```

Outputs under build/experimental/artifacts: PhxBringup.kext, PhxAccel.kext, NVMTLDriver.bundle with libnvmtl_translate.dylib, nvmtl/libvulkan_radeon.dylib and its ICD manifest, metal-smoke, provenance and license notices. The build targets x86_64, preserves the upstream kernel ABI/identifiers for integration, applies the downstream gate, signs ad hoc, and checks Mach-O architecture/type. Never load the upstream and downstream variants together. This is not a complete Metal runtime: the AIR bitcode-reader runtime, firmware/bring-up and target-machine runtime integration are still missing. The RADV build path is implemented; consult IMPLEMENTATION-STATUS.md for actual native CI evidence.

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

## RADV source build and negative runtime tests

`tools/prepare_radv.py` verifies clean exact Mesa/Cobalt/nullarc revisions, creates a fresh detached Mesa worktree and applies nine Cobalt, six Phoenix and one downstream patch in order. Upstream patch bytes are read from Git objects (not platform-dependent CRLF checkouts); provenance records their SHA-256 hashes. Existing outputs are never replaced. Git worktree bookkeeping is added to the ignored source cache; original source files are not changed.

The downstream patch removes the mock source from the library, rejects MOCK/HOST_BO device modes, disallows non-Phoenix profiles and restricts the selected IOKit service to PhxBringup. The normal NMXAccel proxy path is preserved. These gates avoid treating host memory or fake fences as GPU acceleration.

Standalone native build, using the same dependencies as the full build:

```sh
python3 tools/build_radv.py --mesa build/inputs/radv/mesa --cobalt build/inputs/radv/cobalt --vulkan-headers build-vulkan-headers --out build/radv-only --artifacts build/radv-artifacts
```

The build checks six shared native-transport structs (every field offset/size), ABI constants and core selectors against both real pinned headers. This is not a complete ABI/semantics audit; scanout, proxy behavior and hardware execution remain untested. Mesa uses its upstream Darwin weak-entrypoint `dynamic_lookup` linker recipe; the produced dylib must also pass a real `dlopen(RTLD_NOW)` and Vulkan instance/enumeration test, so linker output alone is insufficient.

The no-device probe first checks that all four relevant IOKit services are absent, and refuses to run otherwise. It never creates a VkDevice or submits GPU commands. Four fresh processes test native empty enumeration and explicit rejection of mock, host-only and non-Phoenix modes. A timeout, target-service detection, missing exports, loader error, unexpected diagnostics or any enumerated device fails CI. Python mocks only test the runner logic and are not runtime-driver evidence.

Mesa license texts and Cobalt notices accompany local build output. Mesa includes per-file licenses; root MIT wording is not a complete provenance clearance. glslang/pkg-config are build-host packages rather than pinned source inputs; their/tool versions and dylib dependencies are recorded where applicable. No public binaries are uploaded. The staged nvmtl directory mirrors the plugin's expected runtime filenames but is not installed anywhere.
