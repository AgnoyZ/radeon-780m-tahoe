"""Run the actual compute-ring CLI with injected completions; never execute a GPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from prepare_source import ROOT, prepare
from test_mes_queue import LAYOUT_FAILURES

MARKER = "compute-ring probe: memory write and full-width release fence observed; shader execution unverified"
WORK_LAYOUT_FAILURES = ("work-arena-scheduler", "work-bell-overlap", "work-arena-table", "work-arena-default",
    "work-arena-ring", "work-arena-tmr", "work-arena-stage", "work-arena-unmapped", "work-last-page-overlap")


def cases():
    yield from ("ok", "work-adjacent", "arg-count", "arg-unaligned", "arg-overflow", "arg-wide", "arg-bell-odd", "arg-bell-wide",
        "arg-work-unaligned", "arg-work-bell-odd", "env-mc", "env-adopt", "no-service", "open-status", "hello-status",
        "hello-short", "hello-abi", "snapshot-status", "snapshot-short", *LAYOUT_FAILURES, *WORK_LAYOUT_FAILURES,
        "cp-busy", "rlc-not-ready", "mes-inactive", "mes-all-ones", "selection-busy", "hqd-active", "hqd-all-ones",
        "work-hqd-active", "work-hqd-all-ones", "read-short", "write-short", "vread-short", "delay-error", "delay-eintr",
        "timeout", "fence-high", "bad-token", "token-high", "bell-1", "bell-2", "bell-3", "add-timeout", "add-bad-token",
        "work-bell", "work-delay-error", "work-eintr", "work-timeout", "work-fence-low", "work-fence-high", "work-delayed",
        "work-fence-changed", "work-missing-data", "work-guard-before", "work-guard-after", "work-data-high", "close-status")
    for i in range(1, 66): yield f"read-{i}"
    for i in range(1, 38): yield f"write-{i}"
    for i in range(1, 27): yield f"vread-{i}"
    for i in range(1, 13): yield f"vbad-{i}"
    for i in (*range(3, 16), 18, 20, 21, 23, *range(26, 40), *range(52, 66)): yield f"bad-{i}"
    for i in (1, 2048, 4096, 5694, 5828, 5962, 5963, 8522, 11082, 11083, 11624, 11625,
              11758, 11759, 11764, 11765, 11766, 11767, 11779, 11780, 11781): yield f"vwrite-{i}"


def expected_result(fault):
    c = dict.fromkeys(("lookups", "opens", "hellos", "snapshots", "reads", "writes", "vreads", "vwrites",
        "bells", "sleeps", "closes", "work_bells"), 0)
    if fault.startswith(("arg-", "env-")): return 64, c
    c["lookups"] = 1
    if fault == "no-service": return 1, c
    c["opens"] = 1
    if fault == "open-status": return 1, c
    c["hellos"] = 1
    if fault in ("hello-status", "hello-short"): return 74, c
    if fault == "hello-abi":
        c["closes"] = 1
        return 1, c
    c["snapshots"] = 1
    if fault in ("snapshot-status", "snapshot-short"): return 74, c
    if fault in (*LAYOUT_FAILURES, *WORK_LAYOUT_FAILURES): return 75, c
    events, totals = [], dict(c)
    def emit(field, count):
        for _ in range(count):
            totals[field] += 1
            events.append((field, totals[field]))
    emit("reads", 15); emit("vreads", 12); emit("reads", 2)
    for _ in range(2):
        emit("writes", 1); emit("reads", 2); emit("writes", 1); emit("reads", 1)
    emit("vwrites", 5694)
    emit("writes", 22); emit("reads", 2); emit("writes", 1)
    def verify_hqd():
        emit("writes", 1); emit("reads", 13); emit("writes", 1); emit("reads", 1)
    def submit():
        emit("vwrites", 134); emit("bells", 1); emit("sleeps", 1); emit("vreads", 3)
        emit("writes", 1); emit("reads", 4); emit("writes", 1)
    verify_hqd(); submit(); submit()
    emit("vwrites", 5662); submit(); verify_hqd()
    emit("vwrites", 23); emit("work_bells", 1)
    for field, index in events:
        c[field] = index
        if field in ("reads", "writes", "vreads", "vwrites", "bells"):
            prefix = field[:-1]
            if fault in (f"{prefix}-{index}", f"{prefix}-short"): return 74, c
        if field == "reads":
            if fault == f"bad-{index}": return 75, c
            if index == 2 and fault in ("cp-busy", "rlc-not-ready"): return 75, c
            if index == 16 and fault in ("mes-inactive", "mes-all-ones"): return 75, c
            if index == 17 and fault == "selection-busy": return 75, c
            if index == 19 and fault in ("hqd-active", "hqd-all-ones"): return 75, c
            if index == 22 and fault in ("work-hqd-active", "work-hqd-all-ones"): return 75, c
        if field == "vreads":
            if fault == f"vbad-{index}": return 75, c
            if index == 15 and fault in ("bad-token", "token-high"): return 75, c
            if index == 21 and fault == "add-bad-token": return 75, c
            if index == 13 and fault in ("timeout", "fence-high"):
                c.update(vreads=414, sleeps=400)
                return 75, c
            if index == 19 and fault == "add-timeout":
                c.update(vreads=420, sleeps=402)
                return 75, c
        if field == "sleeps" and fault == "delay-error": return 74, c
        if field == "work_bells" and fault == "work-bell": return 74, c
    c["sleeps"] += 1
    if fault == "work-delay-error": return 74, c
    polls = 3 if fault == "work-delayed" else 400 if fault in ("work-timeout", "work-fence-low", "work-fence-high") else 1
    c["sleeps"] += polls - 1
    c["vreads"] += polls
    if fault == "vread-22": return 74, c
    if polls == 400: return 75, c
    for check in range(4):
        c["vreads"] += 1
        if fault == f"vread-{c['vreads']}": return 74, c
        failures = (("work-fence-changed",), ("work-guard-before",), ("work-missing-data", "work-data-high"), ("work-guard-after",))
        if fault in failures[check]: return 75, c
    c["closes"] = 1
    return (74 if fault == "close-status" else 0), c


def check_result(result, fault):
    status, expected = expected_result(fault)
    prefix = "fake-mes-queue-summary "
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f"Compute probe failed ({fault}): {result.returncode}: {result.stderr}")
    observed = json.loads(rows[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError(f"Incorrect compute continuation/counts ({fault}): {observed}, expected {expected}")
    if (MARKER in result.stdout) != (status == 0): raise RuntimeError("Incorrect compute-ring completion claim")
    return observed


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler: raise RuntimeError("Compute probe tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("Compute probe test output exists; choose a new directory")
    stage = out / "stage"
    provenance = prepare(stage)
    source = stage / "tools/phxctl/mesboot.c"
    flags = [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-I" + str(ROOT / "tests/fake_iokit")]
    subprocess.run(flags + ["-fsyntax-only", str(source)], check=True, timeout=60)
    binary = out / "compute-probe-test"
    subprocess.run(flags + ["-DPHX_TEST_COMPUTE=1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-I" + str(source.parent), str(ROOT / "tests/test_mes_queue.c"), "-o", str(binary)], check=True, timeout=120)
    environment = os.environ.copy()
    for key in ("PTE_SYS", "FAULT_DEFAULT", "MESBOOT_MC", "MESBOOT_CS", "MESBOOT_GFX", "ADOPT", "ADOPT_GFX"):
        environment.pop(key, None)
    results = []
    for variant in ("baseline", "relocated"):
        for fault in cases():
            result = subprocess.run([str(binary), variant, fault], capture_output=True, text=True, timeout=15, env=environment)
            results.append({"variant": variant, "case": fault, **check_result(result, fault)})
    report = {"source_provenance": provenance, "actual_compute_cli_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "cases": results, "standalone_source_compiled": True, "hardware_executed": False,
        "limitation": "Actual CLI with fake scheduler mapping, memory writes and release fences; no GPU instruction or shader execution."}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
