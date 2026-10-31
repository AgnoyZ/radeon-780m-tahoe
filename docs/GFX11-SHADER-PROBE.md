# GFX11 shader dispatch probe: target execution is unverified

Patch `0025-gfx11-shader-dispatch-probe.patch` adds a distinct `shader-probe`
path to the actual staged `mesboot` tool. The previous `compute-probe` writes
memory with a command-processor packet. This new path stages a GFX11 compute
shader, configures shader state and emits `DISPATCH_DIRECT` before its release
fence. Source construction and synthetic observations do not prove that a GPU
has executed either path. Neither command is an installation workflow.

```text
mesboot shader-probe <virtual-base> <mapped-bytes> <table-offset> <default-page-offset> <scheduler-arena> <scheduler-doorbell> <shader-arena> <shader-doorbell>
```

This remains an experimental candidate for a later reviewed manual target
experiment. It requires the same previously configured, owned and verified
firmware/GART/MES environment as `compute-probe`. It performs scheduler setup
itself on one ABI-checked connection. Existing active HQDs and legacy experiment
overrides are refused. It does not discover ownership, allocate a reserved
region, initialize firmware or make a reference-machine layout suitable for
the user's laptop. Do not run it with guessed addresses or deploy it to EFI.

## Six-page work arena

| Relative bytes | Purpose |
| --- | --- |
| `0x0000` | Compute ring |
| `0x1000` | Queue read/write pointers |
| `0x2000` | MQD |
| `0x3000` | EOP |
| `0x4000` | Guarded shader output and separate release fence |
| `0x5000` | Shader instructions and zeroed page tail |

All six pages must fit the GART mapped prefix, CPU aperture and 32-bit write
offset contract. The whole arena must be disjoint from the scheduler arena,
GART/default page and all configured PSP regions, and the doorbells must differ.
All six actual PTEs are checked before any arena writes. A sixth-page overlap
cannot hide behind the previous five-page compute-probe validator.

The output page has a 16-byte guard, 1024 bytes of output, a second 16-byte
guard, and a separate aligned fence at page offset 2048. Every output word is
initialized to the complement of its expected value. Four distinct constants
repeat as the expected vector value; they are passed through user SGPRs, not
inserted into a command-processor `WRITE_DATA` packet. The shader code is
staged in its own page and every 64-bit pair is read back before dispatch;
the last odd word is checked together with its zeroed neighboring word.

## Candidate command sequence

The tool retains scheduler resource/query completion, checked `ADD_QUEUE`
and parameterized compute-HQD readbacks from the existing explicit path.
It builds and validates the entire 86-dword shader packet before compute-arena
initialization. Program/result/fence addresses must be nonzero, aligned and
fit their full extents in 48 bits; program and result VA spans cannot overlap.
Invalid packet inputs leave the caller's packet storage unchanged.

1. `ACQUIRE_MEM` requests the reviewed MEC cache invalidation/writeback fields,
   including instruction-cache invalidation. This is a candidate cache protocol,
   not target cache-coherency evidence.
2. Clear compute starts, scratch-ring/request/user-accumulator/checksum state;
   configure indexed CU masks and program addresses.
3. Install the reviewed shader resource fields, a 64-thread X dimension, one
   Y/Z dimension and one 64-record, 16-byte-stride output descriptor. Set four
   distinct user constants and clear resource limits.
4. Emit one `DISPATCH_DIRECT` group and the existing full-width `RELEASE_MEM`
   sequence. Update both write-pointer shadow words before the doorbell.
5. Require the 64-bit release value within 400 polling samples, then re-read it,
   check all 256 output dwords and both full guards. Transport, staging, output,
   fence, delay and close failures cannot print the success marker.

Even a genuine target pass would establish only this fixed buffer-clear
shader's dispatch/output/fence behavior. It would not prove general arithmetic,
shader compilation, user GPUVM, queue adoption, Metal, scan-out or WindowServer.
No resources are reclaimed merely because the CLI process exits; a queue can
remain live. There is no automatic reset, rollback or retry after partial state.

## Provenance and licenses

The 79 instruction words are the unchanged `bufferclear_cs_shader_gfx11` array
from the official libdrm 2.4.123 source archive. Only the local symbol changes;
the complete AMD 2022 MIT-style permission/warranty notice accompanies it in
the added `gfx11_shader_probe.h`. The archive, source files and little-endian
instruction stream are hash-recorded in
`validation/libdrm-2.4.123-shader-reference.json`. This is source test code, not
firmware or a redistributed driver binary. Other component publication gates
remain unchanged.

The packet builder is independently written using the reviewed GFX11 dispatch
helpers' state/descriptor semantics. MEC `ACQUIRE_MEM` and GCR field locations
were checked against the pinned Mesa `ac_cmdbuf_cp.c`, `ac_barrier.c` and
`pkt3.json`; file hashes and the field derivation are in the same reference
record. No libdrm/Mesa implementation bodies or full headers are copied.
The hardware state normally supplied by Linux's kernel submission path must
still be validated for this direct-ring candidate on the actual target.

## Validation scope

The new mode of `tests/test_mes_queue.c` includes the actual staged CLI. It
asserts the complete packet, program/result/fence high words, staged shader,
complement initialization, guards, queue state and write-pointer ordering.
Its fake GPU deliberately supplies or corrupts results; it does not interpret
the ISA or execute a shader. Baseline/relocated variants exercise different
address high bits and doorbells. Regressions also cover invalid packet inputs,
each staged code pair, each output word, each guard, sixth-page PTE/overlap
failures, transport boundaries, timeout, changed fence and failed close.

Windows Python checks completed: 218 total tests, 210 executed successfully and
eight explicit POSIX-only skips; syntax compilation and `git diff --check`
passed. The shader runner defines 915 cases per layout variant, 1830 total.
Code `fbd61b8`, run `41168516913`, subsequently passed all 218 Linux Python
tests without skips and all 1830 actual-CLI scenarios under ASan/UBSan, together
with the existing kernel/context/page/walk/queue/adoption and firmware/CLI
regressions. All 1830 operation-count dictionaries, the exact staged CLI and
canonical-LF header hashes, the unchanged 79-word shader, six new runner
outcomes and 32 patch/header Git input hashes were independently checked. See
`validation/ci-fbd61b8-shader-probe.json`.

Native job `124441666535` is in progress; native tool preflight/full build of
this revision are not yet independently verified. No target execution,
firmware residency, hardware cache correctness or acceleration is claimed.
The working EFI, disks, BIOS, NVRAM and OS security settings remain untouched.
