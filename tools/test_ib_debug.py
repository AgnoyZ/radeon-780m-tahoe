"""Reproduce and bound actual native-submit debug reads without target hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, prepare
from test_bo_retirement import extract_source

CROSS_PREFIXES = tuple(range(1, 17)) + (31, 32, 63, 64, 95, 96, 97)
LENGTHS = tuple(range(1, 10)) + (15, 16, 95, 96, 97, 128)
CASES = tuple(f'cross-{n}' for n in CROSS_PREFIXES) + tuple(f'length-{n}' for n in LENGTHS) + (
    'offset-map', 'multi-two', 'multi-max', 'graphics', 'debug-disabled', 'emission-limit', 'emission-last',
    'opaque-first', 'opaque-peer', 'descriptor-prefix', 'descriptor-offset-end', 'descriptor-offset-past',
    'bo-prefix', 'offset-overflow', 'pointer-offset-overflow', 'pointer-span-overflow', 'pointer-unaligned', 'missing-md')


def expected_result(case, variant):
    if case not in CASES or variant not in ('low', 'upper'): raise ValueError('Unknown IB diagnostic scenario')
    ibs = 64 if case == 'multi-max' else 2 if case == 'multi-two' else 1
    if case.startswith('cross-'): words = min(96, int(case.split('-')[1]))
    elif case.startswith('length-'): words = min(96, int(case.split('-')[1]))
    elif case in ('offset-map', 'multi-two', 'multi-max', 'graphics', 'emission-last', 'opaque-peer', 'descriptor-prefix', 'bo-prefix'):
        words = 1
    else: words = 0
    return {'case': case, 'variant': variant, 'log_rows': ((words + 7) // 8) * ibs,
            'prefix_words': words, 'ibs': ibs, 'submissions': int(case != 'missing-md'), 'passed': True, 'hardware_executed': False}


def check_result(result, case, variant):
    if result.returncode != 0: raise RuntimeError(f'IB debug assertion failed ({variant}/{case}): {result.stderr}')
    row = json.loads(result.stdout)
    expected = expected_result(case, variant)
    if row != expected or any(type(row[key]) is not type(value) for key, value in expected.items()):
        raise RuntimeError(f'IB debug result/count/type mismatch for {case}/{variant}: {row!r}, expected {expected!r}')
    return row


def check_regression(result):
    if result.returncode == 0 or result.stdout or 'AddressSanitizer: heap-buffer-overflow' not in result.stderr:
        raise RuntimeError('Previous actual doSubmit did not reproduce the expected diagnostic overread')
    return {'actual_previous_method_executed': True, 'sanitizer': 'AddressSanitizer: heap-buffer-overflow',
            'case': 'cross-1', 'raw_sanitizer_output_logged': False, 'hardware_executed': False}


def write_extracted(out, source):
    constants, shared, declarations, maps, methods, hashes = extract_source(source)
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (('bo-constants.inc', constants), ('bo-shared.inc', shared),
                        ('bo-structures.inc', declarations), ('bo-maps.inc', maps), ('bo-methods.inc', methods)):
        (out / name).write_text(value + '\n', encoding='utf-8', newline='\n')
    return hashes


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('IB debug tests require POSIX Clang++; not target GPU execution')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('IB debug output exists; choose a fresh directory')
    stage = out / 'stage'; provenance = prepare(stage)
    source_path = stage / 'src/phxbringup/PhxBringup.cpp'
    source_bytes = source_path.read_bytes()
    source = source_path.read_text(encoding='utf-8')
    hashes = write_extracted(out / 'current', source)
    previous = out / 'before-stage'
    previous_source = previous / 'src/phxbringup/PhxBringup.cpp'
    previous_source.parent.mkdir(parents=True)
    previous_source.write_bytes(source_bytes)
    subprocess.run(['git', 'init', '-q', str(previous)], check=True, timeout=30)
    patch = ROOT / 'patches/0027-bounded-ib-debug-reads.patch'
    for arguments in (['--check', '-R'], ['-R']):
        subprocess.run(['git', '-C', str(previous), 'apply', *arguments, str(patch)], check=True, timeout=30)
    old_hashes = write_extracted(out / 'previous', previous_source.read_text(encoding='utf-8'))
    if old_hashes['IOAccelPhxNativeClient::doSubmit'] == hashes['IOAccelPhxNativeClient::doSubmit']:
        raise RuntimeError('Regression build did not remove the actual bounds correction')
    flags = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-g',
             '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(stage / 'src/phxbringup')]
    binaries = {}
    for variant in ('previous', 'current'):
        binary = out / ('ib-debug-' + variant)
        subprocess.run(flags + ['-I' + str(out / variant), str(ROOT / 'tests/test_ib_debug.cpp'), '-o', str(binary)],
                       check=True, timeout=120)
        binaries[variant] = binary
    environment = os.environ.copy()
    environment['ASAN_OPTIONS'] = 'halt_on_error=1:abort_on_error=0:symbolize=0:detect_leaks=1'
    environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=0'
    regression = check_regression(subprocess.run([str(binaries['previous']), 'low', 'cross-1'],
        capture_output=True, text=True, timeout=15, env=environment))
    rows = []
    for variant in ('low', 'upper'):
        for case in CASES:
            rows.append(check_result(subprocess.run([str(binaries['current']), variant, case],
                capture_output=True, text=True, timeout=15, env=environment), case, variant))
    if source_path.read_bytes() != source_bytes: raise RuntimeError('Regression reproduction changed the current stage')
    result = {'source_provenance': provenance, 'actual_ib_debug_method_sha256': hashes,
              'actual_ib_debug_source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'previous_doSubmit_sha256': old_hashes['IOAccelPhxNativeClient::doSubmit'],
              'regression_reproduced': regression, 'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual doSubmit, coverage and client lifecycle methods; fake CPU BOs, metadata, logging and downstream submission. Previous actual method reproduces a heap overread; current diagnostic never claims complete GPU-side BO/IB validation or GPU execution.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    exercise(parser.parse_args().out)
