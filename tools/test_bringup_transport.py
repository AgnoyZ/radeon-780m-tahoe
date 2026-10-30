"""Fault-inject the actual staged mesboot helpers; never connect to hardware."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, prepare
from verify_artifacts import inspect_macho


def check_case(result, expected_return, expected_calls):
    if result.returncode != expected_return:
        raise RuntimeError(f"Unexpected transport exit {result.returncode}: {result.stderr}")
    calls = [line for line in result.stderr.splitlines() if line.startswith("fake-transport call=")]
    if len(calls) != expected_calls:
        raise RuntimeError("Unexpected transport count; a failed prerequisite may have continued")
    expected_stdout = "transport-returned" if expected_return == 0 else ""
    if result.stdout.strip() != expected_stdout:
        raise RuntimeError("Unexpected output after transport failure")
    if expected_return == 74 and "mesboot transport:" not in result.stderr:
        raise RuntimeError("Failure did not come from the checked transport")


def cases():
    operations = ("open", "rd", "vr", "wr", "vw", "db", "sm", "read-then-write",
                  "vram-read-then-write", "write-then-doorbell", "claim", "adopt")
    for operation in operations:
        yield operation, "ok", 0, 2 if "-then-" in operation else 1
        yield operation, "status", 74, 1
    for operation in ("rd", "vr", "wr", "sm", "read-then-write", "vram-read-then-write"):
        yield operation, "zero", 0, 2 if "-then-" in operation else 1
    for operation in ("open", "rd", "vr", "wr", "sm", "read-then-write", "vram-read-then-write"):
        for fault in ("short", "long"):
            yield operation, fault, 74, 1
    for fault, calls_count in (("bad-abi", 1), ("no-service", 0), ("open-failure", 0)):
        yield "open", fault, 1, calls_count


def exercise(out):
    compiler = shutil.which("clang")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("Transport fault injection requires a POSIX host with Clang; not a pass on this host")
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("Transport test output exists; choose a fresh directory")
    stage = out / "stage"
    provenance = prepare(stage)
    binary = out / "transport-fault-test"
    subprocess.run([compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-g",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I" + str(ROOT / "tests/fake_iokit"), "-I" + str(stage / "tools/phxctl"),
                    str(ROOT / "tests/test_bringup_transport.c"), "-o", str(binary)], check=True, timeout=120)
    passed = []
    for operation, fault, status, count in cases():
        result = subprocess.run([str(binary), operation, fault], capture_output=True, text=True, timeout=10)
        check_case(result, status, count)
        passed.append(operation + ":" + fault)
    report = {"source_provenance": provenance, "fault_injection_cases_passed": passed,
              "transport_backend": "fake IOKit; actual patched mesboot source",
              "hardware_executed": False, "driver_runtime_tested": False,
              "limitation": "Checks transport status, exact reply lengths and fail-stop sequencing, not GPU initialization"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


def compile_native(out):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Native mesboot compilation requires Intel macOS")
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("Native transport output exists; choose a fresh directory")
    stage = out / "stage"
    provenance = prepare(stage)
    binary = out / "mesboot-compile-only"
    subprocess.run(["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-O2",
                    str(stage / "tools/phxctl/mesboot.c"), "-framework", "IOKit", "-framework", "CoreFoundation",
                    "-o", str(binary)], check=True, timeout=60)
    return {"source_provenance": provenance, "binary": inspect_macho(binary, 2),
            "native_iokit_linked": True, "tool_executed": False, "hardware_executed": False,
            "deployable": False, "limitation": "Reference memory layout remains unsafe for target use; compile only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    exercise(args.out)
