"""Run the actual GFX11 shader-probe CLI with explicit fake GPU observations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, prepare
from test_compute_probe import WORK_LAYOUT_FAILURES
from test_mes_queue import LAYOUT_FAILURES

MARKER = "GFX11 shader probe: 1024-byte buffer-clear output and full-width release fence observed; Metal and display unverified"


def cases():
    yield from ("ok", "work-adjacent", "arg-count", "arg-unaligned", "arg-overflow", "arg-wide", "arg-bell-odd",
        "arg-bell-wide", "arg-work-unaligned", "arg-work-bell-odd", "env-mc", "env-adopt", "no-service", "open-status",
        "hello-status", "hello-short", "hello-abi", "snapshot-status", "snapshot-short", *LAYOUT_FAILURES,
        *WORK_LAYOUT_FAILURES, "work-sixth-page-overlap", "cp-busy", "rlc-not-ready", "mes-inactive", "mes-all-ones",
        "selection-busy", "hqd-active", "hqd-all-ones", "work-hqd-active", "work-hqd-all-ones", "read-short",
        "write-short", "vread-short", "delay-error", "delay-eintr", "timeout", "fence-high", "bad-token", "token-high",
        "bell-1", "bell-2", "bell-3", "add-timeout", "add-bad-token", "work-bell", "work-delay-error", "work-eintr",
        "work-timeout", "work-fence-low", "work-fence-high", "work-delayed", "work-fence-changed", "work-missing-data",
        "work-guard-before", "work-guard-after", "work-data-high", "close-status")
    for prefix, count in (("read", 65), ("write", 37), ("vread", 196), ("vbad", 13)):
        for i in range(1, count + 1):
            yield f"{prefix}-{i}"
    for i in (*range(3, 16), 18, 20, 21, 23, *range(26, 40), *range(52, 66)):
        yield f"bad-{i}"
    for i in (1, 4096, 5694, 5828, 5962, 5963, 9034, 12206, 12207, 12748, 12749, 12782,
              *range(12783, 12862), 12862, 12869, 12870, 13125, 13126, 13127, *range(13128, 13216)):
        yield f"vwrite-{i}"
    for i in range(40): yield f"shader-code-{i}"
    for i in range(256): yield f"shader-output-{i}"
    for i in range(4): yield f"shader-guard-{i}"


def expected_result(fault):
    c = dict.fromkeys(("lookups", "opens", "hellos", "snapshots", "reads", "writes", "vreads", "vwrites",
        "bells", "sleeps", "closes", "work_bells"), 0)
    if fault.startswith(("arg-", "env-")): return 64, c
    c['lookups'] = 1
    if fault == 'no-service': return 1, c
    c['opens'] = 1
    if fault == 'open-status': return 1, c
    c['hellos'] = 1
    if fault in ('hello-status', 'hello-short'): return 74, c
    if fault == 'hello-abi':
        c['closes'] = 1
        return 1, c
    c['snapshots'] = 1
    if fault in ('snapshot-status', 'snapshot-short'): return 74, c
    if fault in (*LAYOUT_FAILURES, *WORK_LAYOUT_FAILURES, 'work-sixth-page-overlap'): return 75, c
    events, totals = [], dict(c)

    def emit(field, count):
        for _ in range(count):
            totals[field] += 1
            events.append((field, totals[field]))

    def verify_hqd():
        emit('writes', 1); emit('reads', 13); emit('writes', 1); emit('reads', 1)

    def submit():
        emit('vwrites', 134); emit('bells', 1); emit('sleeps', 1); emit('vreads', 3)
        emit('writes', 1); emit('reads', 4); emit('writes', 1)

    emit('reads', 15); emit('vreads', 13); emit('reads', 2)
    for _ in range(2):
        emit('writes', 1); emit('reads', 2); emit('writes', 1); emit('reads', 1)
    emit('vwrites', 5694)
    emit('writes', 22); emit('reads', 2); emit('writes', 1)
    verify_hqd(); submit(); submit()
    emit('vwrites', 6686); submit(); verify_hqd()
    emit('vwrites', 79); emit('vreads', 40)
    emit('vwrites', 354); emit('work_bells', 1)
    for field, index in events:
        c[field] = index
        if field in ('reads', 'writes', 'vreads', 'vwrites', 'bells'):
            if fault in (f'{field[:-1]}-{index}', f'{field[:-1]}-short'): return 74, c
        if field == 'reads':
            if fault == f'bad-{index}': return 75, c
            if index == 2 and fault in ('cp-busy', 'rlc-not-ready'): return 75, c
            if index == 16 and fault in ('mes-inactive', 'mes-all-ones'): return 75, c
            if index == 17 and fault == 'selection-busy': return 75, c
            if index == 19 and fault in ('hqd-active', 'hqd-all-ones'): return 75, c
            if index == 22 and fault in ('work-hqd-active', 'work-hqd-all-ones'): return 75, c
        if field == 'vreads':
            if fault == f'vbad-{index}': return 75, c
            if index == 16 and fault in ('bad-token', 'token-high'): return 75, c
            if index == 22 and fault == 'add-bad-token': return 75, c
            if index == 14 and fault in ('timeout', 'fence-high'):
                c.update(vreads=415, sleeps=400)
                return 75, c
            if index == 20 and fault == 'add-timeout':
                c.update(vreads=421, sleeps=402)
                return 75, c
            if 23 <= index <= 62 and fault == f'shader-code-{index - 23}': return 75, c
        if field == 'sleeps' and fault == 'delay-error': return 74, c
        if field == 'work_bells' and fault == 'work-bell': return 74, c
    c['sleeps'] += 1
    if fault == 'work-delay-error': return 74, c
    polls = 3 if fault == 'work-delayed' else 400 if fault in ('work-timeout', 'work-fence-low', 'work-fence-high') else 1
    c['sleeps'] += polls - 1
    c['vreads'] += polls
    if fault == 'vread-63': return 74, c
    if polls == 400: return 75, c
    c['vreads'] += 1
    if fault == 'vread-64': return 74, c
    if fault == 'work-fence-changed': return 75, c
    for i in range(128):
        c['vreads'] += 1
        if fault == f"vread-{c['vreads']}": return 74, c
        if fault in (f'shader-output-{2 * i}', f'shader-output-{2 * i + 1}') or (
            i == 0 and fault in ('work-missing-data', 'work-data-high')): return 75, c
    for i in range(4):
        c['vreads'] += 1
        if fault == f"vread-{c['vreads']}": return 74, c
        if fault == f'shader-guard-{i}' or (i == 0 and fault == 'work-guard-before') or (
            i == 2 and fault == 'work-guard-after'): return 75, c
    c['closes'] = 1
    return (74 if fault == 'close-status' else 0), c


def check_result(result, fault):
    status, expected = expected_result(fault)
    prefix = 'fake-mes-queue-summary '
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f'Shader probe assertion failed ({fault}): {result.returncode}: {result.stderr}')
    observed = json.loads(rows[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError(f'Incorrect shader continuation/counts ({fault}): {observed}, expected {expected}')
    if (MARKER in result.stdout) != (status == 0): raise RuntimeError('Incorrect shader completion claim')
    return observed


def exercise(out):
    compiler = shutil.which('clang')
    if platform.system() not in ('Linux', 'Darwin') or not compiler:
        raise RuntimeError('Shader probe tests require POSIX Clang; not hardware execution')
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError('Shader probe output exists; choose a fresh directory')
    stage = out / 'stage'
    provenance = prepare(stage)
    source = stage / 'tools/phxctl/mesboot.c'
    header = source.parent / 'gfx11_shader_probe.h'
    binary = out / 'shader-probe-test'
    flags = [compiler, '-std=c11', '-D_DEFAULT_SOURCE', '-Wall', '-Wextra', '-I' + str(ROOT / 'tests/fake_iokit')]
    subprocess.run(flags + ['-fsyntax-only', str(source)], check=True, timeout=60)
    subprocess.run(flags + ['-DPHX_TEST_SHADER=1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-I' + str(source.parent), str(ROOT / 'tests/test_mes_queue.c'), '-o', str(binary)], check=True, timeout=120)
    environment = os.environ.copy()
    for key in ('PTE_SYS', 'FAULT_DEFAULT', 'MESBOOT_MC', 'MESBOOT_CS', 'MESBOOT_GFX', 'ADOPT', 'ADOPT_GFX'):
        environment.pop(key, None)
    results = []
    for variant in ('baseline', 'relocated'):
        for fault in cases():
            result = subprocess.run([str(binary), variant, fault], capture_output=True, text=True, timeout=15, env=environment)
            results.append({'variant': variant, 'case': fault, **check_result(result, fault)})
    report = {'source_provenance': provenance, 'actual_shader_cli_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'actual_shader_header_sha256': hashlib.sha256(header.read_bytes()).hexdigest(), 'cases': results,
        'standalone_source_compiled': True, 'hardware_executed': False, 'shader_executed': False,
        'limitation': 'Actual shader-probe CLI with fake descriptor geometry, register banks, memory and GPU writes/fences. Exact GFX11 packets and 79-word reference shader checked; no firmware, shader, GPU translation or target device executes.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    exercise(parser.parse_args().out)
