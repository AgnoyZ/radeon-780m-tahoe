# Experimental builds: not an installation release

These artifacts are research builds for noncommercial development, NOT a complete or hardware-validated driver distribution.

- PhxBringup and PhxAccel are patched builds of the pinned nullarc source, not a new from-scratch implementation.
- The kernel and framebuffer paths require Darwin 25, PCI 1002:1900, and explicit `phx780m=1` opt-in. Existing kill switches are retained. This flag alone does NOT initialize the GPU or enable Metal.
- Do not load/install them yet: the firmware layout, panel, runtime ABI and full userspace stack still require machine-specific review.
- The build includes source-build paths for the upstream Metal plugin, LGPL AIR translator, native-only Mesa RADV and pinned LLVM AIR bitcode reader/runtime; this is NOT a complete or target-validated runtime. Firmware and boot-time orchestration remain missing. Dropping these kexts into EFI cannot produce a complete working graphics stack.
- No boot config, NVRAM, OS security setting or disk is changed by the build scripts. No installer is supplied.
- `metal-smoke --list` lists Metal devices and their registry-derived PCI identity without submitting work. Execution requires exactly one verified PCI `1002:1900` Metal device and Darwin 25; a marketing name alone is not accepted. Running `metal-smoke` submits real compute work and can hang an experimental GPU; use only after independently establishing the runtime stack and recovery path.
- The probe checks six dispatch sizes, alternates output offsets of 0/256 bytes, validates every output against the original input seed, verifies unchanged input and checks output guard regions. Output starts as the bitwise complement of its expected value so a missing write cannot pass. CPU fixtures exercise this same checker in CI but are never evidence of GPU execution.
- A compute pass does not verify WindowServer, external display, backlight, codec acceleration, sleep or sustained stability.

## Native validation status

- Run `41063982777` (`a296873`) built and loaded native RADV, checked the shared kernel/userspace ABI and enumerated zero devices on a non-target host. It did not create a Vulkan device or execute GPU work. Its absolute Homebrew SPIRV-Tools dependency prevents treating that build as deployable; see `docs/validation/ci-a296873.json`.
- Commit `034d0c2` disables RADV's optional SPIRV-Tools debugging dependency and rejects non-system dylib dependencies. Run `41067014778` passed this RADV phase before failing later in LLVM configuration; see `docs/validation/ci-034d0c2.json`. This does not disable the shader compiler or the separate generated-SPIR-V validation tests.
- Run `41065701927` (`c1fb030`) failed during LLVM CMake configuration: the sparse checkout excludes `llvm/docs`, but documentation was enabled. The recipe explicitly sets `LLVM_INCLUDE_DOCS=OFF`; the regression test first reproduced that omission. Core, bitreader, bitwriter, irreader and passes remain enabled.
- Run `41069365794` (`dadac3f`) then built/signed the LLVM runtime, verified its 38 plugin exports and system-only dependencies, but failed at the actual Metal compiler's rejection of `-std=macos-metal3.1`. The shared recipe now uses the compiler-supported `-std=metal3.1` and CI preflights both Metal fixture variants and native probe compilation before heavy builds. Full AIR/plugin validation is still pending; see `docs/validation/ci-dadac3f.json`.
- Hosted CI is not Radeon 780M hardware evidence. No Tahoe target run, deployment or working acceleration is claimed. Public binary uploads remain disabled.

## Licenses and provenance

Read the included UPSTREAM-LICENSE, UPSTREAM-THIRD_PARTY_NOTICES.md and LICENSES directory.
PhxAccel/NullMoth-derived components are PolyForm Noncommercial 1.0.0.

Required Notice: Copyright (c) 2026 NullMoth Systems (https://nullmothsystems.com)

PhxBringup is offered upstream under MIT or GPL-2.0-only (subject to per-file notices). Its ABI header identifies BSD-3-Clause/Cobalt64 provenance while the upstream summary labels that contribution MIT. This discrepancy is an open audit item; do not relicense or publicly redistribute the builds until resolved.
MacKernelSDK is an external pinned build dependency with APSL/per-file terms, not bundled here. No Apple OS binaries or hardware firmware are included.
Vulkan-Headers is pinned at `6802bb4733b63ed5efd3adb308a6c885ef180ea1`; its Apache-2.0/MIT notices are included under DEPENDENCY-LICENSES. NVMTLDriver.bundle is also NullMoth-derived and subject to PolyForm Noncommercial terms. The plugin's embedded conversion-shader data is upstream source content, not an Apple OS executable.
The separately built libnvmtl_translate.dylib is LGPL-3.0-or-later, not PolyForm. Its exact source archive accompanies local artifacts under SOURCE, with NOTICE/LICENSE/COPYING under DEPENDENCY-LICENSES. No claim is made that these steps alone resolve every dependency's redistribution requirements; public binary publication remains blocked.

`build-report.json` records commits, patch/policy hashes, compiler and artifact hashes. Structural Mach-O and signing checks do not establish runtime loadability. `hardware_tested` stays false until real machine evidence exists.
