# Explicit compute-ring probe: shader execution remains unverified

Patch `0016-explicit-compute-ring-probe.patch` extends the explicit scheduler
bootstrap through a real `ADD_QUEUE` packet and a candidate compute-ring
`WRITE_DATA` / 64-bit `RELEASE_MEM` sequence. All addresses derive from the
supplied layouts and checked kernel metadata. No GPU has executed this change.

```text
mesboot compute-probe <virtual-base> <mapped-bytes> <table-offset> <default-page-offset> <scheduler-arena> <scheduler-doorbell> <compute-arena> <compute-doorbell>
```

This command performs scheduler setup itself, on one ABI-checked connection.
It needs the preceding GART/MES setup and an inactive scheduler/compute HQD;
it is not a continuation of an already-running `sched-query`. Existing active
queues are refused. There is no automatic reset, retry or rollback.

## Layout

The scheduler retains its four-page arena. The compute probe requires five
separate pages: ring, writeback, MQD, EOP, and results/fence. Both whole arenas
must fit the mapped VRAM prefix, CPU aperture and 32-bit write-offset limit.
They must not overlap each other, PSP ring/TMR/staging, or the GART table/default
page. Their even, field-fitting doorbell indices must differ. The fifth page is
included in every overlap/bounds check, not just the MQD/ring pages.

The shared `PhxMesQueueLayout.h` now has a size-aware arena validator; the old
four-page scheduler wrapper keeps its contract. This describes geometry, not
allocation or ownership. Actual doorbell aperture limits remain enforced on
kernel writes; reservations and exclusivity are still unresolved.

## Execution path

1. Validate all arguments before lookup, then both layouts against the same
   kernel snapshot. Check existing readiness/GART state and all nine arena PTEs.
2. Check inactive scheduler and compute HQDs in their selected banks, restoring
   selection after each check, before any arena memory writes.
3. Initialize/query the scheduler as before. Clear the full compute arena and
   populate its MQD from explicit virtual addresses and doorbell index.
4. Submit `ADD_QUEUE` for the pinned path's legacy compute queue (ME1/pipe0/
   queue0 assumption). Require both MES completion values before continuing.
5. Use the same parameterized HQD readback helper for scheduler and compute:
   selected bank, active/VMID, MQD/ring/writeback address pairs, doorbell and
   queue-control fields must match before the work doorbell.
6. Initialize the output to the complement of a public test pattern, surround
   it with 64-bit guards, and initialize the release fence to the complement
   of a public, nonzero-high-word completion value.
7. Submit a 13-dword ring: `WRITE_DATA` writes the pattern through the explicit
   GART virtual address; `RELEASE_MEM` uses the reported MC base plus the specified
   fence offset, matching the existing kernel submission convention. Write the
   full pointer shadow before the compute doorbell.
8. Require the full 64-bit release value within 400 polling samples, with
   requested 5-ms delays. Re-read the fence and require the exact result and
   both guards. Delay errors other than EINTR, transport/shape errors and bad
   observations stop. Check close before printing the success marker.

This is a command-processor memory-write test, not an ALU shader dispatch.
Even successful target execution would establish only these queue/mapping/
write/fence observations. It would not establish user GPUVM, shader execution,
Metal rendering, scan-out or WindowServer acceleration. No queue adoption or
accelerator claim occurs. The arenas remain live device resources after exit;
they cannot be reclaimed merely because the process closed its connection.

## Source and host checks

Linux `7d0a66e4bb9081d75c82ec4957c50034cb0ea449` was inspected for the
`WRITE_DATA` memory-test packet and `gfx_v11_0_ring_emit_fence` sequence.
`nvd.h` and `navi10_enum.h` confirm the packet opcodes, write-confirm bit,
cache/release flags and event value. Reviewed hashes/notices and derived words
are in `validation/linux-compute-probe-reference.json`. Validation is independently
written; no Linux implementation bodies are copied into the patch.

The existing actual-CLI harness now has a separately compiled compute mode.
Its two fake register banks, disjoint arenas and injected firmware effects
check `ADD_QUEUE`, MQD and both GPU address forms, the exact 13 packet words,
complement initialization and guards. Baseline/relocated runs cover high address
bits and different doorbells. Failures include fifth-page overlap, shared
doorbell, active HQD, every immediate-path register operation, memory-stage
boundaries, failed MES add completion, missing writes, each fence half, changed
fence/guards, delayed completion, sleep errors and close errors.

Run `41153999930`, code `c239fa2`, passed 155 Python tests and all 558
compute-mode actual-CLI cases under ASan/UBSan (279 per address-layout variant).
The same source passed 366 scheduler, 212 MES-start, 319 GART, 76 kernel-method,
114 firmware-sequence and 158 GFX-power regression cases. All 1455 CLI operation
counts/case sets, actual CLI/kernel method hashes, and sixteen-patch/seven-header
Git input hashes were independently checked. See
`validation/ci-c239fa2-compute-ring.json`.

Native job `124396895811` passed real-tool compilation/preflight according to
job-step metadata. Full native build and native artifact hashes are not yet
verified for this revision. None of the synthetic tests executes firmware,
command processors or shaders.

Exclusive memory/doorbell ownership, firmware residency, target topology and
cache/address semantics still require hardware evidence. Synchronous kernel
calls can stall beyond the requested polling delays. No deployment, working
EFI, disk, BIOS, NVRAM or OS-security change is performed.
