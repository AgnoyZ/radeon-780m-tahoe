# Implementation status (2026-10-31)

## Implemented; target hardware verification pending
- Pinned nullarc source submodule and MacKernelSDK dependency.
- Downstream patches require explicit opt-in and Darwin 25 / PCI 1002:1900 before PCI command changes or framebuffer boot arming consumption.
- Removed legacy no-GPU submission and wait success; unavailable GPU returns NotReady instead of fabricating a fence retirement.
- Removed cross-engine queue fallback; mixed-engine indirect buffers are refused.
- Replaced overflowing 64-bit end-address checks in debug doorbell and PSP ring setup with a shared subtraction-based aperture bound check. Target-region ownership and the broader bring-up workflow remain unresolved; see `BRINGUP-AUDIT.md`.
- Patched every `mesboot.c` IOKit transaction to stop on failed status or mismatched reply length instead of continuing with zero/partial data. Run `41087992288` / code `b2cadc9` passed 47 actual-source fake-transport cases under ASan/UBSan and compiled/linked the real tool against macOS IOKit without running it. See `validation/ci-b2cadc9-transport.json`. Firmware/layout/timeout semantics remain unresolved, and the tool is not deployed.
- Added terminal MES/compute/graphics completion checks before later writes or queue adoption, full-width MES fence/token reads, alignment-safe packet-field encoding and a poisoned graphics result buffer. Run `41089800738` / code `61c5c0e` passed all 52 transport and 20 injected completion cases under sanitizers, plus real-I/O-library compile/link preflight without execution. See `validation/ci-61c5c0e-completion.json`. Other boot experiments and the target memory layout are still not validated.
- Isolated source preparation, native macOS builds, binary inspection, regression tests and private CI artifacts.
- Real Metal compute correctness probe; no CPU or other-GPU fallback.
- Source-build integration for the actual NVMTLDriver Metal plugin, pinned Vulkan headers, normal symbol resolution, exported Objective-C entrypoint checks, matching bundle metadata and dependency license notices. Native CI verification passed (see evidence below).
- Hash-locked LGPL translator source, locked Rust build, all 16 plugin FFI export checks and real-dylib AIR-to-SPIR-V tests passed native CI. Only the translate/free calls and negative-input behavior were exercised; symbol presence does not test the behavior of all 16 exports.

## RADV native build and direct dependency fix verified
- Exact Mesa/Cobalt/nullarc source staging applies all 15 upstream patches plus a native-Phoenix-only downstream patch successfully on the local host. Canonical patch hashes come from Git objects.
- Implemented Intel macOS Mesa/ACO/RADV source build, signed dylib/ICD staging, shared transport-layout assertions and actual no-device dynamic-loading tests. Native CI run `41063982777` initially exposed a Homebrew dependency; the RADV phase of `41067014778` verified its removal (see evidence below). Target deployment remains unverified.
- The downstream driver refuses mock/host-only devices and non-Phoenix profiles; hardware fallback is not a success path. Existing EFI is unchanged.
- First native attempt, run `41062610926` / commit `6cf8369`, reached the shared-header ABI probe but failed because the C11 test omitted `<assert.h>` while the upstream Phoenix header uses `static_assert`. Added the standard header; no assertions or compiler diagnostics are disabled. Mesa compilation and ICD runtime tests were not reached by that failed run.

## LLVM AIR and real-plugin host compiler chain verified
- Selected and fetched LLVM 21.1.8 at `2078da43e25a4623cab2d0d60decddf709aaea28`; audited the source license and the plugin's 38 mandatory/optional C API references. This does not establish equivalence with nullarc's unversioned packaged LLVM.
- Run `41069365794` (`dadac3f`) built the actual LLVM runtime, verified all 38 plugin exports and system-only dependencies, and passed signing checks. The 48,405,008-byte x86_64 dylib has SHA-256 `615e6eab713a5d08f578d1b645a12b5d35ee9f7b6297831e850875370d48fa2b`.
- The overall run then failed when Apple's compiler rejected `-std=macos-metal3.1`, before completing the real Metal/AIR/SPIR-V tests. The recipe now uses the diagnostic's supported `-std=metal3.1` spelling, shared by both compiler tests. An early native toolchain/probe preflight detects such failures before expensive builds. The corrected compiler and actual AIR/plugin chain subsequently passed run `41086848246` below.
- Curated build evidence: `validation/ci-dadac3f.json`. The failed overall result and absence of target execution are retained; GitHub confirms zero binary artifacts.
- Corrected code `011d604`, run `41077457040`, passed source tests and the early native preflight: both real Metal variants compiled/linked and both native probes compiled. The run then failed after all 1,569 LLVM build actions and LLVM signing, when signing the enclosing plugin rejected unsigned `Contents/MacOS/radv-build-report.json`. The later AIR/plugin runtime tests were not reached; this is an overall failure, not a full build pass.
- Both RADV JSON files now stage under `Contents/Resources`, while the dylib stays beside the plugin executable. The ICD points to `../MacOS/libvulkan_radeon.dylib`. The real bundle is signed/strictly verified immediately after RADV staging, before LLVM compilation. No signing bypass is used.
- Early preflight also builds explicitly synthetic Mach-O fixtures in the same nested-code/resource layout, signs/verifies the bundle and checks that modifying either JSON breaks its signature. Run `41086848246` / code `3263e3a` passed this preflight and later the full host build/test pipeline. The earlier preflight snapshot remains in `validation/ci-3263e3a-preflight.json`; final evidence is in `validation/ci-3263e3a-full.json`.

## First complete native host integration pass
- Run `41086848246`, clean code `3263e3aa155e187ebae61751c4c4dc7bbf8b1992`, passed both jobs; its native job completed at `2026-10-30T16:42:01Z` (October 31 in Asia/Shanghai). Zero binary artifacts were retained. The host was Intel macOS 15.7.9, not the target laptop or Tahoe.
- Two kexts, the actual plugin, translator, RADV, LLVM and the Metal probe compiled; applicable signing/structure/export/dependency checks passed. The previously failing enclosing-bundle signature now passes with JSON resources in the correct directory.
- Actual Apple Metal source compilation, LLVM AIR reading and translator output validation passed. The two arithmetic variants produced distinct 1,168-byte SPIR-V modules. The real relocated Metal plugin produced the same respective shader hashes, loaded its own translator/LLVM/RADV images and reached genuine no-service ICD initialization rejection with zero GPU commands.
- Missing translator, missing LLVM, missing RADV and malformed metallib were rejected at their expected failure points, not accepted as crashes or generic loader errors. The Metal execution probe also refused the non-target `106b:eeee` host instead of falling back to it.
- `validation/ci-3263e3a-full.json` cross-checks all four runtime hashes between build and functional reports. Build-phase `runtime_loaded`/`runtime_tested` flags are preserved as compilation-time observations; later functional evidence is recorded separately.
- This revision predates the additional userspace transport/completion patches. Their source/sanitizer/preflight results are recorded separately and their full native runs remain in progress. No run here establishes target initialization, device creation, scanout or hardware acceleration.

## Not implemented / not verified
- Machine-specific firmware carve-out safety, all kernel memory/concurrency paths, panel/power differences and full ABI compatibility audit.
- Initial boot-workflow audit found reference-machine addresses, unchecked IOKit results, masked pipeline failures and automatic reboot/NVRAM changes. See `BRINGUP-AUDIT.md`; the original scripts were inspected but not executed or installed.
- GPU firmware and boot orchestration; runtime integration of the full Metal stack on the target GPU. The tested host-side LLVM AIR/plugin compiler chain now passes, but broader shader coverage and target execution remain unverified.
- Tahoe installation on the target laptop and actual GPU command completion, Metal rendering, WindowServer integration and long-run stability.
- Resolved ABI provenance discrepancy noted in EXPERIMENTAL.md; no external redistribution authorization is inferred.

The goal remains a working 780M Tahoe graphics stack. This milestone is a code/build foundation, not completion. Current working EFI and Windows disks are untouched.

## Verified locally
- Current suite: 63 Python tests passed, including real Git/worktree patch-order tests, aperture-check wiring, plugin-relative RADV staging, resource metadata paths/overwrite refusal, shared compiler recipes, preflight guards and transport/completion/compiler-runner rejection checks. The real 16-patch Mesa source stage also applied successfully; no native RADV binary has been built locally.
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
- Follow-up disables Mesa's optional SPIRV-Tools debugging linkage via its supported Meson feature and adds a hard system-only dependency gate. Shader compilation remains enabled and external spirv-val validation remains mandatory. The correction passed the subsequent RADV phase documented below.
- Sanitized evidence with the original dependency list: `validation/ci-a296873.json`. GitHub confirms zero retained artifacts. LLVM/real Metal compiler-chain integration was not part of this historical run.

## RADV dependency correction and LLVM configuration failure
- Run `41067014778`, code `034d0c2ff47260c3483dcc17eb378e4dfa412c25`, verified RADV's direct dependencies contain only IOKit and system libSystem/libz/libc++; the absolute Homebrew SPIRV-Tools dependency is gone. The dylib is 20,264,208 bytes, SHA-256 `bf386fee7ab64d49618c5daf753b74eed28e002bc70aa8e72a638aa26401e915`.
- Signing, the real shared-header ABI checks and all four actual load/empty-enumeration cases passed. All 16 patch hashes match the previous build. This is not a VkDevice, GPU submission or target-machine integration test.
- The overall run failed afterward at LLVM configuration because its sparse checkout excludes `llvm/docs`. The same failure occurred in `41065701927`. Commit `dadac3f` explicitly disables documentation; its regression test reproduced the omission before the fix. Actual LLVM compilation and compiler-chain validation still require native CI evidence.
- Sanitized partial-build evidence: `validation/ci-034d0c2.json`. The overall failure is preserved rather than reported as a full pass; GitHub confirms no retained artifacts.

## Metal compute acceptance probe
- Commit `e454560` replaces marketing-name matching with Metal registry ID to PCI `1002:1900` verification, refuses ambiguous/unverified identities and permits submission only on Darwin 25.
- Six real dispatch sizes use alternating 0/256-byte output offsets, unchanged-input checks, guards and independent expected results. Complement initialization rejects missing GPU writes. The checker is shared with synthetic CPU tests; those tests are not GPU evidence.
- Run `41086848246` passed native Objective-C compilation, source/sanitizer checks and the non-target-host refusal. No probe has executed on the target laptop.

## Plugin-relative RADV host integration verified
- The full build now packages RADV alongside the plugin executable. A downstream source patch resolves this exact library from the loaded plugin image and removes system-path/environment selection and generic Vulkan-loader fallback. Standalone RADV builds retain their separate layout. No installed file is changed.
- Source staging records the new patch and shared path helper hashes. C++ sanitizer tests cover path bounds/invalid inputs; Python tests cover actual patch application, matching package layout and refusing overwrites.
- The real-plugin host test now additionally attempts initialization only after confirming target services are absent. It requires the expected bundled RADV image, its no-service diagnostic and zero GPU command counters; an unexplained failure is not success. Missing RADV is a separate negative case, using a newly copied/re-signed bundle.
- The actual plugin/LLVM/RADV compiler and no-device integration passed run `41086848246`; target GPU interoperability remains unproven. See the complete native host evidence above.
- The RADV phase of run `41073491733` (`84fad0d`) verified plugin-relative staging, signing, system-only dependencies and all four direct-load/no-device cases; binary hash `bf386fee7ab64d49618c5daf753b74eed28e002bc70aa8e72a638aa26401e915` matches the previous RADV build. This is not proof that the Metal plugin itself has loaded it. See `validation/ci-84fad0d.json`.
- Runs `41069685354`, `41071134458` and `41073491733` were intentionally cancelled after checking that each revision still contained the compiler flag proven invalid in `41069365794`. GitHub confirms all three are terminal/cancelled. The corrected run `41077457040` later failed at the bundle resource layout described above; none of these runs is counted as a full pass.
