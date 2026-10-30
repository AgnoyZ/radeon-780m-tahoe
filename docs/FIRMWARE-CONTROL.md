# Checked firmware control: not a deployment workflow

Patch `0008-checked-firmware-control.patch` updates the actual reference
`tools/phxctl/phxctl.c`. Previously a file short read ended the transfer loop,
then `loadfw` submitted the smaller byte count and could exit successfully after
an IOKit or PSP error. Staging also read the file incrementally while writing
device memory, so later chunks could come from a changed file.

## Corrected input and transfer contract

The research `stage` and `loadfw` commands now require the reviewed **whole-file**
lowercase SHA-256 as their final argument. Existing reference scripts omit it
and intentionally fail before opening the service; do not adapt/run those
scripts as an installation shortcut. The expected digest must come from the
reviewed `firmware.lock.json`, not be invented from an untrusted replacement.

Before staging any bytes, the tool:

1. Validates unsigned firmware arguments without truncating overflow/negative
   values, and checks the padded destination extent against the reference buffer
   capacity. This is a bound, not proof of target memory ownership.
2. Opens a bounded regular file and reads the complete file into a private memory
   snapshot. Short reads and read/close failures stop before any staging request;
   interrupted reads retry. The file is closed before transfer starts.
3. Uses Apple's CommonCrypto SHA-256 on the whole snapshot and requires the
   supplied digest to match. File-slice bounds are checked against that snapshot.
4. Transfers the selected slice in at most 4 KiB chunks. The load command is
   issued only after every chunk succeeds, using exactly the requested length.
   A file changed after snapshot verification cannot alter subsequent chunks.

Every scalar/structured IOKit call in this tool now checks its return code and
exact reply length. HELLO verifies ABI version. PSP nonzero response status and
SMU non-success responses stop the process rather than printing a success and
continuing. The PSP status policy is conservative and needs target-specific
interpretation, as explained in `PSP-COMPLETION.md`.

Exit codes are 64 for invalid firmware arguments, 65 for file/hash/slice errors,
74 for IOKit transport/reply errors and 75 for unconfirmed ABI/PSP/SMU semantics.
Failed transfers free the snapshot and do not issue later chunks or a load
request. Previously accepted chunks are **not** rolled back or erased.

## Offline native verification

`phxctl verify-file <file> <reviewed-sha256>` is an offline mode that returns
before service lookup/opening. It reads/hashes a file, prints the verified byte
count and exits; it does not stage firmware or access a GPU. Only this mode is
executed by native CI. The tool is not added to deployment artifacts.

Native preflight compiles the real staged tool against system IOKit and
CommonCrypto. Four synthetic-file cases check a matching digest, wrong digest,
malformed digest and changed file using the real CommonCrypto implementation.
All four native cases passed for `5a066d0` and `005062f`; see
`validation/ci-5a066d0-full.json` and `validation/ci-005062f-native-preflight.json`.
They executed only `verify-file`, without opening the GPU service.

Separately, 39 ASan/UBSan host cases include the actual patched CLI source and
fake IOKit/crypto dependencies. They check complete-byte transfer, file mutation
after the first chunk, read failures/interruptions, hash refusals, argument bounds,
short/long replies, stage/load failures and no later operations after a failed
prerequisite. The fake crypto checks fixture bytes but is **not** a SHA-256
implementation test; native CommonCrypto results must be reported separately.
Run `41102630320`, code `5a066d0`, has now passed all 39 cases under ASan/UBSan
and standalone C11 compilation. The extracted report and patch hashes are in
`validation/ci-5a066d0-control.json`. Real native CommonCrypto results are recorded
separately in the native evidence above; the fake crypto remains a different test.

Source review found that the newly included shared ABI header uses C11
`static_assert`, but `phxctl.c` had not included `<assert.h>`. The test harness
included it first and could hide this standalone compilation defect. Patch 0008
now includes the header in the tool itself. Host CI first compiles the actual
tool as its own C11 translation unit with fake IOKit declarations and warnings
as errors, before building the harness; the native build also explicitly selects
C11. Both POSIX standalone compilation and the native compiler/CommonCrypto path
have now passed for the corrected revision.

The earlier native run `41101826570`, code `b39f6f8`, subsequently finished with
failure in job `124220444422`. Its compiler errors identify `static_assert` in
`PhxNativeABI.h` as an invalid declaration, confirming the missing-include defect
fixed by `5a066d0`. That failed preflight did not reach any real CommonCrypto
file-verification case or the full native driver build. A successful Linux test
of the corrected revision does not turn the failed native run into a pass.

Patch 0009 adds `psp-layout` to send an explicit 64-byte descriptor to the new
privileged/debug kernel selector. It supplies metadata without staging bytes or
creating a ring. Seven additional CLI cases check descriptor fields, argument
refusal and terminal transport/reply errors, bringing the host suite to 46 cases.
All 46 cases passed ASan/UBSan in run `41104430767`, code `005062f`; see
`validation/ci-005062f-layout.json`. See
`PSP-LAYOUT.md` for the wire contract and the still-missing ownership requirements.

Patch 0010 adds `loadtoc`, using the same authenticated snapshot path before
submitting the staged TOC through selector 115. It requires a positive returned
TMR size and a fit flag of exactly one, then stops without setting up the TMR.
All 60 CLI cases passed ASan/UBSan in run `41145000196`, code `a5eab3a`; see
`validation/ci-a5eab3a-toc.json`.
107 Python tests pass locally. See `PSP-TOC.md` for the response layout, size
provenance and initialization sequencing.

## Remaining integration

This binds transferred bytes to a supplied digest, not to a vendor signature or
an automatically authenticated trust source. It does not automatically validate
component selection, PSP firmware type, destination allocation or target IP
compatibility. The header-derived manifest is a separate input; a controlled
orchestrator still needs to connect it to a verified target memory layout and
command sequence. The new layout descriptor checks numeric bounds/overlap but
does not allocate or establish ownership of its regions. Other raw-debug argument paths are not a reviewed deployment
interface. Shell pipelines still need explicit error propagation.

No real firmware, kext or target machine is executed/modified by these tests.
Source staging retains the upstream license notices. Public binary publication
remains blocked, and existing EFI is unchanged.
