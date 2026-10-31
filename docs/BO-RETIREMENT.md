# Individual BO retirement and checked mapping

Patch `0020-deferred-bo-release-and-checked-unmap.patch` extends whole-client
retirement with deferred individual buffer release and checked map/unmap
transactions. These methods have not run on the target laptop. They do not
establish active-MES invalidation, real DMA safety or working acceleration.

## Logical free versus physical release

Freeing a valid buffer hides its handle immediately and marks its mappings for
cleanup. The handle slot, original descriptor, host prepare ownership and pool
charge remain occupied. Repeated free or lookup of that handle fails. Any pending
CPU-written user-fence metadata referencing that handle is cleared so later
completion cannot write through a reused handle.

The client reaper removes pending mappings only after successful kernel unmap.
It uses a fixed 512-byte mapped-handle bitmap, checks map-handle bounds and refuses
budget underflow. It releases a pending BO only when every alias is gone and its
context can be reclaimed. Host imports receive exactly their original complete
and release calls. A client with no VM context and no mappings can release its
never-submitted BO immediately.

Logical free returns success even when backing is retained. Explicit unmap
instead returns Busy before mutation if GPU work is outstanding. An invalidation
timeout returns Timeout and retains pending metadata. A completed, non-overlapping
unmap retry is idempotent; a partial overlap or another BO's mapping is rejected.

## Kernel transaction rules

Under the GPU lock, map/unmap requires a live non-closing context, observable
GPU readiness, retirement of its last submitted sequence, consistent slot/context
ownership and the existing binding-register readbacks. An uncertain peer slot
blocks changes and reclamation. Retrying invalidation can repair the current
slot, but cannot excuse an unrelated fault.

Mapping validates aligned, nonzero 48-bit VA and descriptor extents using
subtraction-based bounds. Before writing any leaf, it checks every physical
segment and rejects an existing valid PTE. It then rechecks physical segments
while constructing leaves. A partial failure clears only the leaves written by
this transaction; it never erases a conflicting pre-existing mapping. Empty
intermediate page-table allocations remain context-owned until whole-context
retirement.

Exposing or rolling back bound-context leaves requires the selected-VMID
invalidation ACK. A failed ACK marks the slot uncertain and returns an explicit
cleanup-required result. The client retains that VA and descriptor association
until a later successful unmap. Failures before exposure remove only the newly
reserved metadata. Mapping with unavailable GPU hardware no longer reports a
bookkeeping-only success.

Pending mappings cannot cover an indirect buffer or be reused by another map.
The client reaps before submission and refuses new work while cleanup is pending.
Other client methods and successful waits also trigger reaping. Closing a client
transfers its container, including pending-free BOs, through the existing
whole-context retirement path. Reclamation remains on-demand, without a timer.

## Validation and limits

`tools/test_bo_retirement.py` extracts and hashes the actual kernel map/unmap,
ownership/idle/retirement and client free/reaper/map/submission implementations.
The host harness supplies explicit fake descriptors, physical segments, page
allocation, MMIO, locks and downstream submission transport. Its cases cover
busy work, failed ACK and retry, multiple aliases, pool accounting, hidden
handles, user-fence cleanup, malformed spans, PTE collisions, partial rollback,
changed physical segments and submission blocking/resumption. The existing
context-retirement harness additionally exercises closing with pending-free BOs.

Windows passed all 176 Python integration/runner checks and Python syntax compilation.
Run `41159691075`, code `da5c999`, passed the Linux source job: all 82 actual-method
BO cases, 55 context-retirement cases, 71 VM-binding/submission cases and 73
queue-adoption cases passed under ASan/UBSan alongside existing regressions.
Independently checked the actual method/declaration hashes, exact outcomes,
1455 CLI operation-count dictionaries and all 20 patch plus seven shared-header
hashes against exact Git objects. See `validation/ci-da5c999-bo-retirement.json`.
Native macOS job `124414639905` remains in progress. Intel macOS compilation
and actual target execution are separate gates. The harness does not execute
real page wiring, the kernel allocator, DMA, concurrent clients or actual GPU
commands, and does not validate Tahoe, Metal, scanout or reset/unload.

No driver is installed or enabled by this change. No firmware, EFI, NVRAM,
security settings or disk layout changes are made. To compare source behavior,
use a separate clean checkout of the preceding revision and rebuild there; do
not remove retirement guards from a running instance or replace the working EFI.
