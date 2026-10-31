"""Execute actual page-table allocation/walking against explicit host-only descriptors."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare

METHODS = ('ptTable', 'ptTablePhys', 'vmPte', 'vmidAlloc')
CASES = (
    'root-fresh', 'root-cached', 'root-reused', 'root-allocation-fails', 'root-busy',
    'root-stopping', 'root-stops-after-lock', 'root-invalid-cached', 'root-skips-invalid',
    'backing-null', 'backing-zero-size', 'backing-bad-size', 'backing-null-output',
    'allocate-next-chunk', 'allocate-last-page', 'allocate-capacity', 'allocate-skipped-index',
    'allocate-large-pages', 'allocate-used-overflow', 'allocate-missing-prefix',
    'allocate-stale-physical', 'allocate-cached', 'allocate-partial-retry',
    'lookup-root', 'lookup-last-used', 'lookup-unused', 'lookup-end', 'lookup-before',
    'lookup-misaligned', 'lookup-high', 'lookup-zero', 'lookup-no-used', 'lookup-used-overflow',
    'lookup-pages-overflow', 'lookup-missing-chunk', 'lookup-changed-physical', 'lookup-alias',
    'walk-allocate', 'walk-read', 'walk-no-allocate', 'walk-low-last-byte', 'walk-high-va',
    'walk-zero-root', 'walk-root-mismatch', 'walk-capacity', 'walk-partial-allocation',
    'walk-poisoned-invalid', 'walk-zero-child', 'walk-foreign-child', 'walk-unused-child',
    'walk-root-cycle', 'walk-parent-cycle', 'walk-three-level-cycle', 'walk-repeat',
    'walk-sibling', 'walk-distant', 'walk-last-va',
) + tuple(f'{kind}-{mode}' for kind in ('fresh', 'cached', 'lookup') for mode in (
    'short-length', 'long-length', 'null-cpu', 'unaligned-cpu', 'cpu-overflow',
    'zero-physical', 'unaligned-physical', 'high-physical', 'physical-overflow', 'short-segment',
)) + tuple(f'walk-bad-flags-{bit}' for bit in (1, 2, 3, 7, 11, 48, 63)) + (
    'fresh-physical-alias', 'fresh-cpu-alias', 'cached-physical-alias', 'cached-cpu-alias',
)


def extract_source(source):
    pieces, hashes = [], {}
    for name in ('phxPtBacking',) + METHODS:
        prefix = r'static bool ' if name == 'phxPtBacking' else r'[^\n]*\bPhxBringup::'
        rows = re.findall(r'^' + prefix + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
        if len(rows) != 1:
            raise RuntimeError('Expected exactly one actual page-table method: ' + name)
        pieces.append(rows[0])
        hashes[name] = hashlib.sha256(rows[0].encode()).hexdigest()
    constants = [line for line in source.splitlines() if line.startswith('static constexpr uint64_t kPtAddrMask')]
    if len(constants) != 1:
        raise RuntimeError('Expected actual page-table address mask')
    declarations = []
    for prefix in ('    static constexpr uint32_t kPtChunkBytes', '    static constexpr uint32_t kMaxCtx'):
        rows = [line for line in source.splitlines() if line.startswith(prefix)]
        if len(rows) != 1:
            raise RuntimeError('Expected actual page-table constant: ' + prefix)
        declarations.append(rows[0])
    rows = re.findall(r'^    struct VmCtx \{.*?^    \};', source, re.M | re.S)
    if len(rows) != 1:
        raise RuntimeError('Expected actual page-table context')
    declarations.append(rows[0])
    return '\n'.join(constants), '\n'.join(declarations), '\n'.join(pieces), hashes


def check_result(result, case):
    if result.returncode != 0:
        raise RuntimeError(f'Page-table assertion failed ({case}): {result.stderr}')
    row = json.loads(result.stdout)
    if (not isinstance(row, dict) or set(row) != {'case', 'passed', 'hardware_executed'} or
            row['case'] != case or row['passed'] is not True or row['hardware_executed'] is not False):
        raise RuntimeError('Unexpected page-table assertion report')
    return row


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Page-table tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'
    provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, declarations, methods, hashes = extract_source(source)
    for name, text in [('pt-constants.inc', constants), ('pt-structures.inc', declarations), ('pt-methods.inc', methods)]:
        (out / name).write_text(text + '\n', encoding='utf-8')
    binary = out / 'page-tables-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    str(ROOT / 'tests/test_page_tables.cpp'), '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_page_table_method_sha256': hashes,
              'actual_page_table_declarations_sha256': hashlib.sha256((constants + '\n' + declarations).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual backing validation, allocation, page-table lookup/walk and context allocation; fake IOKit descriptors, CPU storage, physical segments, flushes, locks, readiness and reaping. No target GPUVM, DMA/IOMMU coherency or GPU execution proof.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
