# Submission-time VMID validation

Patch `0018-checked-vmid-binding.patch` changes the actual kernel binding and
invalidation path used by `gpuSubmit`. It preserves the existing user VMIDs
8..15, page-table format and submission ABI. It does not install a driver,
take over a queue or claim successful target GPUVM execution.

## Implemented behavior

- `vmFlushTlb` returns a result instead of silently exhausting its wait. It
  rejects missing MMIO and VMIDs outside 8..15 before shifting or writing.
- The legacy GFXHUB request contains only the requested user VMID, plus the
  existing L1/L2 invalidation flags. It no longer also requests VMID 0.
- It accepts only the requested ACK bit, rejects all-ones reads, and takes at
  most 1000 samples with at most 999 requested one-microsecond delays. This is
  a bounded polling count, not a verified wall-clock timeout on the laptop.
- `vmBindingValid` reads back all seven programmed context registers: root
  low/high, context control, virtual-page start low/high and end low/high.
  The root must be nonzero, 4-KiB aligned and fit the existing physical-address
  mask. An unexpected value fails before requesting invalidation.
- `vmBind` checks context handles, cached hardware-VMID ownership, candidate
  victim indices/ownership and the LRU counter before indexing or changing the
  binding. It still reuses only a free slot or a retired LRU victim.
- Both first binding and cached reuse require matching registers and a
  successful invalidation. Cached reuse cannot bypass a prior failed request.
  A failed initial invalidation leaves a software reservation, not permission
  to submit. A retry must obtain a new successful acknowledgement.
- The existing real `gpuSubmit` branch returns Busy when binding returns zero.
  Tests execute that branch and verify no ring/writeback/doorbell writes,
  sequence allocation or submission publication occurs after binding failure.
  A successful retry executes the real INDIRECT_BUFFER/RELEASE_MEM emission.

## Reference audit

The pinned Linux source is `7d0a66e4bb9081d75c82ec4957c50034cb0ea449`.
`gfxhub_v3_0_get_invalidate_req` sets the selected VMID bit and L1/L2 flags;
the matching register header supplies the flag positions. `gmc_v11_0_flush_gpu_tlb`
documents the legacy engine-17 request/ACK path and uses firmware-mediated
invalidation when KIQ/MES is ready. File hashes and the limits of this comparison
are recorded in `validation/linux-vmid-binding-reference.json`.

This patch does **not** copy Linux's function bodies, claim its complete
invalidation protocol, or establish compatibility of the legacy direct-MMIO path
with active MES/GFXOFF on this laptop. A returned register bit is a checked
observation, not independent proof that hardware performed the intended
translation-cache operation. Integrating the active scheduler's invalidation
protocol remains necessary before target runtime claims.

## Validation

`tools/test_vm_binding.py` extracts the actual `vmFlushTlb`, `vmBindingValid`,
`vmBind`, `ringPut` and `gpuSubmit` methods, their constants and queue/context
structures from the patched source. Native CI compiles them with ASan/UBSan and
warnings-as-errors. Host fakes provide MMIO, mappings, locks, completion fences
and retirement observations; they are explicitly not GPU emulation.

The cases cover all eight VMIDs, invalid shifts/handles/roots, absent MMIO,
wrong/all-ones/late/missing ACKs, each register mismatch on first and cached
binding and actual submission, slot exhaustion, LRU/late retirement, inconsistent
ownership and retry after timeout. Successful submission checks the actual
12-dword packet, 64-bit writeback, doorbell and sequence. Failed submission
compares memory and doorbell snapshots and requires unchanged publication state.
Windows runs Python integration/runner tests only; native results are recorded
separately after CI completes.

Run `41156152909` / code `babba67` completed its Linux source job successfully:
165 Python tests and all 68 actual-method VM binding/submission sanitizer cases
passed, along with the 72 adoption cases and all earlier regression suites.
The five method hashes, extracted declarations, all binding/adoption outcomes,
1455 CLI operation-count dictionaries and 25 patch/header input hashes were
independently checked. See `validation/ci-babba67-vm-binding.json`. The macOS
job `124403616486` remains in progress; these results are not a native kext build
or a target GPUVM/shader/lifetime pass.

## Unresolved lifetime issues

This is submission-time binding validation, not a complete GPUVM lifetime fix.
`vmMap`, `vmUnmap` and `vmidFree` still discard their invalidation return value.
The submit path now independently revalidates before emitting work, but it does
not make unmapping/releasing resources safe while prior work remains in flight.

The audit also found `clientClose` releases BOs before waiting on the context;
`vmidFree` clears/recycles tables after its bounded wait even if work did not
retire; and `doBoFree` discards mapping records without ensuring PTE invalidation
or outstanding GPU completion. Fixing only call order or withholding a context
slot would still allow premature descriptor release/unpinning. A complete fix
must transfer ownership of BOs, host-page wiring and page tables to a deferred
retirement mechanism, propagate unmap failures, reclaim only after verified
retirement/invalidation, and define device-stop/reset behavior. No such deferred
reclamation or safe teardown is claimed by this patch.
