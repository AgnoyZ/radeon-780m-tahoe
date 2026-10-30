# Bring-up integration audit: not ready for deployment

Reviewed pinned nullarc `cbb08ddf517c009255a74ad0fbc2cd7e0d6fa339` on 2026-10-30.
This is a source audit, not a firmware or target-hardware test. None of the reviewed
scripts was executed. No source reference-machine address is a verified ThinkBook
address. The current build intentionally does not install these scripts or tools.

## Concrete blockers in the reference workflow

| Source | Observed behavior | Required downstream change |
| --- | --- | --- |
| `tools/phxctl/bringup5.sh` | Uses literal firmware byte offsets/sizes and literal PSP command words, rather than a verified local firmware manifest and target memory map. | Parse the actual pinned firmware headers, validate payload bounds and expected IP, and derive addresses from reviewed target evidence. Never copy reference command addresses as defaults. |
| `tools/phxctl/mesboot.c` | `VRAM_MC`, `FB_PA`, the system aperture and default/fault-page registers contain reference-machine constants. Queue, GART and scratch regions also have fixed offsets. | Introduce an explicit target layout with verified MC/physical/aperture relationships and exclusive region ownership. BAR bounds alone or finding zero-filled memory does not prove a region is free. |
| `tools/phxctl/mesboot.c` | Helpers `rd`, `wr`, `vw` and `vr` discard IOKit return codes; `rd` can return its initialized zero after a failed read. | Propagate transport status and exact returned lengths. Stop before the next write when any prerequisite read/write or firmware response fails. Zero is not a replacement for an unknown register value. |
| `tools/phxctl/bringup5.sh`, `tools/phxctl/full.sh` | Firmware/register operations are piped to `grep`/`tail` without `pipefail`; failures can be hidden by a successful final pipeline command. | Use a checked, structured stage runner. Track transport completion and device response separately; do not infer success from a matching log line. |
| `tools/phxctl/full.sh`, `tools/phxctl/phxboot.sh` | The workflow includes automatic reboot timers, `killall shutdown`, sysctl changes, allow-list changes and NVRAM-based display arming. | Keep initial manual compute bring-up separate from desktop takeover and persistent boot configuration. Any recovery mechanism must own only its own timer/process and require an explicitly reviewed deployment plan. No automatic installation here. |
| `src/phxbringup/PhxNativeABI.h` and `PhxBringup.cpp` | Kernel firmware/ring offsets and size checks are coupled to the experimental layout; the shell's raw PSP words and userspace constants duplicate layout assumptions. | Define one validated layout contract shared by userspace and kernel. Check arithmetic overflow, alignment, pairwise overlap and firmware/display reservations before permitting writes. |

The existing downstream PCI/Darwin/opt-in gate is necessary but does not resolve
these layout, firmware, sequencing or recovery problems. A compiled kext and a
working userspace compiler are not a completed GPU boot sequence.

## Evidence required before an initialization experiment

1. Confirm the actual target Tahoe build, a tested external-disk/EFI recovery path
   and the exact driver/firmware revisions. The last verified target environment
   remains Sonoma Recovery, not Tahoe.
2. Capture target PCI resources and GPU IP discovery, framebuffer/UMA bounds and
   console/reserved-region ownership without modifying hardware. Keep raw data
   private. A Windows resource snapshot is not proof of the macOS memory layout.
3. Pin and audit each firmware input. Validate its hash, header, payload ranges,
   engine/IP version and licensing; do not publish firmware files or reuse
   reference byte counts without checking the actual input.
4. Replace the unchecked transport helpers and duplicated reference layout before
   building a target execution plan. Validate the rejection paths using fault
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
