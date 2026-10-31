"""Run the actual explicit scheduler query against fake memory/registers, never a GPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from prepare_source import ROOT, prepare

MARKER = "scheduler query: resource and query completions observed; GPU compute and graphics unverified"
LAYOUT_FAILURES = ("snapshot-faulted", "snapshot-adopted", "small-aperture", "arena-table", "arena-default",
                   "arena-ring", "arena-tmr", "arena-stage", "arena-unmapped")


def cases():
    yield from ("ok", "arg-count", "arg-unaligned", "arg-overflow", "arg-wide", "arg-bell-odd", "arg-bell-wide",
                "env-mc", "env-adopt", "no-service", "open-status", "hello-status", "hello-short", "hello-abi",
                "snapshot-status", "snapshot-short", *LAYOUT_FAILURES, "cp-busy", "rlc-not-ready",
                "mes-inactive", "mes-all-ones", "selection-busy", "hqd-active", "hqd-all-ones",
                "read-short", "write-short", "vread-short", "delay-error", "delay-eintr", "timeout",
                "bad-token", "token-high", "fence-high", "bell-1", "bell-2", "close-status")
    for i in range(1, 45): yield f"read-{i}"
    for i in range(1, 32): yield f"write-{i}"
    for i in range(1, 14): yield f"vread-{i}"
    for i in (1, 2048, 4096, 4097, 4638, 4639, 5694, 5695, 5698, 5699, 5826, 5827, 5828, 5829, 5962):
        yield f"vwrite-{i}"
    for i in range(1, 8): yield f"vbad-{i}"
    for i in (*range(3, 16), 18, 20, *range(23, 37)): yield f"bad-{i}"


def expected_result(fault):
    c = dict.fromkeys(("lookups", "opens", "hellos", "snapshots", "reads", "writes", "vreads", "vwrites", "bells", "sleeps", "closes"), 0)
    if fault.startswith("arg-") or fault.startswith("env-"): return 64, c
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
    if fault in LAYOUT_FAILURES: return 75, c
    events = [("reads", i) for i in range(1, 16)] + [("vreads", i) for i in range(1, 8)]
    events += [("reads", 16), ("reads", 17), ("writes", 1), ("reads", 18), ("reads", 19), ("writes", 2), ("reads", 20)]
    events += [("vwrites", i) for i in range(1, 5695)]
    events += [("writes", i) for i in range(3, 25)] + [("reads", 21), ("reads", 22), ("writes", 25), ("writes", 26)]
    events += [("reads", i) for i in range(23, 36)] + [("writes", 27), ("reads", 36)]
    for bell in (1, 2):
        events += [("vwrites", i) for i in range(5695 + (bell - 1) * 134, 5829 + (bell - 1) * 134)]
        events += [("bells", bell), ("sleeps", bell)]
        events += [("vreads", i) for i in range(8 + (bell - 1) * 3, 11 + (bell - 1) * 3)]
        events += [("writes", 26 + bell * 2)]
        events += [("reads", i) for i in range(33 + bell * 4, 37 + bell * 4)]
        events += [("writes", 27 + bell * 2)]
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
        if field == "vreads" and fault == f"vbad-{index}": return 75, c
        if field == "sleeps" and fault == "delay-error": return 74, c
        if field == "vreads" and index == 10 and fault in ("bad-token", "token-high"): return 75, c
        if field == "vreads" and index == 8 and fault in ("timeout", "fence-high"):
            c.update(sleeps=400, vreads=409)
            return 75, c
    c["closes"] = 1
    return (74 if fault == "close-status" else 0), c


def check_result(result, fault):
    status, expected = expected_result(fault)
    prefix = "fake-mes-queue-summary "
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f"Scheduler query case failed ({fault}): {result.returncode}: {result.stderr}")
    observed = json.loads(rows[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError(f"Wrong scheduler continuation/counts ({fault}): {observed}, expected {expected}")
    if (MARKER in result.stdout) != (status == 0): raise RuntimeError("Incorrect scheduler query completion claim")
    return observed


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler: raise RuntimeError("Scheduler tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("Scheduler test output exists; choose a new directory")
    stage = out / "stage"
    provenance = prepare(stage)
    source = stage / "tools/phxctl/mesboot.c"
    flags = [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-I" + str(ROOT / "tests/fake_iokit")]
    subprocess.run(flags + ["-fsyntax-only", str(source)], check=True, timeout=60)
    binary = out / "mes-queue-test"
    subprocess.run(flags + ["-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I" + str(source.parent),
        str(ROOT / "tests/test_mes_queue.c"), "-o", str(binary)], check=True, timeout=120)
    environment = os.environ.copy()
    for key in ("PTE_SYS", "FAULT_DEFAULT", "MESBOOT_MC", "MESBOOT_CS", "MESBOOT_GFX", "ADOPT", "ADOPT_GFX"):
        environment.pop(key, None)
    results = []
    for variant in ("baseline", "relocated"):
        for fault in cases():
            result = subprocess.run([str(binary), variant, fault], capture_output=True, text=True, timeout=15, env=environment)
            results.append({"variant": variant, "case": fault, **check_result(result, fault)})
    report = {"source_provenance": provenance, "actual_scheduler_cli_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "cases": results, "standalone_source_compiled": True, "hardware_executed": False,
        "limitation": "Synthetic kernel metadata, arena, register bank and completion writes; not ownership, firmware or GPU execution proof."}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
