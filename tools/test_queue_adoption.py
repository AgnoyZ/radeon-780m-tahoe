"""Run the actual kernel queue-adoption method with host-only memory/lock fakes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare

CASES = (
    'compute', 'graphics', 'second-queue', 'adjacent-regions', 'aperture-end', 'doorbell-end',
    'minimum-ring', 'maximum-ring', 'repeated-compute', 'repeated-graphics', 'live-history',
    'null-input', 'no-aperture', 'no-doorbell', 'no-mmio', 'no-mc-base', 'no-gpu-lock', 'no-smu-lock',
    'no-layout', 'psp-fault', 'stopping', 'invalid-layout', 'mc-overflow', 'physical-overflow',
    'ring-zero', 'ring-small', 'ring-large', 'ring-not-power-two', 'ring-misaligned',
    'wb-misaligned', 'fence-bit1', 'fence-bit2', 'doorbell-misaligned',
    'doorbell-overflow', 'doorbell-overrun', 'ring-wb-overlap', 'ring-fence-overlap', 'wb-fence-overlap',
    'shared-doorbell', 'unready-peer',
) + tuple(f'{region}-{failure}' for region in ('ring', 'wb', 'fence')
          for failure in ('overflow', 'narrow', 'cross-32bit', 'aperture-overrun', 'vram-overrun')) + tuple(
    f'{kind}-{candidate}-{occupied}' for kind in ('psp', 'peer')
    for candidate in range(3) for occupied in range(3))


def extract_source(source):
    method = re.findall(r'^IOReturn PhxBringup::adoptQueue\([^\n]*\) \{.*?^\}\n', source, re.M | re.S)
    structure = re.findall(r'^    struct GpuQueue \{.*?^    \};', source, re.M | re.S)
    if len(method) != 1 or len(structure) != 1:
        raise RuntimeError('Expected exactly one actual adoption method and queue structure')
    return structure[0], method[0], hashlib.sha256(method[0].encode()).hexdigest()


def check_result(result, case):
    if result.returncode != 0:
        raise RuntimeError(f'Queue adoption assertion failed ({case}): {result.stderr}')
    report = json.loads(result.stdout)
    if (not isinstance(report, dict) or set(report) != {'case', 'passed', 'hardware_executed'} or
            report['case'] != case or report['passed'] is not True or report['hardware_executed'] is not False):
        raise RuntimeError('Unexpected queue adoption assertion report')
    return report


def exercise(out):
    compiler = shutil.which('clang++')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Actual queue adoption tests require POSIX Clang; not a pass on this host')
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError('Output exists; choose a fresh directory')
    stage = out / 'stage'
    provenance = prepare(stage)
    struct, method, digest = extract_source((stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8'))
    (out / 'queue-structure.inc').write_text(struct + '\n')
    (out / 'queue-adoption.inc').write_text(method)
    binary = out / 'queue-adoption-test'
    subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-g',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(out),
                    '-I' + str(stage / 'src/phxbringup'), str(ROOT / 'tests/test_queue_adoption.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    results = [check_result(subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15), case)
               for case in CASES]
    report = {'source_provenance': provenance, 'actual_adopt_queue_sha256': digest,
              'actual_queue_structure_sha256': hashlib.sha256(struct.encode()).hexdigest(),
              'cases': results, 'hardware_executed': False, 'kernel_loaded': False,
              'limitation': 'Actual kernel method with host memory and locks. No target ownership, hardware idle, HQD, GART or scheduler verification.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    exercise(parser.parse_args().out)
