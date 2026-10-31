"""Execute actual kernel VM binding and GPU submission with explicit host fakes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare

METHODS = ('vmFlushTlb', 'vmBindingValid', 'vmBind', 'ringPut', 'gpuSubmit')
CASES = tuple(f'flush-{i}' for i in range(8, 16)) + (
    'flush-zero', 'flush-low', 'flush-high', 'flush-shift32', 'flush-max', 'flush-no-mmio',
    'flush-last', 'flush-timeout', 'flush-wrong-vmid', 'flush-all-ones',
    'bind-first', 'bind-cached', 'bind-zero', 'bind-high', 'bind-inactive', 'bind-no-mmio',
    'bind-zero-root', 'bind-misaligned-root', 'bind-high-root', 'bind-tick-overflow',
    'bind-cached-low', 'bind-cached-high', 'bind-cached-owner', 'bind-invalid-victim',
    'bind-inactive-victim', 'bind-mismatched-victim', 'bind-all-busy', 'bind-retired-lru', 'bind-late-retirement',
    'bind-timeout', 'bind-cached-timeout', 'bind-retry-timeout', 'bind-all-ones',
    'submit-first', 'submit-cached', 'submit-timeout', 'submit-all-ones', 'submit-bad-root',
    'submit-retry-timeout',
    'submit-sequence-exhausted', 'submit-wptr-exhausted', 'submit-stopping',
) + tuple(f'{mode}-readback-{i}' for mode in ('bind', 'cached', 'submit') for i in range(7))


def extract_source(source):
    pieces, hashes = [], {}
    for name in METHODS:
        found = re.findall(r'^(?:bool|uint32_t|void|IOReturn) PhxBringup::' + name + r'\([^\n]*\)(?: const)? \{.*?^\}\n', source, re.M | re.S)
        if len(found) != 1:
            raise RuntimeError('Expected exactly one actual method: ' + name)
        pieces.append(found[0]); hashes[name] = hashlib.sha256(found[0].encode()).hexdigest()
    declarations = []
    for name in ('GpuQueue', 'VmCtx', 'HwVmid'):
        found = re.findall(r'^    struct ' + name + r' \{.*?^    \};', source, re.M | re.S)
        if len(found) != 1: raise RuntimeError('Expected actual structure: ' + name)
        declarations.append(found[0])
    for prefix in ('    static constexpr uint32_t kPtChunkBytes', '    static constexpr uint32_t kMaxCtx', '    VmCtx *vmCtx'):
        found = [line for line in source.splitlines() if line.startswith(prefix)]
        if len(found) != 1: raise RuntimeError('Expected actual declaration: ' + prefix)
        declarations.insert(0, found[0])
    # Define constants before the structures and keep the inline lookup inside the fake class.
    constants = [line for line in source.splitlines() if any(line.startswith(prefix) for prefix in (
        'static constexpr uint32_t kFirstUserVmid', 'static constexpr uint64_t kPtAddrMask',
        'static constexpr uint32_t kRegCtx0Cntl', 'static constexpr uint32_t kRegInvEng17Req'))]
    if len(constants) != 4: raise RuntimeError('Expected exact register/VMID constant declarations')
    return '\n'.join(constants), '\n'.join(declarations[1:]) + '\n' + declarations[0], '\n'.join(pieces), hashes


def check_result(result, case):
    if result.returncode != 0:
        raise RuntimeError(f'VM binding assertion failed ({case}): {result.stderr}')
    value = json.loads(result.stdout)
    if (not isinstance(value, dict) or set(value) != {'case', 'passed', 'hardware_executed'} or
            value['case'] != case or value['passed'] is not True or value['hardware_executed'] is not False):
        raise RuntimeError('Unexpected VM binding assertion report')
    return value


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('VM binding tests require POSIX Clang; not a native pass on this host')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'; provenance = prepare(stage)
    source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')
    constants, declarations, methods, hashes = extract_source(source)
    for name, text in [('vm-constants.inc', constants), ('vm-structures.inc', declarations), ('vm-methods.inc', methods)]:
        (out / name).write_text(text + '\n')
    binary = out / 'vm-binding-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_vm_binding.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    rows = [check_result(subprocess.run([str(binary), case], text=True, capture_output=True, timeout=15), case) for case in CASES]
    result = {'source_provenance': provenance, 'actual_vm_method_sha256': hashes,
              'actual_vm_declarations_sha256': hashlib.sha256((constants + '\n' + declarations).encode()).hexdigest(),
              'cases': rows, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual binding, invalidation, ring writer and submission methods; fake registers, mappings, locks, queue fences and retirement observations. Not target GPUVM, MES invalidation, or lifetime validation.'}
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    exercise(parser.parse_args().out)
