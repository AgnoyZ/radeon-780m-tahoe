"""Execute actual staged PSP kernel method bodies with explicit host fakes only."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from prepare_source import ROOT, prepare

METHODS = ("clearRing", "pspRing", "pspRunCmd", "fwStage", "loadIpFw", "pspCtl")
CASES = ("success", "timeout", "wrong-fence", "psp-error", "last-fence", "fence-exhausted",
         "bad-wptr", "high-wptr", "last-slot", "wrap-sentinel", "max-words", "too-many-words", "null-words",
         "null-output", "cmd-overflow", "fence-overflow", "ring-overflow", "unaligned-cmd",
         "tmr-success", "tmr-timeout", "tmr-error", "tmr-too-large", "stage-tail",
         "stage-overrun", "stage-null", "stage-empty", "stage-aperture-overflow",
         "load-success", "load-error", "load-address-overflow", "create-timeout", "destroy-timeout")


def extract_methods(source):
    parts, hashes = [], {}
    frame = re.findall(r"^struct PhxGfxRbFrame \{.*?^static_assert\([^\n]+\);", source, re.M | re.S)
    if len(frame) != 1:
        raise RuntimeError("Could not identify exactly one actual PSP frame definition")
    for name in METHODS:
        matches = re.findall(r"^(?:IOReturn|void) PhxBringup::" + name + r"\([^\n]*\) \{.*?^\}\n", source, re.M | re.S)
        if len(matches) != 1:
            raise RuntimeError("Could not identify exactly one actual PSP method: " + name)
        parts.append(matches[0])
        hashes[name] = hashlib.sha256(matches[0].encode()).hexdigest()
    return frame[0] + "\n", "\n".join(parts), hashes


def check_result(result, case):
    if result.returncode != 0:
        raise RuntimeError(f"PSP host assertion failed ({case}): {result.stderr}")
    report = json.loads(result.stdout)
    if not isinstance(report, dict) or set(report) != {"case", "passed", "hardware_executed"} or report["case"] != case or report["passed"] is not True or report["hardware_executed"] is not False:
        raise RuntimeError("Unexpected PSP assertion report")
    return report


def exercise(out):
    compiler = shutil.which("clang++")
    if platform.system() not in ("Linux", "Darwin") or not compiler:
        raise RuntimeError("PSP host tests require POSIX Clang; not a pass on this host")
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("PSP test output exists; choose a fresh directory")
    stage = out / "stage"
    provenance = prepare(stage)
    source = (stage / "src/phxbringup/PhxBringup.cpp").read_text(encoding="utf-8")
    frame, methods, hashes = extract_methods(source)
    (out / "psp-frame.inc").write_text(frame, encoding="utf-8")
    (out / "psp-methods.inc").write_text(methods, encoding="utf-8")
    binary = out / "psp-host-test"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I" + str(out),
                    "-I" + str(stage / "src/phxbringup"), str(ROOT / "tests/test_psp_submission.cpp"),
                    "-o", str(binary)], check=True, timeout=120)
    results = []
    for case in CASES:
        result = subprocess.run([str(binary), case], text=True, capture_output=True, timeout=15)
        results.append(check_result(result, case))
    report = {"source_provenance": provenance, "actual_method_sha256": hashes, "cases": results,
              "hardware_executed": False, "kernel_loaded": False,
              "limitation": "Actual kernel method bodies with fake memory, registers, locks and firmware observations; not PSP emulation or target proof"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    exercise(parser.parse_args().out)
