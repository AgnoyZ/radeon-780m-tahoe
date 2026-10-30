"""Test the actual plugin's metallib indexing/compilation, never device creation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from test_translator_runtime import spirv_instructions

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"plugin_loaded": True, "plugin_compiler_executed": True, "bundled_runtimes_loaded": True,
            "gpu_commands_begun": 0, "gpu_commands_submitted": 0, "gpu_commands_abandoned": 0}


def clean_environment(environment):
    return {k: v for k, v in environment.items()
            if not k.startswith(("NVMTL_", "NVK_", "NAK_", "NVRM_", "DYLD_", "VK_", "RADV_", "MESA_", "AMD_"))}


def check_probe(result, negative=False):
    if negative:
        if result.returncode != 20 or "Plugin library index failed" not in result.stderr or result.stdout.strip():
            raise RuntimeError(f"Expected plugin indexing rejection, got {result.returncode}: {result.stderr}")
        return None
    if result.returncode:
        raise RuntimeError(f"Actual plugin compiler failed ({result.returncode}): {result.stderr}")
    data = json.loads(result.stdout)
    if data != EXPECTED or any(type(data[k]) is not type(v) for k, v in EXPECTED.items()):
        raise RuntimeError("Plugin did not verify its runtime images and absence of GPU commands")
    return data


def copy_bundle(source, destination, omit=None):
    source = Path(source).resolve()
    if omit not in (None, "libnvmtl_translate.dylib", "air-runtime/libLLVM.dylib"):
        raise ValueError("Only a named runtime may be omitted from a negative fixture")
    excluded = source / "Contents/MacOS" / omit if omit else None
    def ignore(directory, names):
        return [name for name in names if Path(directory) / name == excluded]
    shutil.copytree(source, destination, ignore=ignore)


def exercise(bundle, fixture, validator, out):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Real plugin tests require an Intel macOS build host")
    bundle, fixture, out = map(lambda p: Path(p).resolve(), (bundle, fixture, out))
    if out.exists():
        raise RuntimeError("Plugin test output exists; choose a fresh directory")
    source_executable = bundle / "Contents/MacOS/NVMTLDriver"
    required = [source_executable, bundle / "Contents/MacOS/libnvmtl_translate.dylib",
                bundle / "Contents/MacOS/air-runtime/libLLVM.dylib"]
    if not all(p.is_file() for p in required):
        raise RuntimeError("Build the actual plugin and both compiler runtimes first")
    out.mkdir(parents=True)
    env = clean_environment(os.environ)
    def run(*command, timeout=60):
        return subprocess.run(list(map(str, command)), check=True, env=env, timeout=timeout)
    probe = out / "plugin-compile-probe"
    run("xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
        "-framework", "Foundation", "-framework", "Metal", "-framework", "IOKit", "-framework", "CoreFoundation",
        ROOT / "tools/plugin_compile_probe.m", "-o", probe)
    relocated = out / "relocated/NVMTLDriver.bundle"
    copy_bundle(bundle, relocated)
    run("codesign", "--verify", "--strict", relocated)
    inputs = {}
    for value in (17, 29):
        air, lib = out / f"increment{value}.air", out / f"increment{value}.metallib"
        run("xcrun", "-sdk", "macosx", "metal", "-std=macos-metal3.1", "-c", fixture, f"-DADD_VALUE={value}", "-o", air)
        run("xcrun", "-sdk", "macosx", "metallib", air, "-o", lib)
        inputs[value] = lib
    reports = []
    for value, lib in inputs.items():
        case = out / f"positive{value}"
        case.mkdir()
        result = subprocess.run([str(probe), str(relocated / "Contents/MacOS/NVMTLDriver"), str(lib), str(case)],
                                capture_output=True, text=True, env=env, timeout=90)
        observed = check_probe(result)
        data = (case / "compiled.spv").read_bytes()
        instructions = spirv_instructions(data)
        if not {62, 128}.issubset({op for op, _ in instructions}) or not any(
                op == 15 and args and args[0] == 5 for op, args in instructions):
            raise RuntimeError("Plugin output lacks compute/store/integer-add operations")
        run(validator, "--target-env", "vulkan1.2", case / "compiled.spv", timeout=30)
        reports.append({"case": f"increment{value}", **observed, "spirv_bytes": len(data),
                        "spirv_sha256": hashlib.sha256(data).hexdigest(), "spirv_val": "passed"})
    if reports[0]["spirv_sha256"] == reports[1]["spirv_sha256"]:
        raise RuntimeError("Actual plugin returned identical SPIR-V for different Metal arithmetic")
    negatives = []
    for name, omit in (("missing_translator", "libnvmtl_translate.dylib"), ("missing_llvm", "air-runtime/libLLVM.dylib"),
                       ("malformed_metallib", None)):
        negative = out / name
        negative.mkdir()
        target = relocated
        lib = inputs[17]
        if omit:
            target = negative / "NVMTLDriver.bundle"
            copy_bundle(bundle, target, omit=omit)
            run("codesign", "--force", "--sign", "-", target)
            run("codesign", "--verify", "--strict", target)
        else:
            lib = negative / "invalid.metallib"
            lib.write_bytes(b"not a metallib")
        result = subprocess.run([str(probe), str(target / "Contents/MacOS/NVMTLDriver"), str(lib), str(negative)],
                                capture_output=True, text=True, env=env, timeout=90)
        check_probe(result, negative=True)
        if (negative / "compiled.spv").exists():
            raise RuntimeError("Rejected plugin compilation produced an output")
        negatives.append(name)
    report = {"plugin_sha256": hashlib.sha256(source_executable.read_bytes()).hexdigest(),
              "translator_sha256": hashlib.sha256(required[1].read_bytes()).hexdigest(),
              "llvm_sha256": hashlib.sha256(required[2].read_bytes()).hexdigest(), "cases": reports,
              "negative_cases_passed": negatives, "relocated_bundle_tested": True, "hardware_executed": False,
              "metal_device_created": False, "full_metal_pipeline_tested": False,
              "limitation": "Actual plugin compiler only; no Metal/Vulkan device, GPU execution or target runtime integration"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "fixture", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--validator", required=True)
    args = parser.parse_args()
    exercise(args.bundle, args.fixture, args.validator, args.out)
