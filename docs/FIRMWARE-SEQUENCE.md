# Profile-driven firmware initialization (experimental)

Patch `0011-profile-firmware-sequence.patch` adds an actual `phxctl` command
that keeps one IOKit connection through layout, ring, TOC, TMR and firmware
loading. It is a candidate implementation, not a working 780M acceleration
claim. It has not been run against the target GPU or Tahoe.

## Reviewed metadata, immutable inputs

`tools/firmware_profile.py` generates `src/PhxFirmwareProfile.h` from
`firmware.lock.json` and `docs/validation/firmware-08624cd.json`. The header
contains only nine filenames, whole-file hashes/sizes and eighteen selected
component extents/types. It contains no firmware bytes. Source preparation
refuses a stale header and records the normalized header SHA-256 in provenance.
All nine local files were re-inspected against the existing audit while adding
this sequence; the manifest matched exactly. That verifies file metadata,
not device compatibility or vendor signatures.

Selection follows the pinned nullarc `bringup5.sh` candidate recipe; enum values
were checked against Linux commit
`7d0a66e4bb9081d75c82ec4957c50034cb0ea449`,
`drivers/gpu/drm/amd/amdgpu/psp_gfx_if.h`:

| Selection after TOC | PSP firmware types |
| --- | --- |
| PFP, ME, MEC instruction | 2, 1, 4 |
| SDMA context, control | 71, 72 |
| MES_2 instruction, data | 33, 34 |
| MES1 instruction, data | 81, 82 |
| IMU instruction, data | 68, 69 |
| RLC restore GPM, restore SRM, IRAM, DRAM, RLCP, ucode | 20, 21, 26, 48, 25, 8 |

TOC is submitted using `LOAD_TOC`, not as firmware type 24. MEC's separate
jump table is not appended to its instruction component. These choices are
explicit reference candidates; they require confirmation for the target IP
discovery and firmware revision before hardware use.

## Command contract

```text
phxctl firmware-sequence <firmware-directory> <ring-offset> <tmr-offset> <tmr-capacity> <staging-offset> <staging-capacity>
```

This interface deliberately supplies no default device addresses. Its arguments
are VRAM-relative byte offsets/capacities from a separately reviewed target
allocation. Numeric fit is not an allocation or exclusive ownership grant.
The missing ownership mechanism remains a prerequisite to deployment.

1. Validate complete arguments, aligned/disjoint/overflow-safe relative extents
   and capacity for every compiled component before service lookup.
2. Read all nine bounded regular files and verify whole-file CommonCrypto SHA-256
   plus exact sizes. Retain all snapshots before opening IOKit. Missing or
   mismatched later files cannot leave earlier components loaded.
3. Open one connection, require the existing ABI handshake, configure layout
   through selector 114, independently check its reported MC/physical/VRAM/BAR
   bounds, and reject misaligned TMR addresses before ring creation.
4. Create the ring; require transport success and the expected ring MC address.
5. Stage the TOC, submit selector 115 and require confirmed PSP completion, a
   positive 32-bit TMR size, fit flag exactly one, and independent capacity and
   address-alignment validation. SETUP_TMR uses exactly that observed size.
6. Stage and load all seventeen IP components in recipe order. Chunks are at
   most 4096 bytes and use offsets relative to the staging region, restarting
   at zero for each component only after synchronous checked completion.
7. Require RLC autoload completion, close the connection and free snapshots.
   The success message explicitly says GPU operation is unverified.

An error stops without later commands and releases userspace snapshots. A
partial device sequence is **not rolled back**: the ring, TMR or loaded firmware
may remain live, and uncertain submissions may have faulted the managed kernel
path. Process exit is not a device reset. Do not blindly rerun the command or
use raw-debug requests to bypass a failure. No automatic reset/retry is added.
The existing privileged/debug selector gates still apply. Keeping one connection
does not establish cross-client exclusivity for all device operations.

The command does not power GFX up through SMU, initialize GART, bootstrap MES,
adopt graphics queues, execute a shader or take over the display. It is one
necessary part of that larger initialization pipeline. Working EFI files and
security settings are unchanged.

The separate `gfx-power-sequence` command added in patch 0012 extends this
firmware path with checked SMU interface/version queries, IMU power-up and
bounded CP/RLC boot-readiness observations. It does not alter this command's
firmware-only behavior. See `GFX-POWER.md` for its additional prerequisites and
verification limits.

## Verification scope

`python tools/firmware_profile.py --check` checks deterministic metadata.
The Python suite validates reference selection, wrong identities/revisions,
missing/duplicate inputs/components, extents/types and stale-header rejection.

`python tools/test_firmware_sequence.py --out <new-directory>` compiles the
actual patched CLI independently, then includes it in an ASan/UBSan harness
with fake IOKit and nine synthetic files. Tests check exact bytes and component
types/order, all hashes before service lookup, one open, mutation of every file
after the first transfer, failure at every staging/load step, malformed replies,
size/fit/transport errors and no continuation after failed prerequisites.
The harness checks that snapshots have been freed at process exit.

Its crypto stub validates deterministic synthetic bytes and returns fixture
profile digests; it is **not** a SHA-256 implementation or real-firmware test.
The size-mismatch case deliberately makes that stub return the profile digest
for a shortened synthetic file to independently exercise the size check.
Real CommonCrypto is tested separately by native CI in `verify-file` mode,
which never opens IOKit. Host tests cannot prove firmware execution, target
memory ownership, correct target IP selection or acceleration.

Run `41146858706`, code `ccd95b5`, passed the Linux source job: 121 Python
tests, all 114 actual-CLI sequence cases, the existing 60 firmware-control
cases and 69 PSP-method cases, with ASan/UBSan enabled for the C/C++ suites.
The sequence report's event order/byte totals were independently rechecked;
its actual CLI hash was compared to freshly staged LF source and its patch
and shared-header hashes to the corresponding Git objects. See
`validation/ci-ccd95b5-sequence.json`. Native compilation preflight also passed
in job `124374016775`; its full native build is still running and is not counted
as a pass. No target hardware experiment follows from these host results.
