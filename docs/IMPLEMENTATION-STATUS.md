# Implementation status (2026-10-30)

## Implemented; target hardware verification pending
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

## Native CI evidence
- Code commit `87109fc328d71cb1bd664472b2b18a4054c32ee7`, run `41056244424`: Python integration tests and C++ ASan/UBSan policy checks passed.
- Intel macOS CI compiled and linked PhxBringup.kext and PhxAccel.kext, ad-hoc signed and verified both, passed x86_64 MH_KEXT_BUNDLE checks, and compiled metal-smoke.
- Sanitized compiler/provenance/hash report: `validation/ci-87109fc.json`. This is a build result, NOT a target hardware result.
- Overall run failed only at artifact upload: account Actions storage quota exhausted, zero artifacts retained. No old artifacts were deleted and no billing setting was changed.
- Follow-up CI defaults to explicitly labelled compile/test-only runs. Artifact retention is opt-in via workflow_dispatch; a requested upload failure still fails the job.
