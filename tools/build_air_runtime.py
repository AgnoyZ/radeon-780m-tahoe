"""Build a pinned, replaceable LLVM AIR reader runtime; never install it."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from prepare_source import ROOT, git, verify_checkout
from verify_artifacts import inspect_macho
from test_air_runtime import llvm_exports


def cmake_command(source, native):
    return ["cmake", "-S", str(Path(source) / "llvm"), "-B", str(native), "-G", "Ninja",
            "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_OSX_ARCHITECTURES=x86_64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0",
            "-DLLVM_BUILD_LLVM_DYLIB=ON", "-DLLVM_LINK_LLVM_DYLIB=OFF",
            "-DLLVM_DYLIB_COMPONENTS=core;bitreader;bitwriter;irreader;passes", "-DLLVM_TARGETS_TO_BUILD=",
            "-DLLVM_BUILD_TOOLS=OFF", "-DLLVM_INCLUDE_UTILS=OFF", "-DLLVM_INCLUDE_TESTS=OFF",
            "-DLLVM_INCLUDE_DOCS=OFF",
            "-DLLVM_INCLUDE_BENCHMARKS=OFF", "-DLLVM_INCLUDE_EXAMPLES=OFF", "-DLLVM_INCLUDE_RUNTIMES=OFF",
            "-DLLVM_ENABLE_BINDINGS=OFF", "-DLLVM_ENABLE_ZSTD=OFF", "-DLLVM_ENABLE_ZLIB=OFF",
            "-DLLVM_ENABLE_LIBXML2=OFF", "-DLLVM_ENABLE_LIBEDIT=OFF", "-DLLVM_ENABLE_LIBPFM=OFF",
            "-DLLVM_ENABLE_FFI=OFF", "-DLLVM_ENABLE_CURL=OFF", "-DLLVM_ENABLE_HTTPLIB=OFF",
            "-DPython3_EXECUTABLE=" + sys.executable]


def system_dependencies(otool_output):
    entries = [line.strip().split(" (", 1)[0] for line in otool_output.splitlines()[1:] if line.strip()]
    if not entries or entries[0] != "@rpath/libLLVM.dylib":
        raise ValueError("Unexpected LLVM dylib identity")
    for entry in entries[1:]:
        if not entry.startswith(("/usr/lib/", "/System/Library/")):
            raise ValueError("Non-system LLVM dependency: " + entry)
    return entries[1:]


def run(*args):
    print("RUN", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def build_air_runtime(source, out, artifacts, stage):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("LLVM AIR runtime build requires an Intel macOS host")
    source, out, artifacts, stage = map(lambda p: Path(p).resolve(), (source, out, artifacts, stage))
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    spec = lock["LLVM"]
    verify_checkout(source, spec["commit"])
    plugin = artifacts / "NVMTLDriver.bundle"
    if not (plugin / "Contents/MacOS/NVMTLDriver").is_file():
        raise RuntimeError("Build the real plugin before adding its AIR runtime")
    destination = plugin / "Contents/MacOS/air-runtime"
    if out.exists() or destination.exists():
        raise RuntimeError("AIR runtime output exists; choose fresh build/artifact directories")
    out.mkdir(parents=True)
    native = out / "native"
    run(*cmake_command(source, native))
    run("cmake", "--build", native, "--target", "LLVM", "--parallel", str(min(os.cpu_count() or 2, 4)))
    built = native / "lib/libLLVM.dylib"
    inspect_macho(built, 6)
    destination.mkdir(parents=True)
    final = destination / "libLLVM.dylib"
    shutil.copy2(built, final)
    run("xcrun", "strip", "-S", final)
    run("install_name_tool", "-id", "@rpath/libLLVM.dylib", final)
    dependencies = system_dependencies(subprocess.check_output(["xcrun", "otool", "-L", str(final)], text=True))
    output = subprocess.check_output(["xcrun", "nm", "-gU", str(final)], text=True)
    defined = {line.split()[-1] for line in output.splitlines() if line.split()}
    required = llvm_exports(stage / "src/nmplugin/NVMTLLibraryLoad.m")
    missing = {"_" + name for name in required} - defined
    if missing:
        raise RuntimeError("LLVM lacks plugin runtime exports: " + ", ".join(sorted(missing)))
    run("codesign", "--force", "--sign", "-", final)
    run("codesign", "--verify", "--strict", final)
    notices = artifacts / "DEPENDENCY-LICENSES/LLVM"
    for directory in (source / "llvm", source / "third-party"):
        for path in directory.rglob("*"):
            if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                copy = notices / path.relative_to(source)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
    verify_checkout(source, spec["commit"])
    run("codesign", "--force", "--sign", "-", plugin)
    run("codesign", "--verify", "--strict", plugin)
    report = {**inspect_macho(final, 6), "llvm_commit": spec["commit"], "llvm_tag": spec["tag"],
              "license": spec["license"], "dependencies": dependencies, "plugin_exports_verified": sorted(required),
              "cmake_version": subprocess.check_output(["cmake", "--version"], text=True).splitlines()[0],
              "compiler": subprocess.check_output(["xcrun", "clang", "--version"], text=True).strip(),
              "project_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
              "runtime_tested": False, "hardware_tested": False, "deployment_performed": False}
    (notices / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "out", "artifacts", "stage"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    build_air_runtime(args.source, args.out, args.artifacts, args.stage)
