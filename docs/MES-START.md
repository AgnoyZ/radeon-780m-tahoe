# Firmware-profile MES start: hardware execution unverified

Patch `0014-profile-mes-start.patch` replaces the actual `mesboot mes` command's
single hardcoded instruction entrypoint with independently generated scheduler
and KIQ metadata. It checks the existing GART mapping before resetting MES,
checks both programmed entrypoints before activation, and bounds control-state
polling. It does not submit a scheduler packet or prove firmware execution.

## Metadata and source

`firmware_manifest.py` derives the 64-bit MES instruction start from little-endian
header words at byte offsets 56 and 60, after checking the whole-file hash,
size, header/IP version and component bounds. Zero and unaligned values fail.
The existing nine local firmware files were re-inspected; their identities and
component metadata are unchanged. The revised audit records only additional
MES start metadata and the current parser hash. No firmware bytes are published.

`firmware_profile.py` binds pipe 0 to `gc_11_0_1_mes_2.bin` and pipe 1 to
`gc_11_0_1_mes1.bin`, rejecting missing/invalid start metadata. The generated
`phxFirmwareMes` array retains the per-pipe file index and 64-bit instruction
address. Both reviewed files currently encode `0xfffffffff0005000`; this
coincidence is not a reason to share a hardcoded PC. Header generation and tests
also cover distinct addresses. The existing source provenance hashes the
generated profile, including these new fields.

Linux commit `7d0a66e4bb9081d75c82ec4957c50034cb0ea449` was inspected for the
MES v1 header, per-pipe filename selection, `uc_start_addr >> 2`, reset/activate
ordering and register masks. `validation/linux-mes-start-reference.json`
records the reviewed source hashes. AMD MIT-style notices were inspected;
validation and tests are independently written, and no full Linux bodies or
headers are copied into the implementation.

## Actual command

```text
mesboot mes <virtual-base> <mapped-bytes> <table-offset> <default-page-offset>
```

These are the explicit parameters used by the preceding successful GART setup,
not an instruction to choose arbitrary addresses. Argument-free `mes` now fails
before service lookup. The command:

1. Validates arguments and both generated entrypoints; rejects enabled
   `PTE_SYS`, `FAULT_DEFAULT` and `MESBOOT_MC` overrides before opening IOKit.
2. Uses one ABI-checked connection and selector 116; requires valid PSP/TMR
   metadata, no adopted GPU queue or PSP fault, and a fitting GART layout.
3. Requires CP/RLC boot-readiness observations, twelve matching GART address
   registers, flat/enabled context 0, first/last PTEs, first padding entry when
   present, and the default-page prefix. These checks share the actual GART
   command's readback helpers without changing its sequence.
4. Rejects any of the four active MES pipe bits, all-ones control reads, or a
   nonzero GRBM selection before the first register write.
5. Sets pipe 0/1 reset bits while retaining the initial control value. Selects
   each pipe, checks selection, writes its own shifted PC low/high words and
   checks both readbacks. Checks restored idle selection before activation.
6. Writes the two-pipe activation value, requests a 500-us initial delay and
   checks active/reset/halt fields for at most 1000 samples, requesting 1-ms
   delays after incomplete samples. All ones, transport/shape failures, delay
   errors other than EINTR, timeout and close errors terminate with failure.
7. Reports only programmed entrypoints and activation register observations,
   explicitly leaving scheduler execution unverified.

## Verification and limits

The actual staged CLI is included in `tests/test_mes_start.c`. The harness checks
the register-write sequence, preservation of the initial halt bit during reset,
per-pipe bank selection and address words. Two builds run every case: one with
the audited metadata and one substituting distinct synthetic 64-bit entrypoints.
Cases cover all nine register writes, all 25 reads on immediate completion,
both entrypoint readbacks, GART prerequisites, all four VRAM reads, wrong pipe,
stuck reset/halt, all ones, delayed/absent activation, EINTR and close failures.
No VRAM writes, doorbells, adoption calls or scheduler submissions are accepted
by this harness. Python checks validate termination accounting and false-success
rejection.

Run `41151681907`, code `17763be`, passed 145 Python tests and all 212 MES
actual-CLI cases under ASan/UBSan, plus 319 GART, 76 kernel-method, 114 firmware
sequence and 158 GFX-power regression cases. All MES/GART operation counts and
case sets were independently checked; CLI/kernel method hashes match the staged
source and all fourteen patch/six shared-header hashes match the exact Git
commit. Evidence: `validation/ci-17763be-mes-start.json`.

Native job `124389642450` passed the real-tool compilation/preflight step.
That observation comes from job-step metadata, not native artifact hashes.
The full native build is still running; no full-build pass is claimed here.

This still needs target validation. Snapshot and readback checks do not acquire
exclusive hardware ownership or prevent concurrent raw-debug clients. They do
not prove the resident firmware matches the generated metadata, that all GART
entries translate correctly, or that the firmware has executed any instruction.
The control register can echo activation without scheduler progress. Partial
failures have no automatic rollback; re-running after an error is unsupported.
Legacy queue/MQD/scratch offsets remain unresolved and must not be automatically
chained after this command. No deployment or working-EFI change is performed.
