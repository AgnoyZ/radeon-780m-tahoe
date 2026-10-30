# Experimental builds: not an installation release

These artifacts are research builds for noncommercial development, NOT a complete or hardware-validated driver distribution.

- PhxBringup and PhxAccel are patched builds of the pinned nullarc source, not a new from-scratch implementation.
- The kernel and framebuffer paths require Darwin 25, PCI 1002:1900, and explicit `phx780m=1` opt-in. Existing kill switches are retained. This flag alone does NOT initialize the GPU or enable Metal.
- Do not load/install them yet: the firmware layout, panel, runtime ABI and full userspace stack still require machine-specific review.
- The build now compiles the upstream Metal plugin from source; it is NOT a complete runtime. Firmware, RADV, the shader translator and boot-time orchestration are NOT included. Dropping these kexts into EFI cannot produce a complete working graphics stack.
- No boot config, NVRAM, OS security setting or disk is changed by the build scripts. No installer is supplied.
- `metal-smoke --list` lists Metal devices without submitting work. Running `metal-smoke` submits real compute work and can hang an experimental GPU; use only after independently establishing the runtime stack and recovery path.
- A compute pass does not verify WindowServer, external display, backlight, codec acceleration, sleep or sustained stability.

## Licenses and provenance

Read the included UPSTREAM-LICENSE, UPSTREAM-THIRD_PARTY_NOTICES.md and LICENSES directory.
PhxAccel/NullMoth-derived components are PolyForm Noncommercial 1.0.0.

Required Notice: Copyright (c) 2026 NullMoth Systems (https://nullmothsystems.com)

PhxBringup is offered upstream under MIT or GPL-2.0-only (subject to per-file notices). Its ABI header identifies BSD-3-Clause/Cobalt64 provenance while the upstream summary labels that contribution MIT. This discrepancy is an open audit item; do not relicense or publicly redistribute the builds until resolved.
MacKernelSDK is an external pinned build dependency with APSL/per-file terms, not bundled here. No Apple OS binaries or hardware firmware are included.
Vulkan-Headers is pinned at `6802bb4733b63ed5efd3adb308a6c885ef180ea1`; its Apache-2.0/MIT notices are included under DEPENDENCY-LICENSES. NVMTLDriver.bundle is also NullMoth-derived and subject to PolyForm Noncommercial terms. The plugin's embedded conversion-shader data is upstream source content, not an Apple OS executable.

`build-report.json` records commits, patch/policy hashes, compiler and artifact hashes. Structural Mach-O and signing checks do not establish runtime loadability. `hardware_tested` stays false until real machine evidence exists.
