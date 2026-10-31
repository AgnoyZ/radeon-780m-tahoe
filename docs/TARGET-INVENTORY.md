# Target metadata collection: no driver installation

For Recovery without Python, use the native capture/offline import route below.
The existing direct Python route keeps its original in-memory privacy behavior.

This is the first, read-only metadata step toward target bring-up, not a GPU test
or a complete memory-ownership audit. It does not load a kext, open the experimental
IOKit user client, submit commands, write registers, run `diskutil`, change NVRAM,
modify security settings, partition disks or install anything. It writes only a
new local report directory. Do not run `mesboot` or copy experimental kexts to EFI.

## Run on the target, using an already installed Python 3

Run this on **Intel macOS**, ideally after the owner has independently completed
the planned Tahoe migration and recovery-path checks. It can record an older
Intel macOS baseline too, but will not label that as matching the Tahoe target.
It deliberately refuses Windows and ARM Macs. Do not assume Recovery has Python;
if Python is unavailable, report that limitation rather than installing tools or
altering the boot environment as part of this collection step.

From the repository directory:

```sh
python3 tools/target_inventory.py --out local/target-inventory-01
```

The script uses only Python's standard library. Alternatively copy just
`tools/target_inventory.py` into an ordinary data directory on the Mac, not an EFI
startup directory, and run:

```sh
python3 target_inventory.py --out target-inventory-01
```

No `sudo` is needed. Existing output directories are refused; use a different
name for another collection. The local result is `inventory.json`. Review it
before sharing, keep it out of the public repository, and provide it privately
for the next hardware comparison. The repository ignores this filename.

## What the report means

- Observed product version, build, Darwin release, CPU architecture and total RAM.
  RAM is not reclassified as usable graphics memory.
- Number of PCI roots examined, unreadable identities and exact registry matches
  for `1002:1900`. Missing and multiple matches are explicit, not guessed away.
- For matching candidates only: numeric class/revision/subsystem properties and
  any valid registry-reported assigned-address range bases and lengths. These are
  machine-specific metadata and should remain private until manually reviewed.
- Missing/malformed properties stay unknown with warnings. No default address,
  zero-memory fallback, reference-laptop layout or synthetic target is inserted.
- The collector source hash identifies the script version used.

Names, registry paths/IDs, serial numbers, UUID/ROM properties, arbitrary nested
properties, firmware and raw IORegistry/stdout/stderr are not saved. Each fixed
metadata command has a 20-second timeout; failed or malformed collection does not
produce a success report. Registry traversal is depth-limited, and each captured
stdout is checked against a 16 MiB limit before parsing. Subprocess output is
buffered in memory until completion or timeout; this is not a streaming memory
limit. The output requests
owner-only directory/file modes (0700/0600) on macOS; review the storage location
and any inherited access controls before sharing.

`safe_to_initialize`, `physical_identity_verified`,
`reserved_region_ownership_verified` and `gpu_work_submitted` remain false.
Registry properties may be injected/spoofed; assigned PCI apertures do not prove
backed VRAM, free regions, console/firmware reservations or exclusive ownership.
Even a single matching registry identity on Darwin 25 is **not approval to load
the driver or execute a bring-up sequence**. GPU IP discovery, firmware review,
memory ownership, target initialization and actual GPU output remain separate.

## Parser basis and validation limits

Apple's `ioreg` manual specifies XML output (`-a`), class matching (`-c`), matching
subtree roots (`-r`), and root-only traversal at depth one (`-d 1`).
Reference: `apple-oss-distributions/IOKitTools`, commit
`e6f4aac8b42e65f7e76009227de1d05057228488`, `ioreg.tproj/ioreg.8`.

The PCI numeric-property and assigned-address parser follows Intel field layout
in Apple's `IOPCIConfigurator.cpp` (`constructAddressingProperties` and
`constructProperties`) and `IOKit/pci/IOPCIDevice.h` (`IOPCIPhysicalAddress` and
`IOPCIAddressSpace`), at `apple-oss-distributions/IOPCIFamily` commit
`4822b27a36e2de70e231ecf2bf3021384fab6ec2`. Intel and non-Intel structure layouts
differ, hence the Intel-only capture gate. These source references explain the
parser; they do not prove the target's installed driver uses those exact sources.
The pinned source was reviewed directly: the configurator serializes native
structures with `appendBytes`, writes numeric identities as four-byte `OSData`,
and the Intel structure orders high/low address and length words as parsed here.
No Apple source code is copied into this collector.

Tests use synthetic PCI data and check privacy exclusions, missing/ambiguous
matches, malformed types, range overflow/duplicates, timeouts and host refusal.
Native CI additionally invokes the collector on its own non-target Intel Mac,
logging only system metadata and aggregate counts, never candidate addresses or
raw registry data. A CI inventory is not the user's target inventory. The native
preflight containing this collector passed run `41096096384`, code `ff3345a`, at
`2026-10-30T17:08:40Z` (October 31 in Asia/Shanghai). The step result is preserved
in `validation/ci-ff3345a-submission.json`; its detailed host metadata has not yet
been extracted from the still-running native job. Target data is still missing.

## Recovery without Python: native capture, offline import

`tools/recovery_inventory.sh` uses only the fixed native metadata commands listed
above, plus `uname`, shell builtins and ordinary file/timeout helpers. It does
not need Python, sudo or any installed experimental driver. It refuses non-macOS
and ARM hosts. Availability of these native commands in the user's actual
Recovery remains to be observed; missing commands fail rather than installing
anything or inventing values.

Copy the script to an ordinary writable data directory on the USB drive, outside
the EFI partition. From that data directory in Recovery Terminal, run:

```sh
/bin/sh recovery_inventory.sh recovery-capture-01
```

The output directory must be new and its parent must already exist. Spaces in
paths are supported. Every file is private (umask 077), and a local `.gitignore`
excludes all capture contents. Each fixed command writes its own output, stderr
and exit status. A private completion marker is written only after all five
commands exit successfully with nonempty bounded outputs. The script requests
termination after 20 seconds per command and restricts per-process file sizes;
it cannot guarantee interruption of a stuck kernel request. It controls only
the child command and timeout helper it started. Failed/interrupted output
remains an incomplete private capture, never an initialization success.

Unlike the direct Python route, **this directory contains raw PCI registry
properties and stderr**. It may contain identifiers. Keep the entire directory
private, do not post it on GitHub, and do not treat its completion marker as proof
of valid PCI data, target identity or memory ownership.

Copy the private directory back to the Windows data workspace. From this
repository, run with Python, replacing the quoted input path with its location:

```text
python tools/target_inventory.py --from-capture "<copied-capture-directory>" --out local/target-inventory-from-recovery-01
```

Import is offline and can run on Windows. It executes no commands from the
capture, checks the exact fixed file set and successful statuses, rejects linked,
missing, oversized or malformed inputs, and applies the same numeric/PCI whitelist
as direct capture. It writes only `inventory.json` to a new output directory;
original captures are neither changed nor copied into that report. The observed
OS/build remains explicit: a Sonoma Recovery capture is never relabeled Tahoe.
The report remains private metadata for manual review before any sharing.

Input hashes are computed when importing. They are not authenticated evidence
that the script ran unmodified on the reported host. `native_capture_source_verified`,
`physical_identity_verified`, `reserved_region_ownership_verified`,
`safe_to_initialize` and `gpu_work_submitted` remain false. Even a valid single
`1002:1900` match on Darwin 25 does not prove free VRAM, GPU IP revisions,
reservations, correct firmware selection, working queues or acceleration.

Windows tests exercise import, rejection and privacy without claiming native
shell execution. Linux CI executes the actual script with fixed native command
paths replaced by explicit synthetic fixtures, including timeout, failed status,
file-size limits and existing-output refusal. Intel macOS preflight additionally
runs the unchanged script with real Apple read commands and compares the imported
system fields with direct capture, logging only system metadata and aggregate
counts. These are hosted checks, not Recovery or target-laptop verification;
their observed results must be recorded separately after CI completes.

Run `41162066128`, code `8b91942`, passed all 200 Linux source tests with no skips.
All 18 new native-capture/import/preflight checks report success, including the
seven actual-script synthetic shell cases and the offline privacy/rejection
checks. Existing queue, BO, context, VM-binding and bring-up regressions also
passed; exact results, method/declaration hashes, operation counts and 28
patch/header inputs were independently checked. See
`validation/ci-8b91942-recovery-capture.json`.

GitHub step metadata confirms successful real Intel-macOS preflight in native
job `124421788912`, including unchanged native capture and offline import.
The detailed capture JSON/host fields have not been independently extracted
while the full job runs. This is neither a target-laptop capture nor a Recovery
environment pass; no new target data or GPU initialization evidence exists.
