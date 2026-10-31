# Native GPUVM shader acceptance candidate

`tools/native_shader_probe.cpp` exercises the actual native client ABI used by
the Darwin RADV backend. Unlike the raw VMID0 debug-ring shader probe, this
candidate allocates a client context and GTT BO, maps GPU virtual addresses,
submits an indirect buffer and waits for the native retirement sequence.
**No target execution has been verified. This is not an installable driver.**

## Preconditions and scope

The manual target CLI is `native-shader-probe --check|--run [--upper]`.
It requires x86_64 Darwin 25 and exactly one `PhxBringup` service whose immediate
PCI parent reports vendor/device `1002:1900`. Both four-byte little-endian
CFData and bounded CFNumber properties are supported; missing, malformed and
ambiguous identities are refused. HELLO/QUERYINFO ABI, build, VMID, GFX11.0.1,
limits, non-hung state and native queue readiness must agree.

`--check` only checks identity and ABI readiness. It creates no context or BO,
does not map memory, and does not submit/wait for GPU work. Readiness can mean
only a graphics queue exists; the actual native COMPUTE submit must still
refuse if no compute queue is adopted.

`--run` is for an independently initialized and owned compute queue with
verified firmware, GPUVM and cache handling. This tool does not initialize
hardware, choose physical carve-outs, adopt queues, claim an accelerator,
install drivers or change EFI/NVRAM. Do not use it to bypass the outstanding
target ownership/initialization prerequisites. It is not executed on the
user's laptop by repository automation.

## Actual acceptance path

1. Validate an aligned 16-KiB extent inside the driver's reported low or
   canonical upper VA range. Do not guess a physical or retirement-fence address.
2. Allocate one native context, one 16-KiB CPU-accessible GTT BO and its CPU map;
   GPU-map the BO executable through GEMVA. Require exact response shapes.
3. Page 0 holds the licensed, unchanged 79-word reference GFX11 clear shader;
   page 1 holds a 78-dword dispatch packet plus two reference-style NOP words;
   page 2 holds 1024 bytes of complement-initialized output and guards; page 3
   is a canary. All other bytes are deterministic and checked.
4. Submit one 320-byte compute IB through native SUBMIT. The kernel appends
   its own full-width retirement fence. The shared dispatch builder emits no
   guessed user fence; patch 0026 keeps the existing 86-dword raw-ring wrapper.
5. Require a strictly increasing valid sequence, positive bounded WAITSEQ,
   retired >= submitted and the exact client's emitted sequence. Compare all
   16 KiB, including shader, IB, guards, untouched padding and full canary page.
6. Repeat with a distinct four-word pattern. A positive result from one pass
   cannot hide a missing write in the other. CPU barriers supplement, and do
   not replace, the driver's existing pre-submit/post-retirement BO flushes.

The successful probe's claim is limited to two instances of this clear shader
through the native GPUVM/context/BO/submit/wait path. It would not establish
general shader compilation/arithmetic, Metal, display takeover or WindowServer.

## Failure and cleanup

Every transport status and returned scalar/structure count is checked.
Malformed ABI/VA/BO/mapping/sequence/output replies stop the run. If any step
fails, only the CPU view is unmapped and the client is closed; no speculative
GPU unmap/free/retry is issued. The kernel's existing pending retirement and
quarantine paths remain responsible for uncertain backing.

After two complete verified passes, cleanup is CPU unmap, GPU unmap, BOFREE,
CTX free, then client close. A failure at any cleanup step suppresses success
and prevents later explicit GPU cleanup. CTX-free reply must be entirely zero.
Exit codes: 0 accepted/check completed, 4 unsupported host/identity, 64 usage,
74 OS/transport/shape/cleanup error, 75 ABI/readiness/geometry/result mismatch.
An error does not prove the queue is quiescent or establish safe reinitialization.

## Build and validation boundaries

The macOS preflight compiles C++17 against real IOKit/CoreFoundation and staged
ABI/layout/shader headers. CI executes only `--check` on a non-target Mac and
requires refusal 4; it never invokes `--run`. Full local builds package this
probe beside `metal-smoke`; no automatic installation or public binary upload
is enabled. Shader provenance/license remain documented in GFX11-SHADER-PROBE.md
and `validation/libdrm-2.4.123-shader-reference.json`.

`tools/test_native_shader_probe.py` compiles the actual C++ source with separate
fake IOKit/CF headers and ASan/UBSan on POSIX Clang++. Its low/upper-VA scenarios
check independent packet contents and all staged bytes, exact ABI shapes,
identity/refusal paths, every reference shader word, IB word and output word,
padding/guard/canary corruptions in both passes, timeouts and cleanup failures.
GPU writes are explicitly supplied by the harness after WAITSEQ; it has no ISA
interpreter and performs no real GPUVM translation. These are control-flow and
acceptance-checker tests, not GPU execution evidence. Code `4d71c0c`, run
`41170563119`, passed all 226 Linux Python tests without skips, all 1970
native-probe ASan/UBSan scenarios and the existing 1830 raw-ring shader
scenarios plus earlier kernel/VM/queue/firmware regressions. Every native
event transcript, exact C++/ABI/header hashes, eight runner outcomes and
33 patch/header input hashes were independently checked; see
`validation/ci-4d71c0c-native-shader.json`. Native job `124447999039`
preflight completed successfully, which requires real-framework C++17
compilation and check-only refusal 4. This is an observed step result;
the full native build and detailed binary/hash reports remain unverified.
No probe has executed GPU work on the target laptop.

The first source CI (`41170266892`, code `6cea778`) compiled the actual C++
probe but failed its test accounting for a parsed wrong vendor: the identity
expression reads both properties before comparing values. Malformed vendor
properties short-circuit earlier. The expected trace is corrected without
changing the production identity checks; this failed run is not a full pass.
