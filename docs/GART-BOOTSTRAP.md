# Explicit GART bootstrap: target ownership still required

Patch `0013-explicit-gart-bootstrap.patch` replaces the actual `mesboot gart`
path's reference-machine physical/MC addresses with a kernel memory snapshot
and explicit virtual/table/default-page arguments. It implements a candidate
VMID-0 mapping of the beginning of VRAM, not a general GTT allocator. It has
not executed on the target GPU.

## Kernel snapshot

Privileged/debug selector 116 returns `PhxBootMemory`, a 128-byte structure
defined in `src/PhxBootMemory.h`. It accepts no scalar/structure input and
returns no scalar output. The first eight 64-bit words contain version (1),
flags, MC base, backing physical base, VRAM size, BAR0 aperture length, actual
managed TMR size and a reserved zero word. The last 64 bytes contain the
configured PSP descriptor. Flags are configured=1, ring active=2, TMR active=4,
GPU queue adopted=8 and PSP faulted=16.

`PhxBringup::bootMemory` takes the GPU lock then the SMU lock, matching layout
configuration. It copies software state without MMIO reads, memory writes,
allocation or PSP commands. Missing configuration/locks fails with zeroed
output. The handler checks privilege/debug gates, exact structure size and
the output pointer. Fault/active flags are reported, not silently cleared.

This reports startup geometry/configured extents, not ownership or an exclusive
transaction across later calls. It does not reserve firmware/display/console
memory or exclude concurrent raw-debug mutations by another client.

## Actual GART command

```text
mesboot gart <virtual-base> <mapped-bytes> <table-offset> <default-page-offset>
```

Offsets are VRAM-relative bytes. No MC/backing/default physical address is
taken from a reference-machine default. Argument-free `gart` and combined
`all` now fail before opening IOKit. Other legacy MES/queue experiments still
have reference assumptions and are not a supported automatic continuation.

1. Parse strict unsigned arguments before service lookup. Reject malformed,
   zero-size, unaligned/out-of-width spans and enabled `PTE_SYS`/`FAULT_DEFAULT`
   legacy overrides.
2. Open the service/ABI handshake and get selector 116. Require exactly the
   configured/ring/TMR flags, no adopted queues or PSP fault, a positive fitting
   TMR and a valid PSP layout.
3. Check 48-bit virtual/MC/physical spans, exact system-aperture granularity,
   virtual/MC disjointness, mapping size
   within VRAM, and table/default-page bounds within VRAM and BAR0. Enforce the
   existing write selector's 32-bit offset limit. Both write regions must be
   disjoint from each other and the full PSP ring/TMR/staging extents.
4. Require CP_STAT zero, RLC completion (excluding all ones), and all sixteen
   GPUVM contexts disabled before the first memory write.
5. Derive local-VRAM PTEs from the reported physical base. Fill the page-rounded
   table, zero its unused entries and one explicit default page. Read back the
   first/last PTE, first padding entry when present and default-page prefix
   before programming registers.
6. Derive table base, virtual bounds, system aperture and both default-page
   register pairs. Preserve the pinned reference's remaining register sequence;
   these settings still require target validation.
7. Check twelve address-register readbacks and flat/enabled context-zero mode.
   Submit engine-17 invalidation and require the context-zero acknowledgement
   bit, rejecting all ones and stopping after 1000 incomplete samples. The
   requested delay is 1 ms: a polling bound, not a guarantee to interrupt a
   stalled synchronous kernel request. Delay errors stop; interrupted delays
   return to the bounded loop.
8. Check service close and report only address/readback/invalidation completion,
   explicitly leaving GPU execution unverified.

The prototype caps this bootstrap mapping at 128 MiB, matching the former fixed
mapping size, but now permits smaller explicit mappings. This does not claim
the GPU has only that much VRAM or cap the separate per-process GPUVM design.
The allocator and queue layout must ultimately own and propagate their regions.

## Reference and limitations

Linux commit `7d0a66e4bb9081d75c82ec4957c50034cb0ea449`,
`drivers/gpu/drm/amd/amdgpu/gfxhub_v3_0.c`, was reviewed for VM page-table
bounds (`>>12`, `>>44`), system-aperture (`>>18`) and default-page physical
address (`>>12`, `>>44`) encoding. Field widths were checked against the same
commit's `gc_11_0_0_sh_mask.h`. The AMD MIT-style notices were inspected.
This changes the pinned nullarc implementation with independently written
validation; no Linux bodies/whole headers were copied. Source hashes are in
`validation/linux-gart-reference.json`.

Using a common zeroed VRAM default page is a candidate physical-address mapping,
not hardware-validated behavior. Fixed GC segment bases and remaining cache,
TLB and context settings still need target IP review. Existing kernel-start
code supplies the reported geometry.

There is no allocator, ownership grant, GPU reset, retry after error, deployment
or security change. Errors leave partial memory/register state without rollback.
An invalidation failure must not be followed by MES initialization or adoption.
Do not deploy before target firmware/display reservations and exclusive region
ownership are resolved.

## Host verification

Seven new kernel snapshot cases cover no mutation, locking, flags and zeroed
failure output (76 PSP-method cases total). The actual GART CLI harness checks
synthetic metadata, every table/default-page word, relocated high address bits,
overlaps, bad readbacks, failure at all 188 register writes and each read
boundary, and delayed/wrong/missing invalidation acknowledgement. Its 319 cases
use fake memory/registers; they do not emulate GPU translation.

Both new header hashes are recorded in source provenance. Local Python tests
pass (136). Native preflight compiles the real tool without running it; CI
sanitizer/native results must be recorded for this revision when available.
Older build passes are not evidence for this new initializer.

Initial source run `41150258701` (`b8f9883`) passed Python and prior suites,
including all 76 actual kernel-method cases, but stopped in the new GART
harness on `hello-abi`. The actual tool already closes an incompatible ABI
connection; the fake close function incorrectly required a completed GART
sequence. The harness now asserts that this early close happens exactly once
with no snapshot, register or memory access. This fixes the test's model, not
the tool's ABI behavior. The initial run is not a GART suite pass.
