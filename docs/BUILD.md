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
Requires an Intel Mac with Xcode Command Line Tools, pinned MacKernelSDK, Vulkan-Headers, Mesa/Cobalt and LLVM 21.1.8 sources, CMake, Rust 1.90.0, glslangValidator >= 12.2, pkg-config and the hash-locked translator source archive. This is a build host; it need not contain a 780M. Building on a hosted Mac does not test the target laptop.

```sh
git clone https://github.com/acidanthera/MacKernelSDK.git build-sdk
git -C build-sdk checkout --detach 3f750085caa17ec3a7880f11c11bf4f48cd6a164
git clone --depth 1 --branch v1.4.363 https://github.com/KhronosGroup/Vulkan-Headers.git build-vulkan-headers
python3 tools/translator_source.py build/inputs/nvmtl-translator-source.tar.gz
rustup toolchain install 1.90.0 --profile minimal --target x86_64-apple-darwin
python3 tools/fetch_radv.py build/inputs/radv
python3 tools/fetch_air_runtime.py build/inputs/llvm
python3 -m venv build/radv-venv
. build/radv-venv/bin/activate
python -m pip install -r tools/radv-build-requirements.txt
# Install glslangValidator and pkg-config through your chosen build-host package manager.
python3 tools/build_macos.py --sdk build-sdk --vulkan-headers build-vulkan-headers --translator-source build/inputs/nvmtl-translator-source.tar.gz --mesa build/inputs/radv/mesa --cobalt build/inputs/radv/cobalt --llvm build/inputs/llvm --out build/experimental
```

Outputs under build/experimental/artifacts: PhxBringup.kext, PhxAccel.kext, NVMTLDriver.bundle with libnvmtl_translate.dylib, air-runtime/libLLVM.dylib and libvulkan_radeon.dylib plus its ICD manifest in Contents/MacOS, metal-smoke, provenance and license notices. The build targets x86_64, preserves the upstream kernel ABI/identifiers for integration, applies the downstream gate, signs ad hoc, and checks Mach-O architecture/type. Never load the upstream and downstream variants together. This is not a complete Metal runtime: firmware/bring-up and target-machine runtime integration are still missing. RADV and the AIR bitcode-reader now have source-build paths; consult IMPLEMENTATION-STATUS.md for each verified revision and known deployment gaps.

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

Mesa license texts and Cobalt notices accompany local build output. Mesa includes per-file licenses; root MIT wording is not a complete provenance clearance. glslang/pkg-config are build-host packages rather than pinned source inputs; their/tool versions and dylib dependencies are recorded where applicable. No public binaries are uploaded. The standalone build stages an nvmtl directory without installing it. The complete build instead stages RADV adjacent to the plugin executable, matching the downstream plugin-relative loader.

## LLVM AIR runtime source build and compiler-chain tests

The AIR runtime is LLVM 21.1.8 at exact commit `2078da43e25a4623cab2d0d60decddf709aaea28`. This is an explicitly selected downstream dependency, not a claim that it matches nullarc's unversioned release runtime or that it is the newest LLVM. Its Apache-2.0 WITH LLVM-exception license, legacy notice and included standalone third-party notices are retained. Public binary publication is still blocked.

`tools/fetch_air_runtime.py` uses a fresh, pinned sparse Git checkout. `tools/build_air_runtime.py` builds the real Core/BitReader/BitWriter/IRReader/Passes components into libLLVM on Intel macOS. It disables optional zstd/zlib/libxml2/libedit/libpfm/ffi/curl/httplib dependencies and rejects any remaining non-system dependency in the resulting dylib. It does not copy a Homebrew LLVM binary or redistribute Apple's air-opt. The library is placed at the exact plugin-relative air-runtime/libLLVM.dylib path and the containing bundle is re-signed.

The plugin's ten mandatory reader APIs and its optional diagnostic/pass/IR-walk APIs are extracted from the actual pinned source: all 38 symbols must exist. Export checks alone do not test the behavior of every function. The functional test invokes actual LLVM reader/writer and translator APIs, not mocks:

```sh
python3 tools/test_air_runtime.py --llvm build/experimental/artifacts/NVMTLDriver.bundle/Contents/MacOS/air-runtime/libLLVM.dylib --translator build/experimental/artifacts/NVMTLDriver.bundle/Contents/MacOS/libnvmtl_translate.dylib --plugin-source build/experimental/stage/src/nmplugin/NVMTLLibraryLoad.m --ir-fixture tests/fixtures/compute_increment.ll --metal-fixture tests/fixtures/compute_increment.metal --validator spirv-val --out build/experimental/air-runtime-tests
```

It requires malformed bitcode rejection, a project IR -> bitcode -> IR roundtrip, and two actual `xcrun metal` compilations of project-owned MSL with different arithmetic constants. Each AIR blob must be read into IR, translated into a compute SPIR-V module with store/add operations, and accepted by spirv-val. The two Metal variants must produce different SPIR-V. Missing Metal tools, reader errors, crashes, external validation errors or the 240-second test timeout fail the test; there is no text-fixture fallback for unavailable Apple tools. Generated compiler intermediates stay in the ignored build output and are not published. These are host compiler-chain checks, NOT GPU or full-plugin execution.

The shared Metal compiler recipe uses `-std=metal3.1`. Native run `41069365794` built LLVM successfully but then rejected the former spelling `-std=macos-metal3.1`; the compiler diagnostic explicitly listed `metal3.1` as supported. This is a spelling correction, not a downgrade of the language standard. Both the standalone AIR test and actual-plugin test use the same recipe.

CI now runs `python3 tools/macos_toolchain.py --out build/toolchain-preflight` before the large dependency fetch/build steps. It actually compiles and links both project Metal variants and compiles both native probes with the same recipes used later. It does not execute the probes, load drivers or substitute for subsequent LLVM/plugin/runtime tests. Compiler/tool errors stop the run early; existing output directories are not overwritten.

### RADV runtime dependency gate
The first successful native RADV build also exposed a deployment defect: Mesa auto-detected the CI host's optional SPIRV-Tools library and linked an absolute Homebrew path. The recipe now explicitly sets `-Dspirv-tools=disabled` for Mesa's optional debugging helpers (not the real compiler or the separate mandatory spirv-val tests). Before signing/loading the ICD, `otool -L` must show its expected install name and only `/usr/lib/` or `/System/Library/` dependencies. Other Homebrew, build-directory or unresolved `@rpath` dependencies fail the build instead of being hidden by the CI host's environment. The native result for this correction is tracked separately from the earlier successful-but-host-dependent run.

## Actual Metal plugin compiler integration (native verification pending)

```sh
python3 tools/plugin_runtime.py --bundle build/experimental/artifacts/NVMTLDriver.bundle --fixture tests/fixtures/compute_increment.metal --validator spirv-val --out build/plugin-runtime-tests
```

This is distinct from independently calling LLVM and translator APIs. It compiles two project-owned Metal sources into actual metallib containers, loads a relocated copy of the real plugin with `RTLD_NOW`, and calls its existing `nvmtl_translate_metallib` and `nvmtl_compile_library_entry` exports. No plugin source is replaced by a mock; no Metal or Vulkan device is created. It requires the plugin class/functions and both dynamically loaded compiler runtimes to belong to the expected copied images. The plugin's begun/submitted/abandoned GPU command counters must remain zero. Both generated compute shaders must contain store/add operations, differ by arithmetic variant and pass external SPIR-V validation.

Each subprocess uses fresh, isolated AIR/SPIR-V/Mesa caches. Release constructors clear inherited `NVMTL_*` overrides, so the probe sets cache locations only after loading the plugin. A pre-existing system runtime or target service rejects the test. Separate negative processes remove exactly one runtime from a newly copied bundle (never the original), or supply malformed input. Missing LLVM/translator and malformed-input cases must fail specifically at library indexing; missing RADV must fail at its own runtime check. Loader failure, crashes, timeouts and target-service refusals are not passing negative results. Copied negative bundles are re-signed to avoid confusing a broken bundle seal with dependency rejection.

The downstream plugin resolves RADV beside its own image, not from a system directory or environment override, and refuses the generic Vulkan-loader fallback. After compiler checks the helper invokes the real plugin's Vulkan initialization on the confirmed no-target-service host. It requires the bundled RADV image to be loaded, the actual PhxBringup no-service enumeration diagnostic, failed device initialization and zero GPU command counters. An unrelated initialization failure is not accepted. Deliberately invalid `NVMTL_ICD_LIB`/`VK_ICD_FILENAMES` overrides are set after release constructors to verify they do not redirect this path. This does not test device creation or commands on hardware.

All generated files stay below the fresh ignored output directory. The test does not install the plugin, edit an EFI, enable a GPU or claim full Metal pipeline/WindowServer operation. Python tests cover the runner and fixture-copy rules only; actual plugin behavior requires macOS CI.
