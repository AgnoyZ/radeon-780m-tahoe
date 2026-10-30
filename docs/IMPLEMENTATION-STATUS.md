# Implementation status (2026-10-30)

## Implemented; target hardware verification pending
- Pinned nullarc source submodule and MacKernelSDK dependency.
- Downstream patches require explicit opt-in and Darwin 25 / PCI 1002:1900 before PCI command changes or framebuffer boot arming consumption.
- Removed legacy no-GPU submission and wait success; unavailable GPU returns NotReady instead of fabricating a fence retirement.
- Removed cross-engine queue fallback; mixed-engine indirect buffers are refused.
- Isolated source preparation, native macOS builds, binary inspection, regression tests and private CI artifacts.
- Real Metal compute correctness probe; no CPU or other-GPU fallback.
- Source-build integration for the actual NVMTLDriver Metal plugin, pinned Vulkan headers, normal symbol resolution, exported Objective-C entrypoint checks, matching bundle metadata and dependency license notices. Native CI verification passed (see evidence below).
- Hash-locked LGPL translator source, locked Rust build, all 16 plugin FFI export checks and real-dylib AIR-to-SPIR-V tests passed native CI. Only the translate/free calls and negative-input behavior were exercised; symbol presence does not test the behavior of all 16 exports.

## RADV native build verified; dependency fix pending
- Exact Mesa/Cobalt/nullarc source staging applies all 15 upstream patches plus a native-Phoenix-only downstream patch successfully on the local host. Canonical patch hashes come from Git objects.
- Implemented Intel macOS Mesa/ACO/RADV source build, signed dylib/ICD staging, shared transport-layout assertions and actual no-device dynamic-loading tests. Native CI run `41063982777` passed this component on its build host; the resulting binary has a host-library dependency that must be removed before deployment (see evidence below).
- The downstream driver refuses mock/host-only devices and non-Phoenix profiles; hardware fallback is not a success path. Existing EFI is unchanged.
- First native attempt, run `41062610926` / commit `6cf8369`, reached the shared-header ABI probe but failed because the C11 test omitted `<assert.h>` while the upstream Phoenix header uses `static_assert`. Added the standard header; no assertions or compiler diagnostics are disabled. Mesa compilation and ICD runtime tests were not reached by that failed run.

## LLVM AIR reader integration in progress
- Selected and fetched LLVM 21.1.8 at `2078da43e25a4623cab2d0d60decddf709aaea28`; audited the source license and the plugin's 38 mandatory/optional C API references. This does not establish equivalence with nullarc's unversioned packaged LLVM.
- Implemented source build, plugin-relative staging, dependency rejection, export and ad-hoc signing checks and bounded real Metal -> AIR -> LLVM IR -> SPIR-V host tests. These new native steps are pending CI; no successful reader/Metal compiler-chain execution is claimed yet.

## Not implemented / not verified
- Machine-specific firmware carve-out safety, all kernel memory/concurrency paths, panel/power differences and full ABI compatibility audit.
- Self-contained RADV dependency fix, verified LLVM AIR runtime build, GPU firmware and boot orchestration; runtime integration of the full Metal stack on the target GPU.
- Tahoe installation on the target laptop and actual GPU command completion, Metal rendering, WindowServer integration and long-run stability.
- Resolved ABI provenance discrepancy noted in EXPERIMENTAL.md; no external redistribution authorization is inferred.

The goal remains a working 780M Tahoe graphics stack. This milestone is a code/build foundation, not completion. Current working EFI and Windows disks are untouched.

## Verified locally
- Current suite: 37 Python tests passed, including real Git/worktree patch-order tests and negative-runtime runner rejection checks. The real 16-patch Mesa source stage also applied successfully; no native RADV binary has been built locally.
- Previous Windows Python regression suite: 23 tests passed, including applying the patch to the pinned source, validating the plugin build/entrypoint contract, source-integrity rejection and SPIR-V envelope rejection. New module tests were first observed failing before their implementations existed.
- Actual translator release archive hash and layout verified locally; 321 Rust source files are present. Rust compilation itself was performed on macOS CI, not this Windows host.
- Python syntax compilation passed. Native C++/kext/Metal builds are delegated to CI, not claimed as local passes.

## Native CI evidence
- Code commit `87109fc328d71cb1bd664472b2b18a4054c32ee7`, run `41056244424`: Python integration tests and C++ ASan/UBSan policy checks passed.
- Intel macOS CI compiled and linked PhxBringup.kext and PhxAccel.kext, ad-hoc signed and verified both, passed x86_64 MH_KEXT_BUNDLE checks, and compiled metal-smoke.
- Sanitized compiler/provenance/hash report: `validation/ci-87109fc.json`. This is a build result, NOT a target hardware result.
- Overall run failed only at artifact upload: account Actions storage quota exhausted, zero artifacts retained. No old artifacts were deleted and no billing setting was changed.
- Follow-up CI defaults to explicitly labelled compile/test-only runs. Artifact retention is opt-in via workflow_dispatch; a requested upload failure still fails the job.

## Metal plugin native build evidence
- Code commit `4c00a755b5747119acf2716b6015b4a0d892afbe`, run `41058029421`: both jobs passed.
- The real NVMTLDriver translation unit compiled/linked into an x86_64 MH_BUNDLE (1,535,136 bytes); both Objective-C entrypoint exports and ad-hoc signing verification passed. No undefined-symbol bypass was used.
- Sanitized evidence: `validation/ci-4c00a75.json`. Runtime plugin loading and GPU execution remain false; no binary artifacts were retained/published.

## Translator native build and functional evidence
- Code commit `21642eb77355f9ca00cb194c5f1f330d6bc3e7a5`, run `41059257964`: both jobs passed, including real-dylib translation and external SPIR-V validation.
- Rust 1.90.0 compiled the locked source into an x86_64 MH_DYLIB (14,659,472 bytes); the unchanged Cargo.lock hash and all 16 plugin-requested exports were verified. The bundle was re-signed after adding the dylib.
- Two distinct AIR kernels produced distinct 1,128-byte SPIR-V modules. Both retained compute entrypoint/store/integer-add operations and passed SPIRV-Tools v2026.3 validation for Vulkan 1.2. Invalid-stage and malformed-IR requests failed as required.
- Sanitized build and functional reports: `validation/ci-21642eb.json`. These are host-side compiler tests; no GPU workload, display takeover or WindowServer acceleration has run on the target laptop. No binary artifacts were retained/published.

## RADV native build and no-device evidence
- Code commit `a2968730f7b035d8f62867fceeee1472157c5571`, run `41063982777`: both jobs passed after the C11 assertion-header fix. Mesa produced an x86_64 MH_DYLIB of 20,264,560 bytes, SHA-256 `51e7925c2af6110ed71d7e7052f03054766b34bac3db0163f125abc5eb94e4e4`; signing and the actual shared-header transport checks passed.
- Real ICD dlopen(RTLD_NOW), Vulkan instance creation, Phoenix service policy and empty physical-device enumeration passed in four separate processes: native/no service, rejected mock, rejected host-only and rejected non-Phoenix profile. No VkDevice was created and no GPU work was submitted.
- **Portability gap found in the successful report:** the dylib links `/usr/local/opt/spirv-tools/lib/libSPIRV-Tools.dylib`. The CI host has that library; a clean target system need not. Host loading therefore does NOT establish a deployable runtime.
- Follow-up disables Mesa's optional SPIRV-Tools debugging linkage via its supported Meson feature and adds a hard system-only dependency gate. Shader compilation remains enabled and external spirv-val validation remains mandatory. This correction is pending new native validation.
- Sanitized evidence with the original dependency list: `validation/ci-a296873.json`. GitHub confirms zero retained artifacts. LLVM/real Metal compiler-chain integration was not part of this historical run.
