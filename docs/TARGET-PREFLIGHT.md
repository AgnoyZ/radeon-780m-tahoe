# Target preflight: check-only gate

`tools/target_preflight.py` converts a private `inventory.json` into a bounded,
private checklist for the next manual target step. It never opens IOKit, loads a
kext, writes EFI/NVRAM, changes disks, initializes firmware or submits GPU work.

After importing a Recovery capture on Windows, run:

```text
python tools/target_preflight.py local/target-inventory-from-recovery-01/inventory.json --out local/target-preflight-01
```

The output is `preflight.json` with mode `0600` on POSIX. Existing output is
refused. The report allows only the non-submitting `native-shader-probe --check`
step when it observes Intel x86_64 Darwin 25, exactly one `1002:1900` registry
candidate, nonempty assigned-address metadata, and no positive execution claims
in the source inventory. Missing, ambiguous, altered or unsafe metadata blocks
even that check.

This is a policy gate, not hardware proof. Assigned PCI ranges are not an
independent configuration-space read and do not prove VRAM, firmware residency,
UMA reservations, queue ownership or display state. The report always sets
`native_probe_run_allowed`, `safe_to_initialize`, `reserved_region_ownership_verified`
and `gpu_work_submitted` to false. A later, separately reviewed manual procedure
must run `native-shader-probe --check` first; `--run` remains prohibited until
target firmware, GPUVM, queue ownership and recovery are independently verified.
