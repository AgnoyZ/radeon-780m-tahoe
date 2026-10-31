# Explicit scheduler queue: target ownership and execution unverified

Patch `0015-explicit-scheduler-queue.patch` adds an actual `mesboot sched-query`
path with explicit GART parameters, a scheduler arena offset and a doorbell
index. It relocates the existing MQD/HQD, resource packet and completion path
together. It does not allocate or claim ownership of the selected memory.

```text
mesboot sched-query <virtual-base> <mapped-bytes> <table-offset> <default-page-offset> <arena-offset> <doorbell-index>
```

All offsets are VRAM-relative bytes; the doorbell index is in dwords, must be
even for the existing 64-bit write selector and must fit the 26-bit register
field. No new command argument has a reference-machine default. Actual doorbell
aperture bounds are still checked by the kernel on write, not known by this
metadata ABI before initialization; index ownership remains unverified.

## Layout and execution

`PhxMesQueueLayout.h` defines an explicit, page-aligned 16-KiB arena:

| Relative bytes | Purpose | Initialized extent |
| --- | --- | --- |
| `0x0000` | Scheduler ring | 4096 bytes / 1024 dwords |
| `0x1000` | Read/write pointers, completion and firmware context slots | Full 4096-byte page |
| `0x2000` | MQD | Full page zeroed; existing 2048-byte MQD populated |
| `0x3000` | EOP | Full page zeroed; existing descriptor uses 2048 bytes |

Validation requires a valid bootstrap snapshot/GART contract and places the
whole arena inside the mapped VRAM prefix, CPU aperture and 32-bit write-offset
limit. It must be disjoint from the GART table/default page and full PSP
ring/TMR/staging capacities. Adjacent non-overlapping spans are permitted.

Before memory writes the actual command checks CP/RLC observations, the GART
address registers and table endpoint/default readbacks, and all four arena PTEs
against the reported backing physical addresses. It requires both MES pipes
active with no reset/halt bits and idle GRBM selection, then selects the
scheduler bank and rejects an already active/all-ones HQD. GRBM selection is
restored and checked. Selection writes themselves are not a hardware lease.

The command then installs the explicit arena addresses and virtual base in the
existing scheduler helpers, clears the four pages and initializes the MQD/HQD.
It checks the HQD active/VMID, MQD/ring/report/poll address pairs, doorbell field
and queue control before the first doorbell. It sends `SET_HW_RESOURCES` then
`QUERY_SCHEDULER_STATUS`, using the established full-width completion-fence and
status checks. Either failure prevents the next submission and final success.
The completion wait now also rejects sleep errors other than EINTR. Close is
checked. No compute/gfx queue is submitted or adopted by this command.

Legacy scheduler helper defaults are preserved for existing experiments and
tests; only `sched-query` installs the validated explicit layout. It rejects
legacy mapping, compute/gfx and adoption environment overrides. This is not
permission to chain old `sched`, `gfx`, `kiqsched`, `claim` or adoption commands.

## Source and verification

The pinned Linux MES queue register initialization, MQD address encodings,
doorbell field and resource-packet address fields were inspected. References
and their AMD MIT-style notices are recorded in
`validation/linux-mes-queue-reference.json`. Existing register defaults,
resource masks and IP base arrays are retained from the pinned nullarc path;
they are candidates requiring target topology/firmware review, not discovered
hardware capabilities. No full Linux source bodies/headers are copied.

The harness includes the actual staged CLI and supplies a fake register bank,
16-KiB arena and injected completion writes. It checks every memory write stays
in that arena, initial clearing, MQD addresses, doorbell index, resource/fence
packet addresses and the two submission order. Baseline and relocated variants
use different virtual/physical high bits, arena offsets and doorbell indices.
Tests cover layout overlaps/bounds, four arena PTEs, all register operations on
the immediate-success path, write-stage boundaries, HQD readbacks, bad/high-word
completion tokens, timeout, delay and close failures. Header checks include
exact-end/adjacent ranges and doorbell field limits.

Local Python checks pass (150); 366 actual-CLI sanitizer cases are wired into
CI. Exact-revision source and native results are pending and must be recorded
before claiming a host verification pass for this patch.

## Remaining work

Exclusive allocation/ownership is still missing: firmware, display, console,
other clients and doorbell reservations are not established by arithmetic
checks or CPU readbacks. Concurrent raw-debug mutation is not excluded. Any
error can leave partial state; there is no rollback or automatic retry.
Actual firmware residency, GART translation, MES packet compatibility and
hardware completion remain unverified. Even genuine scheduler completion would
not prove compute, graphics, display or Metal acceleration. No working EFI,
device installation, BIOS, NVRAM or OS security setting is changed here.
