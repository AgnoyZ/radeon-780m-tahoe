"""Execute actual deferred context/client cleanup with explicit host-only OS fakes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare
from test_vm_binding import extract_source as extract_vm

OWNER_METHODS = ('vmOwnershipKnown', 'vmFlushTlb', 'deferClient', 'reapContexts', 'reapContextsLocked',
                 'vmidAlloc', 'queueFence', 'gpuRetired', 'stop')
CLIENT_METHODS = ('boRelease', 'freeAll', 'closeResources', 'clientClose', 'free',
                  'findBo', 'clientMemoryForType', 'doWaitSeq')
CASES = (
    'defer-pending', 'defer-complete', 'late-completion', 'zero-submissions', 'driver-last-sequence',
    'client-last-sequence', 'ack-timeout', 'ack-retry', 'ack-all-ones', 'disable-mismatch', 'disable-retry',
    'no-aperture', 'no-mmio', 'no-queues', 'future-fence', 'two-queues-pending', 'two-queues-complete',
    'unbound-context', 'faulted-peer', 'faulted-peer-recovered', 'invalid-owner', 'invalid-hardware-id',
    'invalid-pages', 'missing-chunk', 'partial-last-chunk', 'double-reap', 'alloc-pending', 'alloc-reclaims',
    'bad-handle', 'inactive-handle', 'future-client-sequence', 'duplicate-close-transfer', 'no-lock-quarantine',
    'atomic-quarantine-retry', 'client-close-pending', 'client-close-complete', 'client-destructor-pending',
    'client-close-then-free', 'client-repeat-close', 'client-no-vmid', 'client-memory-after-close',
    'wait-after-close', 'close-during-wait', 'stop-active', 'stop-pending', 'stop-faulted', 'stop-orphan',
    'stop-cold', 'stop-repeat', 'host-pins-preserved', 'mixed-buffer-release', 'empty-buffer-container',
    'alloc-stopping-after-lock', 'unbound-peer-invalid-hardware', 'client-pending-bo-close',
)


def extract_source(source):
    constants, declarations, _, _ = extract_vm(source)
    shared = []
    for name in ('PhxClientBo', 'PhxRetiredBuffers'):
        rows = re.findall(r'^struct ' + name + r' \{.*?^\};', source, re.M | re.S)
        if len(rows) != 1: raise RuntimeError('Expected shared ownership structure: ' + name)
        shared.append(rows[0])
    parts, hashes = [], {}
    for klass, names in (('PhxBringup', OWNER_METHODS), ('IOAccelPhxNativeClient', CLIENT_METHODS)):
        for name in names:
            rows = re.findall(r'^[^\n]*\b' + klass + r'::' + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
            if len(rows) != 1: raise RuntimeError('Expected actual method: ' + klass + '::' + name)
            parts.append(rows[0]); hashes[klass + '::' + name] = hashlib.sha256(rows[0].encode()).hexdigest()
    for name in ('phxReleaseBuffers', 'shape'):
        rows = re.findall(r'^static [^\n]+\b' + name + r'\([^\n]*\) \{.*?^\}\n', source, re.M | re.S)
        if len(rows) != 1: raise RuntimeError('Expected actual helper: ' + name)
        parts.insert(0, rows[0]); hashes[name] = hashlib.sha256(rows[0].encode()).hexdigest()
    inline = [line for line in source.splitlines() if line.startswith('    bool gpuReady() const')]
    if len(inline) != 1: raise RuntimeError('Expected actual readiness gate')
    declarations += '\n' + inline[0]
    return constants, '\n'.join(shared), declarations, '\n'.join(parts), hashes


def check_result(result, case):
    if result.returncode != 0: raise RuntimeError(f'Retirement assertion failed ({case}): {result.stderr}')
    row = json.loads(result.stdout)
    if (not isinstance(row, dict) or set(row) != {'case', 'passed', 'hardware_executed'} or
            row['case'] != case or row['passed'] is not True or row['hardware_executed'] is not False):
        raise RuntimeError('Unexpected retirement assertion report')
    return row


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Retirement tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'; provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, shared, declarations, methods, hashes = extract_source(source)
    for name, text in [('retire-constants.inc', constants), ('retire-shared.inc', shared),
                       ('retire-structures.inc', declarations), ('retire-methods.inc', methods)]:
        (out / name).write_text(text + '\n')
    binary = out / 'context-retirement-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_context_retirement.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_retirement_method_sha256': hashes,
              'actual_retirement_declarations_sha256': hashlib.sha256((constants + shared + declarations).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual ownership transfer, reaping, close/free, wait and stop methods with fake IOKit, registers and fence storage. No actual DMA, page wiring, concurrency stress, reset or target hardware proof.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
