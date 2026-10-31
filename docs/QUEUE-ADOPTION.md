# Kernel queue adoption

Patch `0017-checked-queue-adoption.patch` changes the existing
`PhxBringup::adoptQueue` implementation used by debug selector 112. It does not
change the six-scalar ABI or automatically hand a probe queue to the kernel.

## Implemented checks

- Reject null input and missing mappings, MMIO, MC base or either lock.
- Validate the complete ring, 32-byte writeback and 8-byte fence spans against
  VRAM size, CPU aperture length and the 32-bit offset domain. Subtraction-based
  checks reject both 64-bit addition overflow and truncation before any narrowing.
- Preserve ring-size/power-of-two/alignment checks and validate the full 8-byte
  doorbell span without overflowing. Fence bit zero still selects compute or
  graphics; the remaining alignment bits are checked.
- Reject any pairwise overlap between the new ring, writeback and fence.
- Hold `gpuLock` then `smuLock`, matching the existing layout/snapshot lock order.
  Require a valid configured PSP layout and a non-faulted PSP state. Reject
  overlap with the entire configured PSP ring, TMR capacity or staging capacity.
- Refuse an already adopted queue, even when it appears idle, so its outstanding
  submission history and completion fence cannot be silently reset.
- Reject all nine overlap combinations with the other adopted queue, plus a
  shared 64-bit doorbell slot. The unadopted peer's unused fields are ignored.
- Construct a candidate queue only after validation. Initialize its fence using
  both words of the current sequence, flush, and publish the ready state. Every
  rejection preserves both queue records, framebuffer bytes and doorbells.

## Host validation

`tools/test_queue_adoption.py` stages the pinned upstream with all local patches,
extracts the actual `GpuQueue` declaration and `adoptQueue` method, and hashes
both. `tests/test_queue_adoption.cpp` provides host mappings/locks/flushes; it
does not reimplement the production method. The Linux CI step compiles this
translation unit with ASan, UBSan, warnings-as-errors and no sanitizer recovery.

Cases cover compute/graphics, a second queue with outstanding peer history,
repeat adoption, overlapping old/new regions, missing prerequisites, all
PSP/peer alias combinations, ring sizes, invalid alignment, end-of-aperture and
end-of-doorbell success, 64-bit wrap, 32-bit narrowing, and independent aperture
and VRAM overruns. Rejections compare complete queue and memory snapshots;
success checks exact publication fields and the only permitted two fence writes.
Fake locks assert the acquisition/release order, and the fake flush requires
that the new queue has not been published yet.

Windows runs source integration and runner-contract tests only. Native execution
is claimed only after the actual CI job and its reports are verified.

Run `41155047603` / code `d1ef9f2` completed its Linux source job successfully:
160 Python tests, all 72 adoption sanitizer cases and the existing regression
suites passed. The actual method/structure hashes, all adoption case results,
1455 CLI operation-count dictionaries and all 24 patch/header hashes were
independently checked. Windows staging CRLF is normalized to canonical LF when
comparing source text with Linux output; exact Git objects are used for input
hashes. See `validation/ci-d1ef9f2-queue-adoption.json`. The corresponding macOS
job `124400202228` is still in progress; no full native build or hardware pass
is claimed for this revision.

## Remaining integration requirements

These are numeric bounds and known-region exclusions, **not exclusive ownership
or a hardware-idle certificate**. They do not identify firmware/display/console
reservations outside the configured PSP layout. The kernel does not yet track
the GART table, default page, scheduler arena, MQD or EOP reservations here.
Privileged raw-debug clients can still write registers or memory independently.

The existing ABI does not convey authenticated HQD identity, producer ownership,
GART bindings, GPU retirement or a transfer token. Reusing writeback values or a
userspace success flag as proof would not close those gaps. The explicit
`compute-probe` command therefore continues to stop after its guarded completion
test; it does not call adoption, claim the accelerator or dispatch shaders.

Future integration must transfer an exclusively owned, verified idle queue and
all its associated regions into kernel-managed lifetime tracking, then exercise
GPUVM mappings and shader dispatch on the actual target. Submission counter
overflow, GPUVM timeout/lifetime handling, queue teardown and concurrent raw
debug access remain separate unresolved paths. No EFI, driver installation,
BIOS/NVRAM or OS-security setting is changed by this patch or these host tests.
