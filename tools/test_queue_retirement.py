"""Execute actual queue submission and serialized retirement with host-only fakes."""
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

METHODS = ('queueFence', 'queueProgress', 'gpuRetiredLocked', 'gpuRetired', 'ringPut', 'gpuSubmit')
CASES = (
    'read-empty', 'read-pending', 'read-complete', 'read-interleaved', 'read-other-pending',
    'read-high-word', 'read-index-wrap', 'read-no-lock', 'read-no-mmio', 'read-no-aperture',
    'read-no-queues', 'read-future-fence', 'read-regressed-fence', 'read-future-floor',
    'read-too-many', 'read-zero-sequence', 'read-future-sequence', 'read-duplicate-sequence',
    'read-descending-sequence', 'read-late-invalid-sequence', 'read-unaligned-fence',
    'read-gap-fence', 'read-fence-after-queue', 'read-all-ones',
    'progress-null-output', 'progress-inactive', 'progress-no-aperture',
    'submit-first', 'submit-retires-history', 'submit-index-wrap', 'submit-ring-wrap',
    'submit-future-fence', 'submit-regressed-fence', 'submit-too-many', 'submit-zero-sequence',
    'submit-gap-fence', 'submit-fence-after-queue',
    'submit-future-sequence', 'submit-duplicate-sequence', 'submit-end-before-done',
    'submit-end-descending', 'submit-end-future', 'submit-end-missing', 'submit-empty-mismatch',
    'submit-zero-count', 'submit-count-overflow', 'submit-null-va', 'submit-null-size',
    'submit-null-output', 'submit-no-lock', 'submit-no-mmio', 'submit-no-aperture',
    'submit-no-doorbell', 'submit-no-queue', 'submit-graphics-unavailable', 'submit-stopping',
    'submit-stop-after-lock', 'submit-invalid-context', 'submit-small-ring', 'submit-nonpower-ring',
    'submit-sequence-exhausted', 'submit-pointer-exhausted', 'submit-history-full', 'submit-ring-full',
    'submit-late-completion', 'submit-bind-refused', 'submit-retired-floor', 'concurrent-submit-retire',
)


def extract_source(source):
    constants, declarations, _, _ = extract_vm(source)
    parts, hashes = [], {}
    for name in METHODS:
        rows = re.findall(r'^(?:uint64_t|void|bool|IOReturn) PhxBringup::' + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
        if len(rows) != 1: raise RuntimeError('Expected actual queue method: ' + name)
        parts.append(rows[0]); hashes[name] = hashlib.sha256(rows[0].encode()).hexdigest()
    ready = [line for line in source.splitlines() if line.startswith('    bool gpuReady() const')]
    if len(ready) != 1: raise RuntimeError('Expected actual readiness declaration')
    return constants, declarations + '\n' + ready[0], '\n'.join(parts), hashes


def check_result(result, case):
    if result.returncode != 0: raise RuntimeError(f'Queue retirement assertion failed ({case}): {result.stderr}')
    row = json.loads(result.stdout)
    if (not isinstance(row, dict) or set(row) != {'case', 'passed', 'hardware_executed'} or
            row['case'] != case or row['passed'] is not True or row['hardware_executed'] is not False):
        raise RuntimeError('Unexpected queue retirement assertion report')
    return row


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Queue retirement tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'; provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, declarations, methods, hashes = extract_source(source)
    for name, text in [('queue-retire-constants.inc', constants), ('queue-retire-structures.inc', declarations),
                       ('queue-retire-methods.inc', methods)]:
        (out / name).write_text(text + '\n', encoding='utf-8')
    binary = out / 'queue-retirement-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g', '-pthread',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_queue_retirement.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=20), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_queue_retirement_method_sha256': hashes,
              'actual_queue_retirement_declarations_sha256': hashlib.sha256((constants + '\n' + declarations).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual submission, ring writer, queue-progress validator and locked/public retirement methods. Fake maps, IOKit locks, VM binding and device completion; CPU threads perform 256 submissions with serialized completion observations. ASan/UBSan is not a GPU coherency or exhaustive kernel-concurrency test; no real DMA or target work.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
