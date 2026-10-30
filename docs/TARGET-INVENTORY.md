# Target metadata collection: no driver installation

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
