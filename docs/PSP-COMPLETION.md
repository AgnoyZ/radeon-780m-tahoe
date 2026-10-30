# PSP completion and firmware staging: experimental correction

Patch `0007-checked-psp-completion.patch` corrects a kernel-side false-success path
in the pinned `PhxBringup` source. Previously `pspRunCmd` returned IOKit success
even when its fence never arrived or the PSP response status was nonzero.
`pspCtl(SETUP_TMR)` then marked TMR established based only on that return value.
No real PSP execution was used to discover or validate this issue.

## Changed behavior

- A missing/mismatched completion fence returns `kIOReturnTimeout`. A completed
  command with nonzero PSP status returns `kIOReturnError`. Only matching fence
  and zero status return success. Output addresses remain zero on failure.
- TMR is marked established and its size published only after successful command
  completion. Failure clears those software claims. Oversized TMR requests fail
  instead of being silently reduced to the reference capacity.
- PSP command errors/timeouts latch `pspSubmissionFaulted` for the driver instance.
  Later GPCOM submissions, firmware staging/loading and ring create/destroy calls
  refuse writes. Software `clearRing` does not clear the fault. Read-only ring
  status remains available; this is not a reset or a recovery procedure.
- Unconfirmed ring creation/destruction also latches the fault. A failed destroy
  does not pretend the live ring was successfully cleared.
- Command arguments, mapped extents, ring-pointer frame alignment and fence
  exhaustion are checked before command-buffer/fence/ring writes. The reference
  one-past-ring write-pointer sentinel is retained; arbitrary high values are not.
- Firmware staging checks the padded dword write extent under the same lock as
  its state checks, preventing a final partial word from overrunning the buffer.
  Firmware-load address arithmetic is checked before submission. Packed frame
  fields are copied without an alignment-dependent pointer cast.

IOKit does not guarantee output scalars on a failed call. Callers must treat the
non-success return as authoritative and must not read zero-initialized outputs as
PSP success. The wire layout/selector numbers are unchanged. The original debug
CLI and shell scripts still need checked orchestration; this patch does not turn
their printed diagnostics or shell exit codes into a safe deployment workflow.

Nonzero-status rejection is a deliberate conservative policy, not a claim that
every AMD firmware version uses nonzero exclusively for fatal errors. Linux
v6.18 `amdgpu_psp.c` at commit `7d0a66e4bb9081d75c82ec4957c50034cb0ea449`
documents firmware versions with nonzero statuses on otherwise valid submissions
and tolerates some of them. This project has no target/version/command-specific
evidence supporting those exceptions yet. Any necessary exception must be
validated explicitly; the strict policy may currently reject a usable firmware
path. Fence timeout remains unequivocally unconfirmed completion.

## Host verification

`tools/test_psp_submission.py` stages the actual patched source and extracts six
unaltered method bodies plus the real ring-frame definition. It records each
method hash and compiles those bodies with the staged ABI/policy headers. The
harness supplies explicit fake memory, MMIO, locks, time and PSP responses.
This is not a copy of the kernel algorithm rewritten for the test.

Thirty-two cases cover successful command/TMR/load/staging paths, failed fences
and PSP statuses, sequence exhaustion, frame boundaries, invalid command words,
mapped-range overflow, a partial staging word and ring lifecycle failures. The
negative lifecycle cases attempt follow-up operations and require unchanged fake
memory/register-write counts, including after software ring clearing. Positive
cases check actual frame/command fields and returned addresses. The Linux CI job
runs them under ASan/UBSan before native driver builds. Run `41099945379`, code
`7921a7c`, reports this test step completed successfully at `2026-10-30T17:34:18Z`.
The source job subsequently reported completed/success and its log became
available. All 32 per-case reports passed; the six extracted method hashes match
the currently staged method bodies and all seven recorded patch hashes match
their source files. Full per-case evidence is in
`validation/ci-7921a7c-psp.json`; the earlier step-only observation is preserved
in `validation/ci-7921a7c-psp-step.json`. The complete native kernel build remains
unverified. These fake-hardware observations do not verify PSP firmware behavior.

## Remaining hardware requirements

Patch 0009 now replaces implicit managed PSP offsets with a shared explicit
descriptor; see `PSP-LAYOUT.md`. The harness extracts a seventh actual method for
configuration and adds sixteen cases (48 total). Those new C++ cases are pending
CI execution. The previously recorded 32-case result is historical evidence for
code `7921a7c`, not verification of the changed methods.

Stopping writes does not cancel in-flight firmware, roll back prior writes,
prove memory ownership or establish a safe reboot/unload/reset. The latch is
software state, not a persistent hardware interlock. Unrelated raw debug MMIO,
VRAM and SMU operations are outside this guard; do not run the reference scripts.
Reference addresses outside the managed PSP path, firmware provenance/selection, target TMR sizing,
exclusive ownership and recovery still need integration with target evidence.

No kext was loaded, firmware executed or machine setting changed. The full goal
remains real GPU operation and display/Metal integration on the target Tahoe
machine, not merely successful host fault tests.
