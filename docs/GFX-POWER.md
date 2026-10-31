# Checked GFX power request and boot readiness

Patch `0012-checked-gfx-power-sequence.patch` extends the actual research
`phxctl` with a separate `gfx-power-sequence` command. It performs the complete
profile-driven firmware sequence and then requests IMU power-up and observes
GFX boot status. It has not run on the target GPU. It does not set up GART,
bootstrap MES queues, execute shaders or enable display acceleration.

## Fixed-source review

The implementation was checked against Linux commit
`7d0a66e4bb9081d75c82ec4957c50034cb0ea449`, specifically:

- `drivers/gpu/drm/amd/pm/swsmu/smu13/smu_v13_0_4_ppt.c`: message mapping and
  the IMU power-up callback for this SMU generation.
- `drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu_v13_0_4_ppsmc.h`: interface query
  `0x03`, PMFW query `0x02`, EnableGfxImu `0x16`, successful response `1`.
- `drivers/gpu/drm/amd/pm/swsmu/inc/pmfw_if/smu13_driver_if_v13_0_4.h`:
  reviewed driver interface version `8`.
- `drivers/gpu/drm/amd/pm/swsmu/smu13/smu_v13_0.c`:
  `smu_v13_0_set_gfx_power_up_by_imu` uses an acknowledged message for
  PSP-loaded firmware. Its argument `1` is named GFXOFF_ENABLE; it is not an
  arbitrary Boolean invented for this tool.
- `drivers/gpu/drm/amd/amdgpu/gfx_v11_0.c`:
  `gfx_v11_0_wait_for_rlc_autoload_complete` checks CP_STAT zero and the RLC
  BOOTLOAD_COMPLETE field. GC 11.0.1 uses the special `0x4e7e`, base-index 1
  RLC status offset, not the tool's former generic `0x4e82` offset.
- `drivers/gpu/drm/amd/include/asic_reg/gc/gc_11_0_0_offset.h` and
  `gc_11_0_0_sh_mask.h`: CP_STAT offset `0x0f40` at base-index 0 and
  BOOTLOAD_COMPLETE at bit 31 (`0x80000000`). Bit 0 is not readiness.

The referenced files carry AMD MIT-style notices, inspected before this change.
This patch adds independently written sequencing/polling code and factual
protocol constants; it does not copy Linux implementation bodies or whole
headers. Source hashes and checked metadata are in
`validation/linux-gfx-power-reference.json`. The existing nullarc source and
component notices still apply; this does not authorize binary publication.

The GC segment bases `0x1260` and `0xA000` remain the pinned reference profile's
assumptions. Consequently the candidate absolute dword registers are `0x21a0`
and `0xee7e`. Neither the PCI identifier nor the firmware file hashes prove the
target's IP discovery matches those assumptions. Target review is still needed.
The `gc` diagnostic register list now uses the same corrected RLC offset.

## Command and ordering

```text
phxctl gfx-power-sequence <firmware-directory> <ring-offset> <tmr-offset> <tmr-capacity> <staging-offset> <staging-capacity>
```

The ordinary `firmware-sequence` command still performs firmware work only.
The new command uses the same no-default-address layout contract and all nine
authenticated immutable snapshots. After snapshot verification and the single
IOKit/ABI handshake, it queries the SMU driver interface and PMFW version before
configuring PSP layout or staging bytes. The interface must equal `8`; unlike
Linux's more permissive compatibility policy, this unvalidated candidate stops
on a different version instead of guessing compatibility. PMFW version is
recorded as an observation, not treated as proof of support.

After layout, ring, TOC-size negotiation, exact TMR setup, all seventeen IP
loads and RLC autoload succeed, it sends EnableGfxImu with argument `1`.
Any failed or malformed response stops before polling. All SMU replies now
also reject returned argument values wider than the actual 32-bit protocol
field, preventing silent userspace truncation.

The readiness loop requires **both** CP_STAT zero and RLC bit 31 set in one
sample. It checks the monotonic deadline before the reads and after them so
late ready-looking data cannot pass. It stops on clock failure/backwards time,
read errors, short/long replies or delay errors. Interrupted delays return to
the outer bounded loop. Two independent local limits apply: 2 seconds and
2000 samples, with a requested 1 ms delay between incomplete observations.
These are explicit diagnostic policy limits, not vendor-specified timing or a
guarantee that a stalled synchronous kernel call can be interrupted in 2 seconds.

Only after observed readiness and successful service close does it report:
`IMU acknowledged and GFX boot readiness observed; queues/shaders/display unverified`.
An acknowledged SMU message alone is insufficient. Zero/all-ones reads, an
incorrect completion bit or CP still busy do not constitute readiness.
Even correct status bits do not prove newly executed compute work or clear
the larger target compatibility and memory ownership requirements.

## Failure and verification boundaries

Errors do not reset the GPU, destroy the ring or unload firmware. Earlier
commands may have changed device state; stopping the process is not rollback.
No automatic retry, NVRAM/EFI mutation, installation or security change is added.
This command remains a research initialization path, not a deployment workflow.

The actual-CLI harness now exercises both modes. The GFX suite uses 157
synthetic cases: all firmware prerequisite cases plus SMU reply/version faults,
immediate/delayed readiness, independent CP/RLC failures, wrong completion bit,
all-ones reads, exact deadlines, backwards/frozen/invalid clocks, failed or
interrupted sleeps and malformed register replies. It checks exact operation
order/counts and verifies snapshots are freed. Fake clocks avoid waiting on
real wall time; fake registers do not emulate a GPU.

Local Python tests pass (128 tests). Actual C/ASan/UBSan results and native
compilation must be recorded from CI for this revision before claiming they
passed. Native execution remains limited to hardware-free verification paths.
