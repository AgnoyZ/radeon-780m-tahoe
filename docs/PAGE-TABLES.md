# Owned page-table backing and walks

Patch `0022-checked-page-table-backing.patch` extends the actual kernel allocator,
lookup, walker and context-allocation methods. It is source implementation, not a
target GPUVM or acceleration result.

## Allocation and publication

- Require the requested 64 KiB descriptor length, non-null page-aligned CPU
  storage, a non-wrapping CPU extent, and one full physical segment obtained with
  `kIOMemoryMapperNone`.
- Require a nonzero page-aligned physical base and the entire chunk to fit the
  existing 48-bit page-table address mask. Contiguous allocation flags alone do
  not establish this checked extent.
- Check context capacity and allocation order, missing predecessor chunks,
  stale cached bases, holes, and physical/CPU overlap with cached chunks.
- A failed fresh descriptor is released before publication. A failed cached
  descriptor remains owned; it is neither released nor silently replaced.
- Clear and flush the whole fresh chunk before publishing its physical base
  and descriptor. Retrieving a cached table does not zero it again.
- Context allocation revalidates cached roots before setting `busy`. An invalid
  root does not prevent trying another free context.

These are driver-owned host-memory checks. They do not establish actual IOMMU
translation, DMA coherence, firmware reservations or exclusive GPU ownership.
Descriptor and CPU mappings are assumed stable for the owned descriptor lifetime.

## Lookup and walks

- CPU table lookup accepts a whole aligned page only within `used` tables,
  validates each used chunk's backing and cached physical address, and rejects
  ambiguous physical matches. Unused pages within an allocated chunk are not
  valid child-table addresses.
- The root must match chunk zero. Virtual addresses passed to this internal
  walker must fit its existing 48-bit address space.
- An empty directory entry is exactly zero. Nonzero invalid entries are refused
  rather than overwritten. Owned non-leaf entries must use exactly the existing
  `VALID|SYSTEM|SNOOPED` flags (`7`), with no large-page or reserved flags.
- Ancestor references are refused at every level. Child pointers must resolve
  through the owned, used-table lookup before a CPU dereference.
- A partial walk may retain newly linked empty tables when a later allocation
  fails. It does not decrement `used`, release already published backing, or
  discard existing entries; a later retry can continue through those tables.

This is not a complete graph/provenance audit of every page-table entry or all
kernel lifetime paths. The prior deferred-reclamation and queue-retirement
requirements remain in force. No hardware flags or boot enablement are changed.

## Verification and limits

`tools/test_page_tables.py` extracts the actual four methods and backing helper
from a freshly patched source stage, plus their constants and `VmCtx` definition.
It hashes the extracted source and declarations and runs 98 cases through
`tests/test_page_tables.cpp` under POSIX Clang ASan/UBSan in CI.

Cases cover fresh/cached allocations, zero/short/overflowing CPU and physical
backing, physical/CPU aliases, allocation failure and publication ordering,
cached-root reuse/refusal, lookup boundaries, unused/foreign children, malformed
directory flags, ancestor cycles and retry after a partially linked walk.

The Windows suite passed 206 tests (198 executed successfully, eight explicit
POSIX-only skips). Its runner tests validate source extraction, missing/duplicate rejection,
strict result parsing, CI wiring and refusal to claim native execution on Windows.
At implementation time no local POSIX C++ compiler was available. The 98 C++
cases are **not yet executed or claimed passed**; their CI result must be checked
after synchronization. Earlier successful native builds predate patch 0022.

The harness explicitly fakes IOKit descriptors, physical segments, storage,
cache flushes, locks, readiness and context reaping. It performs no GPU execution,
loads no kext and does not establish target initialization, Metal or scanout.

## Deployment and rollback

No EFI, installed driver, NVRAM or disk layout is modified. This source patch is
not a boot/deployment instruction. Revert its patch-list entry and related source
change in a new commit if a verified regression is found; keep the earlier
retirement fixes and preserve existing history.
