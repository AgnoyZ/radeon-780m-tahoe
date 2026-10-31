# Checked walks through map cleanup and BO lifetime

Patch `0023-checked-walk-cleanup.patch` connects the checked page-table walker to
actual kernel mapping and client buffer retirement. It does not enable hardware,
alter the userspace ABI or establish GPU execution.

## Failure being corrected

The original pointer-only walker returned null for both a legitimately absent
branch and a malformed/unreadable tree. Unmap skipped null entries and could
return success after invalidation, allowing the client to discard its map record
and release backing even though the purported cleanup was not established.
Failed-map rollback similarly skipped an unreadable leaf and subsequently reset
its cleanup-required flag.

## Status and ownership

The internal walker now optionally returns an `IOReturn` in addition to its
pointer. Null plus Success means a known absent branch; NoMemory describes
capacity/allocation failure; VMError describes a malformed or unreadable walk.
The pointer result alone remains available for existing internal consumers, but
map, rollback and unmap require and check the explicit status.

Mapping preflights the full range before writes. An unreadable tree or a nonzero
invalid leaf retains the provisional map as pending even before new leaves were
exposed, preventing subsequent client submissions from ignoring the corruption.
Ordinary validation failures and clean allocation failures still discard only
the new provisional metadata. A valid occupied leaf is refused without changing
that entry. Construction also rechecks occupancy after allocation.

Rollback clears only this transaction's written prefix when its actual walker
resolves the leaf and its value exactly matches the currently checked descriptor
physical segment plus the driver's existing flags. Missing/corrupt walks,
changed leaf values and unavailable/changed segments leave cleanup pending rather
than being silently accepted. Successful invalidation alone cannot erase that
uncertainty or the retained association.

Unmap validates every page and the driver's exact nonzero physical leaf encoding
before mutation. A malformed later branch cannot cause earlier leaves to be
cleared in that preflight pass. The mutation pass rechecks walks and encodings;
if injected state changes occur, any partial changes still reach the existing
selected-VMID invalidation path and the operation returns an error. Explicit
unmap VMError now marks the client map pending, as Timeout already did.

The existing client reaper preserves map records, BO slots, pool charges,
descriptors and host prepare ownership until unmap actually succeeds. Pending
maps cannot cover an IB or authorize new submissions. A repaired tree can be
cleaned on retry; no repair of an unknown hardware state is performed by this
patch. A genuinely absent branch remains idempotent after the existing checked
invalidation. Whole-context retirement remains a separate operation.

## Integration tests and limits

`tools/test_vm_walk_cleanup.py` stages the locked patched source and extracts the
actual allocator/backing/walker methods together with actual map/unmap, client
mapping, logical free, reaping, coverage and submission methods. It hashes their
source and the shared declarations. Unlike the separate BO harness's explicit
flat-map fake, this harness traverses the actual multi-level tables.

Its 55 cases cover healthy mapping, unmap/free, capacity and partial allocation
failure, eleven tree corruptions, malformed leaves, a later corrupt branch,
state changes during construction/clear, rollback identity/segment failures,
invalidation timeout/retry, host pin retention and refusing submission while a
corrupt mapping remains pending. The existing 98 page-table and 82 BO cases
remain separate regressions; their historical passes do not validate this patch.

The Windows Python suite passed 212 tests: 204 executed successfully and eight
POSIX-only checks explicitly skipped. Source extraction, malformed/duplicate
source rejection, strict result parsing and actual-walker/CI wiring are covered.
The new C++ cases are not yet executed at implementation time on this Windows
host; the source CI result and full native macOS build must be checked after
synchronization. OS allocation, descriptors, physical segments, cache flushes,
registers, locks, completion and submission transport remain explicit fakes.
State changes are fault injection, not proof of a real concurrent hardware race.
No GPU command, kernel loading, DMA/IOMMU coherence, full page-table graph audit,
target GPUVM initialization, Metal or display result is established.

No driver, EFI, firmware, NVRAM, security setting or disk is changed. Source
rollback uses a new commit and preserves the prior ownership/retirement guards;
this document is not a deployment procedure.
