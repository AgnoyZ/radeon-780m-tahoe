"""Check real Apple Metal tooling and compile native probes before dependency builds."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from verify_artifacts import inspect_macho

ROOT = Path(__file__).resolve().parents[1]


def metal_command(fixture, output, value):
    return ["xcrun", "-sdk", "macosx", "metal", "-std=metal3.1", "-c",
            str(Path(fixture).resolve()), f"-DADD_VALUE={value}", "-o", str(output)]


def probe_command(kind, output):
    if kind not in ("metal-smoke", "plugin-compile-probe"):
        raise ValueError("Unknown native probe")
    smoke = kind == "metal-smoke"
    command = ["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=" + ("13.0" if smoke else "15.0"),
               "-fobjc-arc", "-Wall", "-Wextra", "-Werror"]
    if smoke:
        command += ["-fblocks", "-I" + str(ROOT / "src")]
    for framework in ("Foundation", "Metal", "IOKit", "CoreFoundation"):
        command += ["-framework", framework]
    source = "metal_smoke.m" if smoke else "plugin_compile_probe.m"
    return command + [str(ROOT / "tools" / source), "-o", str(output)]


def preflight(out):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Native toolchain preflight requires Intel macOS")
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("Preflight output exists; choose a fresh directory")
    out.mkdir(parents=True)
    compiler = subprocess.check_output(["xcrun", "-sdk", "macosx", "metal", "--version"], text=True, timeout=30).strip()
    reports = []
    for value in (17, 29):
        air, library = out / f"increment{value}.air", out / f"increment{value}.metallib"
        subprocess.run(metal_command(ROOT / "tests/fixtures/compute_increment.metal", air, value), check=True, timeout=60)
        subprocess.run(["xcrun", "-sdk", "macosx", "metallib", str(air), "-o", str(library)], check=True, timeout=60)
        data = library.read_bytes()
        if not data.startswith(b"MTLB") or len(data) < 32:
            raise RuntimeError("Apple linker did not produce a metallib container")
        reports.append({"value": value, "metallib_bytes": len(data), "metallib_sha256": hashlib.sha256(data).hexdigest()})
    probes = {}
    for kind in ("metal-smoke", "plugin-compile-probe"):
        executable = out / kind
        subprocess.run(probe_command(kind, executable), check=True, timeout=60)
        probes[kind] = inspect_macho(executable, 2)
    report = {"metal_compiler": compiler, "cases": reports, "compiled_probes": probes,
              "native_probes_executed": False, "driver_runtime_tested": False, "hardware_executed": False}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    preflight(parser.parse_args().out)
