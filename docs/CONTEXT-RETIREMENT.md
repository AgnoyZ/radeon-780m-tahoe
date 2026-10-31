# Deferred client/context retirement

Patch `0019-deferred-client-context-retirement.patch` replaces the kernel's
timeout-then-clear `vmidFree` path and the client's release-before-wait close
path. It implements ownership transfer and on-demand reclamation for a **whole
closing client**. This is not yet a complete buffer lifetime, reset or unload
implementation, and it has not run on target hardware.

## Ownership and state transitions

Client initialization allocates a `PhxRetiredBuffers` container holding the
existing BO entries. That container owns the original memory-descriptor
references and the original host-import prepare calls. It is not a second copy
of the descriptors and does not introduce another prepare/complete pairing.

The close or final-free path sets `closed` while serialized with client methods,
then transfers the existing container to its VM context. It clears its local
aliases after transfer. Closing does not allocate a retirement node and does
not release or complete those descriptors. A client which never acquired a VM
context still uses immediate BO cleanup. Repeated close/free cannot transfer or
release the same container again. Memory export and wait completion refuse a
closed client before touching its former BO entries.

The kernel stores the last sequence on successful submission. Retirement uses
the larger of that value and the client's supplied last sequence; a client-side
zero cannot erase known outstanding work. Closing contexts remain busy and are
excluded from VM lookup, mapping, submission and allocation reuse.

| State | Progress condition | Retained resources |
| --- | --- | --- |
| Active | Client still owns its BO container | Client descriptors; kernel page tables |
| Closing, work pending | All required queue work must retire | Entire container, host-page wiring, page tables and slot |
| Closing, detach pending | Context-control disable readback and selected-VMID invalidation ACK must pass | Same resources; failed slot marked uncertain |
| Closing, ownership uncertain | Every hardware-slot/context association must be consistent and non-faulted | No table or buffer reclamation |
| Reclaimed | Required work retired, slot detached, table geometry valid | Cleared page-table chunks remain cached; BO descriptors/container released |

The reaper checks completion across both adopted queues using the existing
ordered submission histories. Missing queue/MMIO/aperture observations cannot
prove completion of nonzero work. A fence greater than the emitted global
sequence is rejected. Sequence and ring-write-pointer exhaustion now refuse a
new submission rather than wrapping the retirement timeline.

For a closing context still bound to hardware, the reaper disables that context,
requires the disabled value to read back, and requires a successful invalidation
ACK. Only then does it release the software slot. It verifies slot ownership in
both directions, rejects invalid page counts/missing chunks, and clears/flushes
only the pages actually used. BO release and host `complete()` happen after
these checks, not after an elapsed timeout.

Failed binding attempts now mark their slot uncertain. Such a slot cannot be
lent to another client, and reclamation is held globally while hardware might
still refer to old or replacement page tables. Its original owner can clear the
uncertainty through successful binding validation, or a closing context through
successful disable/invalidate. There is no automatic reset or assumed recovery.

## Reclamation triggers and failure handling

Reclamation runs on ownership transfer, VM-context allocation, GPU submission,
successful waits and service stop. It is on-demand: if a client exits and no
further driver activity occurs, completed resources may remain retained until
the next trigger. No periodic worker/timer is implemented here.

Inconsistent handoffs are appended atomically to an explicit quarantine ledger.
They are not guessed to be safe or discarded. This ledger has no automatic
recovery path. Allocations and submissions recheck the stopping state after
acquiring the GPU lock, closing a stop-vs-entry race.

Service stop does not claim to have quiesced firmware, MES or active queues.
If queues, firmware regions, contexts or quarantine entries remain, it retains
the service once and preserves mappings, locks, page tables and descriptors.
It declines further ordinary GPU readiness/binding and does not run the original
destructive teardown. This intentionally prevents ordinary unload of an active
experimental instance; verified device-wide quiescence/reset and balanced
release of the quarantine retain remain future work. The cold, inactive service
teardown is unchanged after the guard. No such path is executed on this machine.

## Host validation

`tools/test_context_retirement.py` extracts the actual deferred-transfer/reaper,
fence/retirement reader, allocator, stop, client-close/destructor, memory-export,
wait and descriptor-release implementations. Host fakes supply IOKit objects,
MMIO and fence storage; ASan/UBSan executes the actual method bodies. The cases
check that pending work and failed disable/ACK preserve descriptor references,
host pins, page bytes and allocation ownership; successful retry releases once
and only after confirmation. They also exercise cached page reuse, partial last
chunks, both queues, impossible fences, inconsistent ownership, a simulated CAS
retry, close during wait, repeated close/free, stop retention and stop racing
allocation. These are deterministic host scenarios, not concurrency stress or
actual DMA/page-wiring validation.

The VM submission regression also executes sequence/write-pointer exhaustion
and stopping refusals; the adoption regression refuses adoption after stop.
Windows runs Python integration and runner-contract tests only. Native and full
macOS results must be recorded separately after CI verification.

Run `41157643806` / code `ce3bda5` completed its Linux source job successfully:
171 Python tests, all 54 retirement/client/stop sanitizer cases, 71 VM binding
cases, 73 adoption cases and all existing regression suites passed. Method and
declaration hashes match canonical staged source; exact outcome sets, 1455 CLI
operation-count dictionaries and 26 patch/header Git-object hashes were checked
independently. See `validation/ci-ce3bda5-context-retirement.json`. Native macOS
job `124408136515` subsequently completed successfully. The full kernel/plugin/
translator/RADV/LLVM build, signing, compiler/runtime checks and non-target refusal
passed. Independently checked 19 patch plus seven header hashes, four runtime
hashes and both real plugin shader outputs; zero binaries were retained. See
`validation/ci-ce3bda5-full.json`. This historical build predates individual BO
and serialized queue retirement. No target GPU execution, actual page wiring,
device-wide quiescence or concurrency-stress pass is claimed.

## Remaining lifetime and hardware gaps

- Individual `doBoFree` and explicit GEMVA unmap are not converted to deferred
  BO retirement. They can still discard mappings/release backing while work is
  active; this patch protects descriptors still owned when the whole client closes.
- Partial map failures, safe unmap rollback and page-table mutation while prior
  submissions are in flight remain unresolved.
- Direct legacy invalidation is still used. Active-MES/GFXOFF integration,
  real fence/cache ordering, DMA quiescence, device reset and unload are unverified.
- Reaping currently performs descriptor release while holding the sleepable GPU
  lock. Target latency and descriptor-completion reentrancy need validation before
  claiming a production-quality reclamation mechanism.
- Exclusive boot-memory/doorbell ownership, actual Tahoe initialization, shader
  execution, display output and Metal/WindowServer acceleration remain unverified.

No existing EFI, OS installation, BIOS, NVRAM or security setting is changed.

## Individual BO follow-on

Patch 0020 extends deferred ownership to individual BO free and checked map/unmap;
see BO-RETIREMENT.md. The whole-context harness now also tests transferring
pending-free normal and host BOs, retaining them while work is pending and
releasing once after retirement. Run `41159691075`, code `da5c999`, passed the
expanded 55-case context suite and 82 individual BO cases under ASan/UBSan.
See `validation/ci-da5c999-bo-retirement.json`; this is host evidence only.

## Checked cached storage and stop follow-on

Patch `0024-checked-context-table-clear.patch` adds `ptClear` to the actual
reaper. Retirement and hardware-slot detach/ACK remain prerequisites. Before
writing any byte, it validates every cached 64-KiB descriptor, including cached
chunks beyond the used-page count: exact length, whole physical segment,
aligned/nonwrapping CPU span, supported physical extent, cached physical-base
agreement, contiguous chunk ownership and no pairwise CPU/physical overlap.
Missing used backing, stale metadata, holes or malformed descriptors retain the
closing context, its BO container and imported-page wiring. A later checked
retry can reclaim them without another ownership transfer.

Validated CPU pointers are snapshotted before mutation. Clearing and flushing
touch only the used-page prefix; unused tails and unused cached chunks remain
unchanged. No second CPU-pointer lookup occurs during clearing. Corrupt PDE
contents do not alone prevent clearing valid owned storage after the existing
retirement, detach and global ownership checks; this is storage validation,
not permission to skip GPU retirement or invalidate unknown ownership.

The stop guard now also preserves orphaned or faulted hardware-slot state, and
evaluates tracked active state even when the GPU lock is missing. A busy
context, ready queue, firmware ring/TMR or quarantine ledger prevents cold
teardown. The service is retained at most once. Only an inactive service with
no uncertain tracked ownership can take the cold cleanup path. This still
does not implement device-wide reset/quiescence or active unload.

The harness now defines 110 cases: the previous 55, a 39-case root/used/unused
cached descriptor fault matrix, seven additional clear cases and nine stop
cases. Refused clear cases assert the entire backing remains unchanged, BO
references/pins remain owned, and geometry-only repair permits exactly one
release. Alias cases keep physical-cache metadata consistent so they reach the
overlap check. Snapshot and corrupt-entry cases check actual successful clear
behavior. The cold-stop fixture explicitly removes both software/hardware
associations; a separate orphan-slot case checks the previously hidden hazard.

Windows Python integration/runner checks passed: 212 total tests, 204 executed
successfully and eight explicit POSIX-only skips; syntax compilation and
`git diff --check` passed. The 110 actual-method C++ scenarios, sanitizer
execution and full macOS build are pending CI verification. No target GPU,
DMA, page wiring, concurrency stress or hardware acceleration pass is claimed.
