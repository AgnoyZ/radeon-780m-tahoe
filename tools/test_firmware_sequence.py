"""Exercise the real profile-driven CLI with synthetic files and fake device/crypto."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

from firmware_profile import load_profile
from prepare_source import ROOT, prepare


def cases():
    yield from ("ok", "mutate-files", "missing-file", "changed-file", "size-mismatch", "service-missing",
                "open-status", "hello-abi", "layout-zero", "layout-overflow", "layout-aperture", "tmr-alignment",
                "ring-address", "toc-zero", "toc-large", "toc-capacity", "toc-no-fit", "toc-unknown-fit",
                "stage-second", "close-status")
    for name in ("count", "negative", "overflow", "junk", "unaligned", "span", "overlap", "zero",
                 "tmr-large", "stage-large", "stage-small", "stage-overlap"):
        yield "arg-" + name
    for i in range(9):
        yield "hash-" + str(i)
        yield "hash-api-" + str(i)
    for operation in ("hello", "layout", "ring", "toc", "tmr", "load", "autoload"):
        for failure in ("status", "short", "long"):
            yield operation + "-" + failure
        if operation in ("toc", "tmr", "load", "autoload"):
            yield operation + "-psp"
            yield operation + "-timeout"
    for i in range(18):
        yield "stage-" + str(i)
        if i: yield "load-" + str(i)


def expected_result(fault, data=None):
    data = load_profile() if data is None else data
    counts = {"events": [], "stages": 0, "accepted_bytes": 0}
    events = counts["events"]
    if fault.startswith("arg-"): return 64, counts
    for i in range(9):
        if fault == "missing-file" and i == 4: return 65, counts
        events.append(f"hash-{i}")
        if fault in (f"hash-{i}", f"hash-api-{i}") or (i == 4 and fault in ("changed-file", "size-mismatch")):
            return 65, counts
    events.append("lookup")
    if fault == "service-missing": return 74, counts
    for operation in ("open", "hello", "layout", "ring"):
        events.append(operation)
        if fault in (operation + "-status", operation + "-short", operation + "-long"): return 74, counts
        if fault == "hello-abi" and operation == "hello": return 75, counts
        if fault in ("layout-zero", "layout-overflow", "layout-aperture", "tmr-alignment") and operation == "layout": return 75, counts
        if fault == "ring-address" and operation == "ring": return 75, counts
    for i, step in enumerate(data["steps"]):
        events.append(f"stage-{i}")
        for offset in range(0, step["size_bytes"], 4096):
            counts["stages"] += 1
            if fault == f"stage-{i}" or (fault == "stage-second" and counts["stages"] == 2): return 74, counts
            counts["accepted_bytes"] += min(4096, step["size_bytes"] - offset)
        operation = "toc" if i == 0 else "load"
        events.append("toc" if i == 0 else f"load-{i}")
        if fault in (operation + "-status", operation + "-short", operation + "-long"): return 74, counts
        if fault in (operation + "-psp", operation + "-timeout") or (i and fault == f"load-{i}"): return 75, counts
        if i == 0:
            if fault in ("toc-zero", "toc-large", "toc-capacity", "toc-no-fit", "toc-unknown-fit"):
                return 75, counts
            events.append("tmr")
            if fault in ("tmr-status", "tmr-short", "tmr-long"): return 74, counts
            if fault in ("tmr-psp", "tmr-timeout"): return 75, counts
    events.append("autoload")
    if fault in ("autoload-status", "autoload-short", "autoload-long"): return 74, counts
    if fault in ("autoload-psp", "autoload-timeout"): return 75, counts
    events.append("close")
    return (74 if fault == "close-status" else 0), counts


def check_result(result, fault, data=None):
    status, wanted = expected_result(fault, data)
    prefix = "fake-sequence-summary "
    lines = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if result.returncode != status or len(lines) != 1:
        raise RuntimeError(f"Firmware sequence failed expectation ({fault}): {result.returncode}: {result.stderr}")
    actual = json.loads(lines[0])
    if (actual != wanted or type(actual.get("stages")) is not int or type(actual.get("accepted_bytes")) is not int):
        raise RuntimeError(f"Wrong sequence/bytes or continuation after failure ({fault}): {actual}; expected {wanted}")
    marker = "firmware-sequence complete: 17 IP loads and RLC autoload acknowledged; GPU operation unverified"
    if status:
        if "phxctl checked failure:" not in result.stderr or "firmware-sequence complete" in result.stdout:
            raise RuntimeError("Firmware sequence failure was hidden or reported as success")
    elif marker not in result.stdout:
        raise RuntimeError("Firmware sequence success report missing its hardware limitation")
    return actual


def write_fixtures(directory, data, fault):
    directory.mkdir()
    for index, entry in enumerate(data["files"]):
        if fault == "missing-file" and index == 4: continue
        content = bytes((index + offset) % 251 for offset in range(entry["size_bytes"]))
        if fault == "changed-file" and index == 4: content = b"\xff" + content[1:]
        if fault == "size-mismatch" and index == 4: content = content[:-4]
        (directory / entry["name"]).write_bytes(content)


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("Firmware sequence tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("Sequence output exists; choose a fresh directory")
    stage = out / "stage"
    provenance = prepare(stage)
    binary = out / "firmware-sequence-host-test"
    common = [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
              "-I" + str(ROOT / "tests/fake_iokit")]
    source = stage / "tools/phxctl/phxctl.c"
    subprocess.run(common + ["-fsyntax-only", str(source)], check=True, timeout=60)
    subprocess.run(common + ["-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                            "-I" + str(source.parent), str(ROOT / "tests/test_firmware_sequence.c"), "-o", str(binary)],
                   check=True, timeout=120)
    data = load_profile()
    reports = []
    for fault in cases():
        directory = out / fault
        write_fixtures(directory, data, fault)
        result = subprocess.run([str(binary), fault, str(directory)], capture_output=True, text=True, timeout=20)
        reports.append({"case": fault, **check_result(result, fault, data)})
    report = {"source_provenance": provenance, "actual_cli_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "cases": reports, "standalone_source_compiled": True, "hardware_executed": False,
              "crypto_backend": "fake fixture-byte validation; not SHA-256 evidence",
              "limitation": "Synthetic files/fake IOKit; no firmware execution, compatibility or address ownership evidence"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    exercise(parser.parse_args().out)
