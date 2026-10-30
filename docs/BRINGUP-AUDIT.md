# Bring-up integration audit: not ready for deployment

Reviewed pinned nullarc `cbb08ddf517c009255a74ad0fbc2cd7e0d6fa339` on 2026-10-30.
This is a source audit, not a firmware or target-hardware test. None of the reviewed
scripts was executed. No source reference-machine address is a verified ThinkBook
address. The build does not install these scripts or tools. The downstream
`mesboot.c` is now staged for compile-only and fake-transport regression checks;
it is not packaged as a deployable initialization tool.

## Concrete blockers in the reference workflow

| Source | Observed behavior | Required downstream change |
| --- | --- | --- |
| `tools/phxctl/bringup5.sh` | Uses literal firmware byte offsets/sizes and literal PSP command words, rather than a verified local firmware manifest and target memory map. | Parse the actual pinned firmware headers, validate payload bounds and expected IP, and derive addresses from reviewed target evidence. Never copy reference command addresses as defaults. |
| `tools/phxctl/mesboot.c` | `VRAM_MC`, `FB_PA`, the system aperture and default/fault-page registers contain reference-machine constants. Queue, GART and scratch regions also have fixed offsets. | Introduce an explicit target layout with verified MC/physical/aperture relationships and exclusive region ownership. BAR bounds alone or finding zero-filled memory does not prove a region is free. |
| `tools/phxctl/mesboot.c` | Upstream helpers discard IOKit return codes and can use initialized zero after a failed read. | Downstream patch `0004` makes IOKit errors and mismatched reply lengths terminal; firmware/GPU response semantics and timeout propagation still need separate work. |
| `tools/phxctl/bringup5.sh`, `tools/phxctl/full.sh` | Firmware/register operations are piped to `grep`/`tail` without `pipefail`; failures can be hidden by a successful final pipeline command. | Use a checked, structured stage runner. Track transport completion and device response separately; do not infer success from a matching log line. |
| `tools/phxctl/full.sh`, `tools/phxctl/phxboot.sh` | The workflow includes automatic reboot timers, `killall shutdown`, sysctl changes, allow-list changes and NVRAM-based display arming. | Keep initial manual compute bring-up separate from desktop takeover and persistent boot configuration. Any recovery mechanism must own only its own timer/process and require an explicitly reviewed deployment plan. No automatic installation here. |
| `src/phxbringup/PhxNativeABI.h` and `PhxBringup.cpp` | Kernel firmware/ring offsets and size checks are coupled to the experimental layout; the shell's raw PSP words and userspace constants duplicate layout assumptions. | Define one validated layout contract shared by userspace and kernel. Check arithmetic overflow, alignment, pairwise overlap and firmware/display reservations before permitting writes. |

The existing downstream PCI/Darwin/opt-in gate is necessary but does not resolve
these layout, firmware, sequencing or recovery problems. A compiled kext and a
working userspace compiler are not a completed GPU boot sequence.

## Implemented arithmetic correction; target validation pending

`patches/0003-bringup-aperture-bounds.patch` replaces addition-based end checks in
`PhxBringup::doorbellWrite` and `PhxBringup::pspRing`. Their 64-bit offsets could
wrap when adding the access extent. The shared `rangeWithin` policy first checks
the offset against the limit, then compares the extent with the remaining space;
it never computes a potentially overflowing end address. Existing alignment and
privilege/opt-in rules are retained. The ring must fit both below TMR and within
the mapped framebuffer aperture before its first aperture access.

Python tests verify the actual staged patch and ordering before memory access.
The same helper used by the kext has C++ boundary, wraparound and exhaustive
small-range assertions in the sanitizer suite. These are source/host arithmetic
checks, not GPU execution. They do not establish ownership of the selected VRAM
regions, validate firmware, remove the reference-machine constants, or make the
original boot scripts safe to deploy.

## Checked userspace transport (2026-10-31)

`patches/0004-checked-bringup-transport.patch` routes every `mesboot.c` scalar and
structured IOKit request through checked calls. A non-success status or any
short/long reply exits with status 74 before returning a register value, issuing
the next write, or printing a successful command return. This covers register and
VRAM access, doorbells, system memory, queue adoption, accelerator claim and the
HELLO handshake. HELLO also rejects a different ABI version. Service lookup
references are released after opening.

The fault-injection harness includes the **actual staged tool source**, replacing
only IOKit with an explicit fake transport. Its 47 subprocess cases cover normal
returns, legitimate zero data, transport errors, both reply-length directions,
ABI/open failures and failed read/write prerequisites. ASan/UBSan instrument this
host test; it asserts the exact call count so a later write cannot masquerade as
an acceptable error. Native preflight separately compiles/links the patched tool
against real macOS IOKit without executing it. Run `41087992288` / code `b2cadc9`
passed all 47 injected cases and the real-I/O-library compile/link preflight.
The full native driver build remains in progress; see
`validation/ci-b2cadc9-transport.json`. Neither check executes the real transport
or a GPU workload.

Source provenance is retained for the new patch. The staged tool uses the pinned
upstream MIT option (`LICENSE` and `LICENSES/MIT.txt`); its two unmodified AMD
headers retain their embedded 2021/2022 MIT-style notices. No firmware is added.

**This is not a safe deployment workflow yet.** Stopping userspace does not undo
hardware changes already made, prove that outstanding GPU work is quiescent,
validate firmware responses, propagate every GPU timeout, or remove the hardcoded
reference memory layout. No automatic GPU reset or speculative recovery writes
are added. The real tool is not executed or installed by these checks.

## Completion handling checked on hosts, not target hardware

`patches/0005-checked-gpu-completion.patch` makes missing MES completion terminal
(exit 75), so callers such as `sched_test` cannot ignore a timeout and launch the
next initialization stage. The tool compares the entire 64-bit query fence and
command completion token, requiring the token value 1 that it put in the command.
It validates these before even diagnostic register-selection writes. Reading a
previous scheduler sequence also retains its high 32 bits.

Compute and graphics queue tests now require both their expected scratch-register
value and their expected memory write before later register changes or queue
adoption. The graphics target is initialized to the complement of its expected
value so stale data cannot satisfy the memory check. These markers are the
reference tool's basic execution checks, not a Metal shader/rendering workload.

Completion-field encoding uses `memcpy` rather than an unaligned `uint64_t *`
store: the pinned MES frames have only four-byte alignment. The host harness
exercises a deliberately four-but-not-eight-byte-aligned frame under sanitizers.

The harness now has 52 transport cases plus 20 injected completion-path cases.
The latter run the actual MES submission, scheduler initialization, compute and
graphics functions, including positive adoption paths, timeouts, missing/wrong
tokens, mismatched high fence/token words, and independent scratch/memory failures.
They check bounded polling, no next stage or adoption after failure, and no later
scalar write after the injected failed completion. This is **control-flow testing
with fake observations**, not GPU emulation, packet correctness or hardware proof.
Run `41089800738` / code `61c5c0e` passed all 52 transport and 20 completion
cases under ASan/UBSan. Its macOS preflight also compiled/linked the real tool
without executing it. The full native driver build remains in progress; see
`validation/ci-61c5c0e-completion.json`.

No hardware rollback is attempted. KIQ/SDMA experiments, ring capacity/ownership,
sequence exhaustion, firmware responses, target mappings and safe recovery still
need separate validation before deployment. Process exit is not proof that the
GPU is idle or its earlier writes have been undone.

## Evidence required before an initialization experiment

Start with `TARGET-INVENTORY.md` for the new metadata-only collector. It records
the actual OS build and whitelisted registry PCI identities/assigned apertures,
with timeouts and without raw dumps. It does not establish independent hardware
identity, GPU IP layout or reserved-region ownership and never approves bring-up.

1. Confirm the actual target Tahoe build, a tested external-disk/EFI recovery path
   and the exact driver/firmware revisions. The last verified target environment
   remains Sonoma Recovery, not Tahoe.
2. Capture target PCI resources and GPU IP discovery, framebuffer/UMA bounds and
   console/reserved-region ownership without modifying hardware. Keep raw data
   private. A Windows resource snapshot is not proof of the macOS memory layout.
3. Pin and audit each firmware input. Validate its hash, header, payload ranges,
   engine/IP version and licensing; do not publish firmware files or reuse
   reference byte counts without checking the actual input.
4. Retain the checked transport/completion paths and replace the duplicated
   reference layout before building a target execution plan. Validate rejection paths using fault
   injection and boundary tests, without claiming that these are GPU tests.
5. Review a single, explicit manual initialization sequence and its recovery
   procedure. Hardware execution needs a separate authorized target-machine step;
   the repository build must not run it.
6. Prove real compute completion and correct output before enabling display
   takeover. Then validate the actual panel, repeated boot, WindowServer and
   stability independently. A printed `done`, fabricated fence or device name
   cannot satisfy any of these checks.

This is the next hardware-facing integration work, not a proposal to reduce the
goal to a compiler-only or no-device-only stack. Full Radeon 780M operation on
Tahoe remains the objective and is still unproven.
