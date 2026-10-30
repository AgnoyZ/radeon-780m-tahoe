# Implementation status (2026-10-30)

## Implemented; native compilation and hardware verification pending
- Pinned nullarc source submodule and MacKernelSDK dependency.
- Downstream patches require explicit opt-in and Darwin 25 / PCI 1002:1900 before PCI command changes or framebuffer boot arming consumption.
- Removed legacy no-GPU submission and wait success; unavailable GPU returns NotReady instead of fabricating a fence retirement.
- Removed cross-engine queue fallback; mixed-engine indirect buffers are refused.
- Isolated source preparation, native macOS builds, binary inspection, regression tests and private CI artifacts.
- Real Metal compute correctness probe; no CPU or other-GPU fallback.

## Not implemented / not verified
- Machine-specific firmware carve-out safety, all kernel memory/concurrency paths, panel/power differences and full ABI compatibility audit.
- Complete builds/integration of RADV, Metal plugin, shader translator, GPU firmware and boot orchestration.
- Tahoe installation on the target laptop and actual GPU command completion, Metal rendering, WindowServer integration and long-run stability.
- Resolved ABI provenance discrepancy noted in EXPERIMENTAL.md; no external redistribution authorization is inferred.

The goal remains a working 780M Tahoe graphics stack. This milestone is a code/build foundation, not completion. Current working EFI and Windows disks are untouched.

## Verified locally
- Windows Python regression suite: 11 tests passed, including applying the patch to the pinned source.
- Python syntax compilation passed. Native C++/kext/Metal builds are delegated to CI, not claimed as local passes.
