"""Fault-inject the actual native GPUVM acceptance probe; never open a device."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, prepare

PASS = 'PASS: native GPUVM shader probe; two guarded dispatches, not Metal or display acceptance'
CHECK = 'CHECK: target identity and ABI readiness only; no GPU work submitted'


def cases():
    yield from ('ok', 'number-ok', 'create-mappable', 'va-exact', 'check-ok', 'arg-missing', 'arg-mode',
        'arg-option', 'arg-many', 'host-status', 'host-linux', 'host-arm', 'host-sonoma', 'host-prefix',
        'matching-null', 'enumerate-status', 'iterator-null', 'no-service', 'parent-status', 'non-pci',
        'ambiguous', 'mixed-services', 'release-parent', 'release-iterator', 'release-service',
        'release-open-service', 'open-status', 'open-null', 'hello-abi', 'hello-limit', 'hello-vmid',
        'info-abi', 'info-minor', 'info-build', 'info-vmid', 'info-gc', 'info-limit', 'info-hung',
        'info-not-native', 'info-not-ready', 'va-unaligned', 'va-reversed', 'va-short', 'va-hole',
        'va-noncanonical', 'va-null', 'va-wrap', 'va-low-wide', 'ctx-alloc-zero', 'ctx-alloc-wide',
        'ctx-alloc-flags', 'ctx-alloc-id', 'ctx-alloc-priority', 'create-zero', 'create-wide',
        'create-limit', 'create-size', 'create-domain', 'create-unzeroed', 'create-bits', 'cpu-map-zero',
        'cpu-map-unaligned', 'cpu-map-wrap', 'cpu-map-short', 'cpu-map-long', 'cpu-map-status',
        'gpu-map-status', 'cpu-unmap-status', 'gpu-unmap-status', 'free-status', 'close-status',
        'ctx-free-nonzero', 'ctx-free-flags', 'ctx-free-id', 'ctx-free-priority', 'submit-2-repeat')
    for field in ('vendor', 'device'):
        for suffix in ('missing', 'wrong', 'negative', 'wide', 'number-status', 'type', 'short', 'long', 'null'):
            yield f'{field}-{suffix}'
    for operation in ('hello', 'info', 'ctx-alloc', 'create', 'ctx-free', 'submit-1', 'submit-2', 'wait-1', 'wait-2'):
        for suffix in ('status', 'short', 'long'):
            yield f'{operation}-{suffix}'
    for stage in (1, 2):
        for suffix in ('zero', 'last'):
            yield f'submit-{stage}-{suffix}'
        for suffix in ('timeout', 'retired', 'last', 'emitted', 'missing'):
            yield f'wait-{stage}-{suffix}'
        for prefix, count in (('code', 79), ('ib', 80), ('output', 256)):
            for index in range(count): yield f'{prefix}-{stage}-{index}'
        for offset in (316, 4095, 4416, 8191, 8192, 8207, 9232, 12287, 12288, 16383):
            yield f'byte-{stage}-{offset}'


CASES = tuple(cases())
CASE_SET = frozenset(CASES)


def expected_result(fault):
    if fault not in CASE_SET: raise ValueError('Unknown native probe test case')
    e = []
    if fault.startswith('arg-'): return 64, e
    e.append('host')
    if fault.startswith('host-'): return 4, e
    e.append('matching')
    if fault == 'matching-null': return 4, e
    e.append('enumerate')
    if fault in ('enumerate-status', 'iterator-null'): return 74, e
    if fault == 'no-service': return 4, e + ['release-iterator']
    if fault == 'mixed-services': e += ['parent', 'release-parent', 'release-service']
    e.append('parent')
    if fault == 'parent-status': return 4, e + ['release-service', 'release-iterator']
    if fault == 'non-pci': return 4, e + ['release-parent', 'release-service', 'release-iterator']
    e.append('vendor')
    if fault.startswith('vendor-'): return 4, e + ['release-parent', 'release-service', 'release-iterator']
    e.append('device')
    if fault.startswith('device-'): return 4, e + ['release-parent', 'release-service', 'release-iterator']
    e.append('release-parent')
    if fault == 'ambiguous':
        return 4, e + ['parent', 'vendor', 'device', 'release-parent', 'release-service', 'release-iterator', 'release-service']
    e.append('release-iterator')
    if fault in ('release-parent', 'release-iterator'): return 74, e + ['release-service']
    e += ['open', 'release-service']
    if fault in ('open-status', 'open-null'): return 74, e
    if fault in ('release-service', 'release-open-service'): return 74, e + ['close']
    mapped = False

    def stop(code): return code, e + (['cpu-unmap'] if mapped else []) + ['close']

    def transport(name): return fault in (name + '-status', name + '-short', name + '-long')

    e.append('hello')
    if transport('hello'): return stop(74)
    if fault.startswith('hello-'): return stop(75)
    e.append('info')
    if transport('info'): return stop(74)
    if fault.startswith('info-'): return stop(75)
    if fault == 'check-ok': return stop(0)
    if fault.startswith('va-') and fault != 'va-exact': return stop(75)
    e.append('ctx-alloc')
    if transport('ctx-alloc'): return stop(74)
    if fault.startswith('ctx-alloc-'): return stop(75)
    e.append('create')
    if transport('create'): return stop(74)
    if fault.startswith('create-') and fault != 'create-mappable': return stop(75)
    e.append('cpu-map')
    if fault == 'cpu-map-status': return stop(74)
    mapped = True
    if fault.startswith('cpu-map-'): return stop(75)
    e.append('gpu-map')
    if fault == 'gpu-map-status': return stop(74)
    for stage in (1, 2):
        submit, wait = f'submit-{stage}', f'wait-{stage}'
        e.append(submit)
        if transport(submit): return stop(74)
        if fault.startswith(submit + '-'): return stop(75)
        e.append(wait)
        if transport(wait): return stop(74)
        if fault.startswith(wait + '-') or any(fault.startswith(f'{prefix}-{stage}-') for prefix in ('code', 'ib', 'output', 'byte')):
            return stop(75)
    e.append('cpu-unmap'); mapped = False
    if fault == 'cpu-unmap-status': return stop(74)
    for name in ('gpu-unmap', 'free', 'ctx-free'):
        e.append(name)
        if transport(name): return stop(74)
        if fault.startswith(name + '-'): return stop(75)
    return stop(74 if fault == 'close-status' else 0)


def check_result(result, fault):
    status, events = expected_result(fault)
    prefix = 'fake-native-shader-summary '
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f'Native shader probe assertion failed ({fault}): {result.returncode}: {result.stderr}')
    observed = json.loads(rows[0])
    if observed != {'events': events}: raise RuntimeError(f'Unexpected native continuation ({fault}): {observed}; expected {events}')
    marker = CHECK if fault == 'check-ok' else PASS
    if result.stdout.strip() != (marker if status == 0 else ''): raise RuntimeError('Incorrect native shader completion claim')
    return observed


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Native shader simulation requires POSIX Clang++; not a hardware test')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Native shader output exists; choose a fresh directory')
    stage = out / 'stage'
    provenance = prepare(stage)
    source = ROOT / 'tools/native_shader_probe.cpp'
    header = stage / 'tools/phxctl/gfx11_shader_probe.h'
    binary = out / 'native-shader-simulation'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g', '-fsanitize=address,undefined',
        '-fno-sanitize-recover=all', '-I' + str(ROOT / 'tests/fake_native_iokit'),
        '-I' + str(stage / 'src/phxbringup'), '-I' + str(header.parent),
        str(ROOT / 'tests/test_native_shader_probe.cpp'), '-o', str(binary)], check=True, timeout=120)
    results = []
    for variant in ('low', 'upper'):
        for fault in CASES:
            result = subprocess.run([str(binary), variant, fault], capture_output=True, text=True, timeout=15)
            results.append({'variant': variant, 'case': fault, **check_result(result, fault)})
    report = {'source_provenance': provenance, 'actual_native_probe_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'actual_shader_header_sha256': hashlib.sha256(header.read_bytes()).hexdigest(), 'cases': results,
        'hardware_executed': False, 'shader_executed': False, 'native_iokit_linked': False,
        'limitation': 'Actual C++ probe with fake IOKit/CF ABI, independent packet/arena checks and injected writes. No ISA interpreter, GPUVM translation, firmware or target device execution.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    exercise(parser.parse_args().out)
