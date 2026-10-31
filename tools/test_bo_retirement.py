"""Execute actual BO release and mapping methods with explicit host-only OS fakes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare
from test_context_retirement import extract_source as extract_retirement

OWNER_METHODS = ('vmOwnershipKnown', 'vmIdleLocked', 'vmCanReclaim', 'vmMap', 'vmUnmap',
                 'vmFlushTlb', 'vmBindingValid', 'gpuRetired', 'gpuRetiredLocked', 'queueProgress', 'queueFence')
CLIENT_METHODS = ('hasPending', 'reapPending', 'doBoFree', 'boRelease', 'findBo',
                  'doGemVa', 'ibCovered', 'doSubmit')
CASES = (
    'free-busy', 'free-complete', 'free-late-completion', 'free-ack-timeout', 'free-ack-retry',
    'free-aliases', 'free-repeat', 'free-high-handle', 'free-no-vmid', 'free-fence-cleared',
    'free-pool-underflow', 'free-gtt', 'free-hi', 'free-visible', 'free-host', 'free-hidden',
    'free-faulted-peer', 'free-invalid-map-handle', 'free-missing-map-bo', 'free-closed',
    'unmap-busy', 'unmap-timeout', 'unmap-retry', 'unmap-idempotent', 'unmap-overlap',
    'unmap-wrong-handle', 'map-not-ready', 'map-no-owner', 'map-no-vmid', 'map-pending-overlap',
    'map-success', 'map-existing', 'map-ack-timeout', 'map-ack-retry', 'map-partial-rollback',
    'map-rollback-timeout', 'map-rollback-retry', 'map-changed-segment', 'map-first-allocation-fails',
    'map-zero-size', 'map-unaligned-va', 'map-unaligned-off', 'map-unaligned-size', 'map-low-va',
    'map-va-overflow', 'map-bo-overflow', 'map-bo-short', 'map-null-md', 'map-null-cleanup',
    'map-physical-zero', 'map-physical-unaligned', 'map-physical-high', 'map-physical-short',
    'map-busy', 'map-unbound', 'map-no-lock', 'map-no-mmio', 'map-no-aperture', 'map-closing',
    'map-stopping', 'map-invalid-handle', 'map-owner-mismatch', 'map-invalid-hardware-id',
    'map-binding-mismatch', 'map-faulted-peer', 'map-ack-all-ones', 'map-future-fence',
    'unmap-zero-size', 'unmap-unaligned', 'unmap-overflow', 'unmap-no-lock',
    'submit-pending', 'submit-after-reap', 'submit-timeout', 'submit-hidden-ib',
    'submit-pending-ib', 'submit-forwarded', 'coverage-pending', 'coverage-hidden',
    'gem-overflow-offset', 'gem-overflow-size', 'gem-noncanonical',
)


def extract_source(source):
    constants, shared, declarations, _, _ = extract_retirement(source)
    parts, hashes = [], {}
    for klass, names in (('PhxBringup', OWNER_METHODS), ('IOAccelPhxNativeClient', CLIENT_METHODS)):
        for name in names:
            rows = re.findall(r'^[^\n]*\b' + klass + r'::' + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
            if len(rows) != 1: raise RuntimeError('Expected actual method: ' + klass + '::' + name)
            parts.append(rows[0]); hashes[klass + '::' + name] = hashlib.sha256(rows[0].encode()).hexdigest()
    for name in ('shape', 'vaCanonical'):
        rows = re.findall(r'^static [^\n]+\b' + name + r'\([^\n]*\) \{.*?^\}\n', source, re.M | re.S)
        if len(rows) != 1: raise RuntimeError('Expected actual helper: ' + name)
        parts.insert(0, rows[0]); hashes[name] = hashlib.sha256(rows[0].encode()).hexdigest()
    for prefix in ('static constexpr uint64_t kVaMask', 'static constexpr uint64_t kPteSysFlags',
                   'static constexpr int kMaxMaps'):
        rows = [line for line in source.splitlines() if line.startswith(prefix)]
        if len(rows) != 1: raise RuntimeError('Expected actual constant: ' + prefix)
        constants += '\n' + rows[0]
    maps = re.findall(r'^    struct Map \{.*?^    \};', source, re.M | re.S)
    if len(maps) != 1: raise RuntimeError('Expected actual client map structure')
    return constants, shared, declarations, maps[0], '\n'.join(parts), hashes


def check_result(result, case):
    if result.returncode != 0: raise RuntimeError(f'BO retirement assertion failed ({case}): {result.stderr}')
    row = json.loads(result.stdout)
    if (not isinstance(row, dict) or set(row) != {'case', 'passed', 'hardware_executed'} or
            row['case'] != case or row['passed'] is not True or row['hardware_executed'] is not False):
        raise RuntimeError('Unexpected BO retirement assertion report')
    return row


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('BO retirement tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'; provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, shared, declarations, maps, methods, hashes = extract_source(source)
    for name, text in [('bo-constants.inc', constants), ('bo-shared.inc', shared),
                       ('bo-structures.inc', declarations), ('bo-maps.inc', maps), ('bo-methods.inc', methods)]:
        (out / name).write_text(text + '\n', encoding='utf-8')
    binary = out / 'bo-retirement-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_bo_retirement.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_bo_method_sha256': hashes,
              'actual_bo_declarations_sha256': hashlib.sha256((constants + shared + declarations + maps).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual BO, map/unmap, ownership, retirement and client submission methods; fake descriptors, physical segments, page-table allocator, registers, locks and submission transport. No real DMA, page wiring, concurrent hardware or target lifetime validation.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
