# Bound native-submit diagnostic reads

Patch `0027-bounded-ib-debug-reads.patch` corrects a CPU overread in the actual
`IOAccelPhxNativeClient::doSubmit` diagnostic path. This is a driver reliability
fix, not target GPU execution or graphics acceleration evidence.

## Valid submissions could overrun the first CPU buffer

`ibCovered` permits one IB to span adjacent executable GPU mappings, including
different BOs. The original debug path finds the first mapping and reads up to
96 IB dwords from that BO's CPU pointer, ignoring the first mapping's remaining
extent. For example, a valid 17-dword IB can begin at the final dword of one
4-KiB BO and continue into a second BO. The old diagnostic tries to read past
the first CPU allocation before forwarding the valid IB to the GPU.

This path runs only with debug enabled and client `emitted < 4`. Disabling
debug avoids that diagnostic, but is not a source fix. Concatenating GPU VA
mappings does not make their independent CPU allocations contiguous.

## Corrected behavior

- Select an active, non-pending, executable mapping containing the IB start.
  Use subtraction rather than adding the map base and length.
- Require a visible BO CPU pointer and descriptor. Validate BO offset plus
  relative IB offset before addition; the start must also fit the descriptor.
- Clip the diagnostic to the minimum of IB size, 96 dwords, remaining map
  extent, remaining BO size and remaining descriptor length.
- Check pointer-offset addition, whole-read span and dword alignment before
  forming or dereferencing the final CPU pointer.
- Log only that first CPU-visible prefix. Preserve the original IB addresses,
  sizes, order, engine selection, pre-submit flush, forwarding and sequence
  publication. Do not reject a valid multi-BO IB just to simplify its logging.

Logging is not complete command-stream inspection. CPU-opaque BOs are not
read; fewer than 96 words can legitimately be logged. Malformed CPU geometry
can suppress or shorten diagnostics without establishing that GPU mappings
are safe. GPU-side ownership, executable permissions, cache coherency and
actual execution remain separate acceptance requirements.

## Regression design and evidence limits

`tools/test_ib_debug.py` extracts the real client methods and compiles them
with the shared fake BO fixture. It constructs valid adjacent GPU mappings
whose CPU allocations have independent sanitizer red zones. It also tests
CPU metadata faults and deliberately invalid pointer geometry as diagnostic
fault injection; those do not represent valid hardware mappings.

The runner first reverse-applies only patch 0027 in a separate fresh source
tree, compiles that previous actual method and requires a captured
`AddressSanitizer: heap-buffer-overflow` for the valid `cross-1` case. Unit
tests bind that previous method hash to audited code `4d71c0c`. The expected
sanitizer output stays captured; no raw sanitizer dump is published.

The corrected method then runs 56 scenarios in low and canonical upper VA
layouts, 112 total. They cover 1..16-word and larger boundary prefixes,
short/96-word/oversized logging caps, nonzero BO mapping offsets, two and 64
IBs, graphics/compute forwarding, debug/emission gating, opaque buffers,
descriptor/BO clipping, offset overflow and pointer overflow/alignment.
The fixture checks every logged word and zero-padded argument, unchanged
BO contents/map records, exact forwarded IBs, flush count and sequence output.
ASan/UBSan instrument the actual methods with warnings as errors. Only unused
shared fixture helpers are exempted from unused-function warnings.

Windows checks verify extraction, the reverse-patch historical method hash,
scenario accounting, false-claim/crash rejection and source wiring. Windows
does not execute this C++ harness. POSIX regression reproduction and all 112
corrected scenarios remain pending until the corresponding CI is audited.
No target kernel is loaded and no real GPU work is submitted by these tests.
