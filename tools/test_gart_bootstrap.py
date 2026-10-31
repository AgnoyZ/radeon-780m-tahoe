"""Run the actual GART CLI against synthetic memory/register transport, never a GPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from prepare_source import ROOT, prepare

INVALID_LAYOUT = ("snapshot-version", "snapshot-reserved", "snapshot-no-tmr", "snapshot-no-ring", "snapshot-gpu",
    "snapshot-faulted", "snapshot-unknown", "snapshot-zero-tmr", "snapshot-large-tmr", "snapshot-zero-mc",
    "snapshot-physical-align", "snapshot-physical-width", "snapshot-mc-width", "snapshot-aperture", "snapshot-map-size",
    "table-ring", "table-tmr", "table-stage", "default-ring", "default-tmr", "default-stage", "table-default",
    "table-outside", "default-outside", "virtual-mc-overlap", "table-offset-wide", "map-outside-vram", "snapshot-wide-tmr",
    "table-wrap", "default-offset-wide", "snapshot-aperture-size-granularity", "snapshot-aperture-base-granularity")


def cases():
    yield from ("ok", "relocated", "env-zero", "legacy-all", "env-pte", "env-default", "no-service", "open-status",
                "hello-status", "hello-short", "hello-long", "hello-abi", "snapshot-status", "snapshot-short", "snapshot-long")
    for name in ("count", "negative", "overflow", "junk", "unaligned", "zero", "map-large", "va-overflow"):
        yield "arg-" + name
    yield from INVALID_LAYOUT
    yield from ("cp-busy", "rlc-not-ready", "rlc-all-ones", "context-zero-active", "context-eight-active",
                "read-short", "read-long", "write-short", "write-long", "vram-read-short", "vram-read-long",
                "ack-delayed", "ack-timeout", "ack-wrong-bit", "ack-all-ones", "sleep-error", "sleep-eintr", "close-status")
    for index in (1, 1024, 1025, 2048): yield f"vram-write-{index}"
    for index in range(1, 5):
        yield f"vram-read-{index}"
        yield f"vram-bad-{index}"
    for index in range(1, 189): yield f"reg-write-{index}"
    for index in range(1, 34): yield f"reg-read-{index}"
    for index in range(20, 33): yield f"register-bad-{index}"


def expected_result(fault):
    c = dict.fromkeys(("lookups", "opens", "hellos", "snapshots", "reg_reads", "vram_reads", "vram_writes",
                       "accepted_words", "reg_writes", "ack_reads", "sleeps", "closes"), 0)
    if fault.startswith("arg-") or fault in ("legacy-all", "env-pte", "env-default"): return 64, c
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
    if fault in INVALID_LAYOUT: return 75, c
    for index in range(1, 19):
        c["reg_reads"] = index
        if fault == f"reg-read-{index}" or fault in ("read-short", "read-long"): return 74, c
        if index == 2 and fault in ("cp-busy", "rlc-not-ready", "rlc-all-ones"): return 75, c
        if index == 3 and fault == "context-zero-active": return 75, c
        if index == 11 and fault == "context-eight-active": return 75, c
    for index in range(1, 2049):
        c["vram_writes"] = index
        if fault == f"vram-write-{index}": return 74, c
        c["accepted_words"] = index
    for index in range(1, 5):
        c["vram_reads"] = index
        if fault == f"vram-read-{index}" or fault in ("vram-read-short", "vram-read-long"): return 74, c
        if fault == f"vram-bad-{index}": return 75, c
    for index in range(1, 189):
        if index == 187:
            c["reg_reads"] = 19
            if fault == "reg-read-19": return 74, c
        if index == 188:
            for read in range(20, 33):
                c["reg_reads"] = read
                if fault == f"reg-read-{read}": return 74, c
                if fault == f"register-bad-{read}": return 75, c
        c["reg_writes"] = index
        if fault == f"reg-write-{index}" or fault in ("write-short", "write-long"): return 74, c
    polls = 1000 if fault in ("ack-timeout", "ack-wrong-bit") else 3 if fault in ("ack-delayed", "sleep-eintr") else 1
    c.update(ack_reads=polls, reg_reads=32 + polls)
    if fault == "reg-read-33": return 74, c
    if fault == "ack-all-ones": return 75, c
    if fault == "sleep-error":
        c["sleeps"] = 1
        return 74, c
    if fault in ("ack-timeout", "ack-wrong-bit"):
        c["sleeps"] = polls
        return 75, c
    c["sleeps"] = polls - 1
    c["closes"] = 1
    return (74 if fault == "close-status" else 0), c


def check_result(result, fault):
    status, expected = expected_result(fault)
    prefix = "fake-gart-summary "
    rows = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(rows) != 1:
        raise RuntimeError(f"GART case failed ({fault}): {result.returncode}: {result.stderr}")
    observed = json.loads(rows[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError(f"Incorrect GART continuation/counts ({fault}): {observed}, expected {expected}")
    marker = "gart complete: 5 pages, address readbacks and invalidation acknowledged; GPU execution unverified"
    if status == 0 and marker not in result.stdout: raise RuntimeError("Missing GART completion limitation")
    if status:
        if "gart complete" in result.stdout: raise RuntimeError("Failed GART operation reported success")
        if status != 1 and not any(s in result.stderr for s in ("mesboot transport:", "mesboot GART:")):
            raise RuntimeError("GART failure did not come from a checked path")
    return observed


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("GART tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("GART output exists; choose a new directory")
    stage = out / "stage"
    provenance = prepare(stage)
    source = stage / "tools/phxctl/mesboot.c"
    flags = [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-I" + str(ROOT / "tests/fake_iokit")]
    subprocess.run(flags + ["-fsyntax-only", str(source)], check=True, timeout=60)
    binary = out / "gart-host-test"
    subprocess.run(flags + ["-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-I" + str(source.parent), str(ROOT / "tests/test_gart_bootstrap.c"), "-o", str(binary)], check=True, timeout=120)
    environment = os.environ.copy()
    for key in ("PTE_SYS", "FAULT_DEFAULT", "MESBOOT_MC"): environment.pop(key, None)
    results = []
    for fault in cases():
        result = subprocess.run([str(binary), fault], capture_output=True, text=True, timeout=15, env=environment)
        results.append({"case": fault, **check_result(result, fault)})
    report = {"source_provenance": provenance, "actual_gart_cli_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "cases": results, "standalone_source_compiled": True, "hardware_executed": False,
              "limitation": "Actual GART CLI with fake kernel metadata/memory/registers; not target ownership or GPU translation proof"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
