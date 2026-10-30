"""Test actual phxctl with fake IOKit; native verification uses file-only mode."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, prepare
from verify_artifacts import inspect_macho

FIXTURE = bytes(i % 251 for i in range(8221))


def cases():
    for fault in ("ok", "mutate-file", "read-eintr", "read-short", "read-error", "hash-mismatch", "hash-format",
                  "hash-api", "missing-hash", "arg-negative", "arg-overflow", "arg-junk", "zero-size",
                  "slice-overflow", "destination-overflow", "destination-alignment", "hello-status", "hello-short",
                  "hello-long", "hello-abi", "stage-first", "stage-second", "load-status", "load-short", "load-long",
                  "psp-status", "psp-timeout"):
        yield "load", fault
    for mode, faults in (("stage", ("ok", "stage-second")), ("verify", ("ok", "hash-mismatch", "hash-format")),
                         ("smu", ("ok", "smu-status", "smu-transport")),
                         ("reg", ("ok", "reg-short", "reg-long", "reg-status")),
                         ("layout", ("ok", "layout-status", "layout-short", "layout-long", "arg-overflow", "arg-negative", "missing-layout")),
                         ("toc", ("ok", "read-short", "hash-mismatch", "stage-second", "load-status", "load-short", "load-long",
                                  "psp-status", "toc-zero", "toc-too-large", "toc-no-fit", "toc-fit-unknown",
                                  "toc-destination-alignment", "missing-toc"))):
        for fault in faults:
            yield mode, fault


def expected_result(mode, fault):
    data = dict.fromkeys(("hellos", "stages", "accepted_bytes", "loads", "opens", "hashes", "reads", "smus", "reg_reads", "layouts", "tocs"), 0)
    if fault in ("missing-hash", "missing-layout", "missing-toc"): return 64, data
    if mode != "verify": data.update(hellos=1, opens=1)
    if fault.startswith("hello-"): return (75 if fault == "hello-abi" else 74), data
    if mode == "layout":
        if fault.startswith("arg-"): return 64, data
        data["layouts"] = 1
        return (0 if fault == "ok" else 74), data
    if mode == "smu":
        data["smus"] = 5 if fault == "ok" else 1
        return {"ok": 0, "smu-status": 75, "smu-transport": 74}[fault], data
    if mode == "reg":
        data["reg_reads"] = 2 if fault == "ok" else 1
        return (0 if fault == "ok" else 74), data
    if fault.startswith("arg-") or fault in ("hash-format", "zero-size", "destination-overflow", "destination-alignment", "toc-destination-alignment"):
        return 64, data
    if fault in ("read-error", "read-short"):
        data["reads"] = 2
        return 65, data
    data.update(reads=4 if fault == "read-eintr" else 3, hashes=1)
    if fault in ("hash-mismatch", "hash-api", "slice-overflow"): return 65, data
    if mode == "verify": return 0, data
    if fault in ("stage-first", "stage-second"):
        data.update(stages=1 if fault == "stage-first" else 2, accepted_bytes=0 if fault == "stage-first" else 4096)
        return 74, data
    data.update(stages=3, accepted_bytes=8209, loads=1 if mode == "load" else 0, tocs=1 if mode == "toc" else 0)
    if fault.startswith("load-"): return 74, data
    if fault.startswith("psp-"): return 75, data
    if fault.startswith("toc-"): return 75, data
    return 0, data


def check_result(result, mode, fault):
    expected_status, expected = expected_result(mode, fault)
    if result.returncode != expected_status:
        raise RuntimeError(f"Unexpected control exit ({mode}/{fault}): {result.returncode}: {result.stderr}")
    prefix = "fake-control-summary "
    lines = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if len(lines) != 1: raise RuntimeError("Missing or repeated firmware control accounting")
    observed = json.loads(lines[0])
    if observed != expected or any(type(v) is not int for v in observed.values()):
        raise RuntimeError("Firmware control continued incorrectly after a failed prerequisite")
    if expected_status and ("phxctl checked failure:" not in result.stderr or any(
            word in result.stdout for word in ("loadfw ", "loadtoc ", "staged ", "verified firmware snapshot", "psp layout configured"))):
        raise RuntimeError("Failure was not reported or a success message escaped")
    marker = {"load": "loadfw ", "stage": "staged ", "verify": "verified firmware snapshot", "smu": "smu ",
              "reg": "0x00123", "layout": "psp layout configured", "toc": "loadtoc complete"}[mode]
    if not expected_status and marker not in result.stdout:
        raise RuntimeError("Successful control path did not report its result")
    return observed


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("Firmware control fault tests require POSIX Clang")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("Control test output exists; choose a fresh directory")
    stage = out / "stage"
    provenance = prepare(stage)
    binary = out / "firmware-control-host-test"
    # Compile independently before the harness can supply any missing includes.
    subprocess.run([compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
                    "-I" + str(ROOT / "tests/fake_iokit"), str(stage / "tools/phxctl/phxctl.c")],
                   check=True, timeout=60)
    subprocess.run([compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror", "-g",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I" + str(ROOT / "tests/fake_iokit"),
                    "-I" + str(stage / "tools/phxctl"), str(ROOT / "tests/test_firmware_control.c"),
                    "-o", str(binary)], check=True, timeout=120)
    reports = []
    for mode, fault in cases():
        fixture = out / (mode + "-" + fault + ".bin")
        fixture.write_bytes(FIXTURE)
        result = subprocess.run([str(binary), mode, fault, str(fixture), hashlib.sha256(FIXTURE).hexdigest()],
                                capture_output=True, text=True, timeout=15)
        reports.append({"case": mode + ":" + fault, **check_result(result, mode, fault)})
    report = {"source_provenance": provenance, "cases": reports, "hardware_executed": False,
              "standalone_source_compiled": True,
              "crypto_backend": "explicit fake verifying fixture bytes; real CommonCrypto tested separately on macOS",
              "limitation": "Actual CLI control flow with fake IOKit; not firmware execution or proof of target address ownership"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


def compile_native_control(stage, out):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Native control verification requires Intel macOS")
    out = Path(out).resolve()
    if out.exists(): raise RuntimeError("Native control output exists; choose a fresh directory")
    out.mkdir()
    binary = out / "phxctl-offline-check"
    subprocess.run(["xcrun", "clang", "-std=c11", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-O2",
                    str(Path(stage) / "tools/phxctl/phxctl.c"), "-framework", "IOKit", "-framework", "CoreFoundation",
                    "-o", str(binary)], check=True, timeout=60)
    fixture = out / "synthetic-file.bin"
    fixture.write_bytes(FIXTURE)
    wanted = hashlib.sha256(FIXTURE).hexdigest()
    results = []
    for name, digest, status in (("matching-hash", wanted, 0), ("wrong-hash", "0" * 64, 65),
                                  ("malformed-hash", "invalid", 64), ("changed-file", wanted, 65)):
        if name == "changed-file": fixture.write_bytes(b"changed synthetic bytes")
        result = subprocess.run([str(binary), "verify-file", str(fixture), digest], text=True, capture_output=True, timeout=15)
        if result.returncode != status or ("verified firmware snapshot" in result.stdout) != (status == 0):
            raise RuntimeError("Native CommonCrypto offline verification did not match the expected result")
        if status and "phxctl checked failure:" not in result.stderr:
            raise RuntimeError("Native refusal did not come from the checked file path")
        results.append({"case": name, "expected_exit": status, "observed_exit": result.returncode})
    return {"binary": inspect_macho(binary, 2), "mode": "verify-file only, before IOKit service opening",
            "real_commoncrypto_executed": True, "cases": results, "hardware_executed": False,
            "firmware_staged_or_loaded": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
