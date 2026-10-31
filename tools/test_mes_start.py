"""Exercise actual MES start against synthetic IOKit/registers, never hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from prepare_source import ROOT, prepare

MARKER = "MES start: two firmware entrypoints and activation register state checked; scheduler execution unverified"


def cases():
    yield from ("ok", "arg-count", "arg-invalid", "arg-unaligned", "arg-overlap", "arg-mapping-mismatch",
                "env-pte", "env-default", "env-mc", "no-service", "open-status", "hello-status", "hello-short", "hello-long",
                "hello-abi", "snapshot-status", "snapshot-short", "snapshot-long", "snapshot-faulted", "snapshot-adopted",
                "snapshot-missing-tmr", "cp-busy", "rlc-not-ready", "rlc-all-ones", "mes-active", "mes-all-ones",
                "selection-busy", "read-short", "read-long", "write-short", "write-long", "vread-short", "vread-long",
                "initial-delay-error", "poll-delay-error", "delay-interrupted", "poll-delayed", "poll-timeout",
                "poll-wrong-pipe", "poll-reset-stuck", "poll-halted", "poll-all-ones", "close-status")
    for i in range(1, 26): yield f"read-{i}"
    for i in range(1, 10): yield f"write-{i}"
    for i in range(1, 5):
        yield f"vread-{i}"
        yield f"vread-bad-{i}"
    for i in (*range(3, 16), *range(17, 25)): yield f"bad-{i}"


def expected_result(fault):
    c = dict.fromkeys(("lookups", "opens", "hellos", "snapshots", "reads", "vreads", "writes", "polls", "sleeps", "closes"), 0)
    if fault in ("arg-count", "arg-invalid", "arg-unaligned", "env-pte", "env-default", "env-mc"): return 64, c
    c["lookups"] = 1
    if fault == "no-service": return 1, c
    c["opens"] = 1
    if fault == "open-status": return 1, c
    c["hellos"] = 1
    if fault in ("hello-status", "hello-short", "hello-long"): return 74, c
    if fault == "hello-abi":
        c["closes"] = 1
        return 1, c
    c["snapshots"] = 1
    if fault in ("snapshot-status", "snapshot-short", "snapshot-long"): return 74, c
    if fault in ("snapshot-faulted", "snapshot-adopted", "snapshot-missing-tmr", "arg-overlap"): return 75, c
    events = [("reads", i) for i in range(1, 16)] + [("vreads", i) for i in range(1, 5)]
    events += [("reads", 16), ("reads", 17), ("writes", 1), ("writes", 2), ("reads", 18),
               ("writes", 3), ("writes", 4), ("reads", 19), ("reads", 20), ("writes", 5), ("reads", 21),
               ("writes", 6), ("writes", 7), ("reads", 22), ("reads", 23), ("writes", 8), ("reads", 24), ("writes", 9)]
    for field, index in events:
        c[field] = index
        prefix = {"reads": "read", "vreads": "vread", "writes": "write"}[field]
        if fault in (f"{prefix}-{index}", f"{prefix}-short", f"{prefix}-long"): return 74, c
        if field == "reads":
            if fault == f"bad-{index}": return 75, c
            if index == 2 and fault in ("cp-busy", "rlc-not-ready", "rlc-all-ones"): return 75, c
            if index == 5 and fault == "arg-mapping-mismatch": return 75, c
            if index == 16 and fault in ("mes-active", "mes-all-ones"): return 75, c
            if index == 17 and fault == "selection-busy": return 75, c
        if field == "vreads" and fault == f"vread-bad-{index}": return 75, c
    c["sleeps"] = 1
    if fault == "initial-delay-error": return 74, c
    samples = 1000 if fault in ("poll-timeout", "poll-wrong-pipe", "poll-reset-stuck", "poll-halted") else (
        3 if fault in ("poll-delayed", "delay-interrupted") else 1)
    c.update(polls=samples, reads=24 + samples)
    if fault == "read-25": return 74, c
    if fault == "poll-all-ones": return 75, c
    if fault == "poll-delay-error":
        c["sleeps"] = 2
        return 74, c
    if samples == 1000:
        c["sleeps"] = 1001
        return 75, c
    c["sleeps"] = samples
    c["closes"] = 1
    return (74 if fault == "close-status" else 0), c


def check_result(result, fault):
    status, expected = expected_result(fault)
    prefix = "fake-mes-start-summary "
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f"MES start case failed ({fault}): {result.returncode}: {result.stderr}")
    observed = json.loads(rows[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError(f"Incorrect MES start continuation/counts ({fault}): {observed}, expected {expected}")
    if (MARKER in result.stdout) != (status == 0): raise RuntimeError("Incorrect MES start success/limitation marker")
    return observed


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("MES start tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("MES start output exists; choose a new directory")
    stage = out / "stage"
    provenance = prepare(stage)
    source = stage / "tools/phxctl/mesboot.c"
    flags = [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-I" + str(ROOT / "tests/fake_iokit")]
    subprocess.run(flags + ["-fsyntax-only", str(source)], check=True, timeout=60)
    flags += ["-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
              "-I" + str(source.parent), "-I" + str(stage / "src/phxbringup")]
    environment = os.environ.copy()
    for key in ("PTE_SYS", "FAULT_DEFAULT", "MESBOOT_MC"): environment.pop(key, None)
    results = []
    for variant in ("audited", "synthetic-distinct-entrypoints"):
        binary = out / ("mes-start-" + variant)
        subprocess.run(flags + (["-DPHX_TEST_ALT"] if variant != "audited" else []) +
            [str(ROOT / "tests/test_mes_start.c"), "-o", str(binary)], check=True, timeout=120)
        for fault in cases():
            result = subprocess.run([str(binary), fault], capture_output=True, text=True, timeout=15, env=environment)
            results.append({"variant": variant, "case": fault, **check_result(result, fault)})
    report = {"source_provenance": provenance, "actual_mes_cli_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "cases": results, "standalone_source_compiled": True, "hardware_executed": False,
              "limitation": "Fake registers only. Alternate profile substitutes two distinct synthetic entrypoints; neither variant executes firmware or a GPU."}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
