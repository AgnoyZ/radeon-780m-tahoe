"""Run actual page walks, mapping and client retirement together with explicit OS fakes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare
from test_bo_retirement import extract_source as extract_bo

PT_METHODS = ('ptTable', 'ptTablePhys', 'vmPte')
CORRUPTIONS = ('root-mismatch', 'null-cpu', 'short-descriptor', 'changed-physical', 'bad-flags',
               'invalid-entry', 'foreign-child', 'unused-child', 'cycle', 'zero-child', 'missing-chunk')
CASES = (
    'status-absent', 'status-present', 'status-capacity', 'status-corrupt', 'status-no-output',
    'map-real', 'unmap-real', 'free-real', 'unmap-empty', 'map-unbound-real', 'free-busy-real',
    'map-conflicting-leaf', 'map-oom', 'map-partial-oom', 'map-rollback-success',
    'map-corrupt-after-preflight', 'map-corrupt-after-first-write', 'map-rollback-missing-branch',
    'map-rollback-invalid-branch', 'map-rollback-leaf-mismatch', 'map-rollback-segment-changed',
    'map-rollback-segment-unavailable', 'submit-corrupt-map',
    'map-leaf-became-occupied', 'map-rollback-timeout', 'unmap-timeout-real',
    'unmap-late-corrupt', 'unmap-changes-during-clear', 'free-host-corrupt',
    'map-corrupt-leaf-invalid', 'unmap-corrupt-leaf-invalid',
    'unmap-corrupt-leaf-flags', 'unmap-corrupt-leaf-zero-physical',
) + tuple(f'{operation}-corrupt-{mode}' for operation in ('map', 'unmap') for mode in CORRUPTIONS)


def extract_source(source):
    constants, shared, declarations, maps, methods, hashes = extract_bo(source)
    page_methods = []
    for name in ('phxPtBacking',) + PT_METHODS:
        prefix = r'static bool ' if name == 'phxPtBacking' else r'[^\n]*\bPhxBringup::'
        rows = re.findall(r'^' + prefix + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
        if len(rows) != 1:
            raise RuntimeError('Expected exactly one actual walk/cleanup method: ' + name)
        page_methods.append(rows[0])
        hashes[name if name == 'phxPtBacking' else 'PhxBringup::' + name] = hashlib.sha256(rows[0].encode()).hexdigest()
    return constants, shared, declarations, maps, methods, '\n'.join(page_methods), hashes


def check_result(result, case):
    if result.returncode != 0:
        raise RuntimeError(f'Walk/cleanup assertion failed ({case}): {result.stderr}')
    row = json.loads(result.stdout)
    if (not isinstance(row, dict) or set(row) != {'case', 'passed', 'hardware_executed'} or
            row['case'] != case or row['passed'] is not True or row['hardware_executed'] is not False):
        raise RuntimeError('Unexpected walk/cleanup assertion report')
    return row


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Walk/cleanup tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'
    provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, shared, declarations, maps, methods, page_methods, hashes = extract_source(source)
    for name, text in [('bo-constants.inc', constants), ('bo-shared.inc', shared),
                       ('bo-structures.inc', declarations), ('bo-maps.inc', maps),
                       ('bo-methods.inc', methods), ('walk-methods.inc', page_methods)]:
        (out / name).write_text(text + '\n', encoding='utf-8')
    binary = out / 'vm-walk-cleanup-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_vm_walk_cleanup.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_walk_cleanup_method_sha256': hashes,
              'actual_walk_cleanup_declarations_sha256': hashlib.sha256((constants + shared + declarations + maps).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual page-table backing/allocator/walker together with actual map/unmap and client BO/map retirement. Descriptors, CPU backing, physical segments, flushes, MMIO, locks, completion observations and downstream submission are fakes. Deliberate state changes are fault injection, not a hardware concurrency or DMA/IOMMU proof.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
