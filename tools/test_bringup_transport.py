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
    operations = ("open", "rd", "vr", "vr64", "wr", "vw", "db", "sm", "read-then-write",
                  "vram-read-then-write", "write-then-doorbell", "claim", "adopt")
    for operation in operations:
        yield operation, "ok", 0, 2 if "-then-" in operation else 1
        yield operation, "status", 74, 1
    for operation in ("rd", "vr", "vr64", "wr", "sm", "read-then-write", "vram-read-then-write"):
        yield operation, "zero", 0, 2 if "-then-" in operation else 1
    for operation in ("open", "rd", "vr", "vr64", "wr", "sm", "read-then-write", "vram-read-then-write"):
        for fault in ("short", "long"):
            yield operation, fault, 74, 1
    for fault, calls_count in (("bad-abi", 1), ("no-service", 0), ("open-failure", 0)):
        yield "open", fault, 1, calls_count


def completion_cases():
    for operation in ("mes", "sched", "compute", "gfx"):
        faults = ("ok", "timeout", "zero-token", "wrong-token", "wrong-fence-high", "wrong-token-high") if operation in ("mes", "sched") else (
            "ok", "timeout", "wrong-scratch", "wrong-memory")
        for fault in faults:
            yield operation, fault


def check_completion_case(result, operation, fault):
    success = fault == "ok"
    if result.returncode != (0 if success else 75):
        raise RuntimeError(f"Unexpected completion exit ({operation}/{fault}): {result.returncode}: {result.stderr}")
    if ("gpu-returned" in result.stdout) != success:
        raise RuntimeError("GPU failure was swallowed or positive path did not return")
    if not success and "mesboot GPU:" not in result.stderr:
        raise RuntimeError("Negative result was not a checked completion failure")
    prefix = "fake-gpu-summary "
    summaries = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if len(summaries) != 1:
        raise RuntimeError("Missing or repeated completion-path accounting")
    summary = json.loads(summaries[0])
    work = operation in ("compute", "gfx")
    expected = {"scheduler_bells": 2 if operation == "sched" and success else 1,
                "work_bells": 1 if work else 0, "adoptions": 1 if work and success else 0,
                "writes_after_failure": 0}
    if set(summary) != set(expected) | {"sleeps"} or any(type(value) is not int for value in summary.values()):
        raise RuntimeError("Invalid completion-path accounting types")
    if any(summary[key] != value for key, value in expected.items()):
        raise RuntimeError("Initialization continued or adopted a queue after a failed prerequisite")
    expected_sleeps = (2 if operation == "sched" else 1) if success else (400 if fault in ("timeout", "wrong-fence-high") else 1)
    if work:
        expected_sleeps = 2 if success else 51
    if summary["sleeps"] != expected_sleeps:
        raise RuntimeError("Completion polling did not follow the actual bounded path")
    return summary


def submission_cases():
    return ("first-frame", "last-frame", "last-sequence", "unaligned", "null", "short-frame",
            "long-frame", "huge-frame", "offset-past-end", "offset-truncated", "offset-unaligned",
            "ring-one-over", "ring-full", "ring-high-word", "ring-max", "sequence-exhausted")


def check_submission_case(result, fault):
    success = fault in ("first-frame", "last-frame", "last-sequence", "unaligned")
    if result.returncode != (0 if success else 76):
        raise RuntimeError(f"Unexpected submission exit ({fault}): {result.returncode}: {result.stderr}")
    if ("submission-returned" in result.stdout) != success:
        raise RuntimeError("Submission rejection was swallowed or valid boundary did not return")
    if not success and "mesboot submission:" not in result.stderr:
        raise RuntimeError("Negative result was not a submission precondition rejection")
    prefix = "fake-submission-summary "
    summaries = [line[len(prefix):] for line in result.stderr.splitlines() if line.startswith(prefix)]
    if len(summaries) != 1:
        raise RuntimeError("Missing or repeated submission accounting")
    summary = json.loads(summaries[0])
    if set(summary) != {"calls", "ring_writes", "wptr", "seq"} or any(type(v) is not int for v in summary.values()):
        raise RuntimeError("Invalid submission accounting types")
    initial_wptr = {"last-frame": 896, "ring-one-over": 897, "ring-full": 1024,
                    "ring-high-word": 1 << 32, "ring-max": (1 << 64) - 1}.get(fault, 0)
    initial_seq = {"last-sequence": (1 << 64) - 2, "sequence-exhausted": (1 << 64) - 1}.get(fault, 0)
    if summary["wptr"] != initial_wptr + (128 if success else 0) or summary["seq"] != initial_seq + int(success):
        raise RuntimeError("Submission pointer or sequence changed incorrectly")
    invalid_calls = summary["calls"] <= 0 if success else summary["calls"] != 0
    if summary["ring_writes"] != (128 if success else 0) or invalid_calls:
        raise RuntimeError("Submission performed unexpected transport or ring writes")
    return summary


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
    completions = []
    for operation, fault in completion_cases():
        result = subprocess.run([str(binary), operation, fault], capture_output=True, text=True, timeout=10)
        observed = check_completion_case(result, operation, fault)
        completions.append({"case": operation + ":" + fault, **observed})
    submissions = []
    for fault in submission_cases():
        result = subprocess.run([str(binary), "submission", fault], capture_output=True, text=True, timeout=10)
        submissions.append({"case": fault, **check_submission_case(result, fault)})
    report = {"source_provenance": provenance, "fault_injection_cases_passed": passed,
              "completion_path_cases_passed": completions,
              "submission_boundary_cases_passed": submissions,
              "transport_backend": "fake IOKit; actual patched mesboot source",
              "hardware_executed": False, "driver_runtime_tested": False,
              "limitation": "Injected transport/completion observations test actual userspace control flow, not GPU execution or packet correctness"}
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
