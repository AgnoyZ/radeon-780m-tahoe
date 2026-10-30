# Checked TOC to TMR initialization

Patch `0010-checked-toc-initialization.patch` connects the managed PSP path's TOC
response to its TMR request. The previous generic response exposed firmware
addresses, not `tmr_size`; using those words as a size would be wrong. The original
shell's literal TMR size was not a target measurement.

## Protocol basis

The source references are Linux commit
`7d0a66e4bb9081d75c82ec4957c50034cb0ea449`, under
`drivers/gpu/drm/amd/amdgpu/`:

- `psp_gfx_if.h`: `GFX_CMD_ID_LOAD_TOC` is `0x20`. The request union begins
  with the 4 KiB-aligned GPU address low/high words and the TOC size. The packed
  response stores `tmr_size` at byte **16**: after status, session ID and both
  firmware-address words. The command buffer's response begins at byte 864.
- `amdgpu_psp.c`, `psp_load_toc` and `psp_tmr_init`: the TOC loader reads
  `resp.tmr_size`. When a non-SR-IOV device has a TOC and private staging buffer,
  initialization loads the TOC before allocating the TMR. The allocation permits
  GTT or VRAM; this project's current descriptor still describes VRAM regions.
  A target's MP0/IP version and supported memory placement need actual discovery.
- `amdgpu_psp.h`: TMR allocation alignment is `0x100000` (1 MiB). This project
  checks the configured TMR MC and backing physical addresses against that bound.

These references define the implemented fields and sequencing, not target
compatibility. No Linux implementation or firmware binary is copied into this
patch. The existing nullarc source/license provenance is retained.

## Managed state and interface

New privileged/debug selector 115 accepts two scalar inputs: staging-buffer
offset and TOC byte count. It requires a live ring and explicit layout, validates
the staged extent and 4 KiB GPU address alignment, then submits `LOAD_TOC` under
the PSP lock. Only a successful checked fence/status permits reading the size
field. The response layout is checked against command-buffer capacity at compile
time. Returned scalars are status, elapsed microseconds, required TMR bytes and
whether the configured TMR capacity/alignment can accommodate that requirement.

An acknowledged TOC with a positive size may return a **fit flag of zero**. That
reports the observation, not successful initialization or permission to use a
different memory region. No TMR is set up by this call. A zero size is unusable
and latches failure; a timeout or PSP error uses the existing sticky failure path.
New TOC submission clears a previous size before attempting the command, and ring
clearing or uncertain PSP lifecycle failure also clears it. TOC reload after a
successful TMR setup is refused.

Managed TMR setup now requires a confirmed TOC size, an exact matching explicit
request, sufficient capacity and 1 MiB-aligned addresses. It preserves the size
reported by firmware without extra rounding. Repeating setup after success is
refused. Engine firmware loading and RLC autoload require successful TMR setup;
they cannot proceed after an unconfirmed predecessor. This does not track all
engine firmware types, verify every component selection, or prove engine readiness.

The research CLI syntax is:

```text
phxctl loadtoc <file> <file-offset> <size> <staging-offset> <reviewed-whole-file-sha256>
```

It reuses the complete, hash-checked snapshot transfer. Any failed chunk prevents
the TOC command. Transport/length/PSP errors stop; zero/oversized reply fields or
any fit value other than one stop with exit 75. A non-fitting response is reported
as an observation on stderr before refusal. A successful command explicitly says
that TMR has **not** been set up. It does not run subsequent stages automatically.

This is not a deployment command sequence. Source hashes and file slicing must
come from the reviewed firmware manifest, and region ownership must be resolved
independently. The CLI does not automatically verify that its supplied slice is
the intended TOC. Raw debug commands remain outside this managed sequencing;
the original boot scripts are not safe alternatives.

## Verification status

The actual-method harness now extracts eight kernel methods and defines 69 cases.
The 21 additions include TOC completion/status failures, wrong/zero/over-capacity
sizes, source/address bounds, stale-result invalidation, misaligned TMR rejection,
exact non-page-sized response preservation, TMR repetition refusal and a sequential
stage/TOC/TMR/stage/engine-load positive path using fake memory and firmware replies.
The independent words at response offsets 8 and 12 deliberately differ from the
size at offset 16, so confusing firmware addresses with size is detectable.

The actual CLI harness now has 60 cases, adding 14 TOC cases covering failed
snapshot/transfer/transport/reply prerequisites. Neither harness emulates firmware
or executes a GPU. Run `41145000196`, code `a5eab3a`, passed all 69 kernel-method
cases and all 60 CLI cases under ASan/UBSan. Each method hash, patch/header hash
and CLI operation count was cross-checked; see `validation/ci-a5eab3a-toc.json`.
107 Python source/runner tests passed locally. Full native kernel compilation
for this revision is still pending. Previous revision `005062f` passed its 48
kernel-method and 46 CLI cases; that evidence is historical and does not prove
this new sequence. See `validation/ci-005062f-layout.json`.

Remaining work includes target Tahoe/IP discovery, real reserved-region ownership,
firmware component/type orchestration, non-reference GART/queue setup and verified
GPU execution before display takeover. No driver was installed or hardware state
changed to implement or test this revision locally.
