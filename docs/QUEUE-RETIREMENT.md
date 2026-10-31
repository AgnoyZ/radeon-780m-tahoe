# Serialized queue completion and submission

Patch `0021-serialized-queue-retirement.patch` places CPU queue-history readers
under the same GPU lock as publication and reclamation. This closes a source
race in the former lock-free `gpuRetired()` walk: readers could overlap changes
to global sequence, ring-history indices and reused entries. Target behavior
has not been tested; this is not evidence of working 780M acceleration.

## Completion snapshot

The public `gpuRetired()` acquires the GPU lock. Binding, idle checks and the
context reaper already hold that lock and call `gpuRetiredLocked()` directly,
avoiding recursive acquisition. No wait loop holds the lock between polls.
Queue selection and context lookup in `gpuSubmit()` move inside the same lock,
including its stopping/readiness checks.

An adopted queue records the current global sequence as its initial retirement
floor, matching the initialized fence. Pruning completed history advances that
floor only to an actually emitted sequence. The shared `queueProgress()` rejects:

- More than 63 live history entries, including malformed index wrap.
- Zero, repeated, descending or future submission sequences.
- A completion below the retired floor, above the global sequence or all ones.
- A completion that is neither the floor nor an emitted sequence in this queue.
- Missing backing, inactive queues, an unaligned fence or a missing output.

The sequence-membership check rejects a value in a gap between this queue's
submissions, including a value emitted only by another queue. It validates all
history entries before exposing completion, even if an earlier entry is pending.
Failed observation returns no completion evidence and cannot prune history.
An absent MMIO/aperture or absence of both adopted queues likewise returns zero.

The fence read uses one aligned native 64-bit volatile load rather than composing
two separate 32-bit observations. This is a CPU access change, not proof of GPU
write atomicity, PCIe ordering or cache coherency on the target machine.

## Submission transaction

Submission validates non-null arrays/output and a nonzero bounded IB count before
computing packet size. It checks the selected power-of-two ring under the lock,
preserves sequence/write-pointer exhaustion refusals, and validates completion
before removing any history entry. History endpoints must increase from the
completed pointer and end at the current write pointer; future/missing/descending
endpoints are refused. Impossible progress therefore cannot fabricate ring space
or reach VM binding, command publication, writeback or a doorbell.

Legitimate ring pressure still waits with the existing bounded polling loop.
VM binding and command emission are otherwise unchanged. A binding refusal may
follow legitimate pruning of already completed history, but does not publish
new commands or advance the global submission sequence.

## Host checks and remaining work

`tools/test_queue_retirement.py` extracts and hashes the actual completion reader,
progress validator, locked/public retirement, ring writer and submission bodies.
Host fakes provide checked mutexes, backing, VM binding and device completion.
Every fake aperture access asserts CPU lock ownership. Cases cover interleaved
queues, high fence words, 32-bit history-index wrap, ring wrap, malformed history,
future/regressed/unissued completions, argument bounds, stopping at acquisition,
pressure timeouts, late completion and exact published command/writeback values.
Two CPU producer threads perform 256 actual-method submissions while another
thread polls retirement; simulated device completion is serialized by the host
fixture. This is not device execution or exhaustive concurrency validation.

Existing BO/context suites execute their new locked dependencies; adoption checks
the initialized floor, and the binding fixture still explicitly fakes retirement
to isolate VMID behavior. Linux CI is configured for ASan/UBSan execution. Native
macOS compilation and host test results must be recorded after verification;
Windows passed all 182 Python source integration and runner-contract checks, plus syntax compilation.

Other driver state/readiness access paths, descriptor completion reentrancy,
active-MES invalidation, actual queue ownership, device reset and unload still
need review and target validation. No deployment, EFI, firmware, OS-security,
NVRAM or disk change is performed. Source rollback uses a separate clean checkout
of the preceding revision; do not strip these checks from a running instance.
