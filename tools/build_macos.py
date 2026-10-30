"""Build experimental x86_64 kexts and the Metal correctness probe; NEVER install/load them."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess

from prepare_source import ROOT, git, prepare, verify_checkout
from verify_artifacts import inspect_kext, inspect_macho

def run(*args):
    print("RUN", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "build/experimental")
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("A macOS build host with Xcode Command Line Tools is required; Windows is not a build pass")
    sdk = args.sdk.resolve()
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    verify_checkout(sdk, lock["MacKernelSDK"]["commit"])
    if not (sdk / "Library/x86_64/libkmod.a").is_file():
        raise RuntimeError("SDK lacks the x86_64 kmod library")
    out = args.out.resolve()
    if out.exists():
        raise RuntimeError("Output already exists; choose a fresh --out")
    stage = out / "stage"
    provenance = prepare(stage)
    artifacts = out / "artifacts"
    artifacts.mkdir()
    base = ["-arch", "x86_64", "-mmacosx-version-min=11.0", "-mkernel", "-fno-builtin", "-fno-common",
            "-nostdinc", "-I" + str(sdk / "Headers"), "-DKERNEL", "-DKERNEL_PRIVATE", "-DDRIVER_PRIVATE",
            "-DAPPLE", "-DNeXT", "-O2", "-Wall"]
    cpp = base + ["-std=c++17", "-fapple-kext", "-fno-rtti", "-fno-exceptions"]
    report = {}
    for component, identifier in (("PhxBringup", "org.drip.PhxBringup"), ("PhxAccel", "com.luuumi.PhxAccel")):
        src = stage / "src" / component.lower()
        objdir = out / "objects" / component
        objdir.mkdir(parents=True)
        objects = []
        if component == "PhxBringup":
            for filename, flags, compiler in (("kmod_info.c", base, "clang"), ("PhxBringup.cpp", cpp, "clang++")):
                obj = objdir / (Path(filename).stem + ".o")
                run("xcrun", compiler, *flags, "-c", src / filename, "-o", obj)
                objects.append(obj)
            libs = ["-lkmod", "-lcc_kext"]
        else:
            flags = cpp + ["-I" + str(src), "-I" + str(src / "accel"), "-I" + str(src / "accel/iofam"),
                           "-I" + str(src / "accel/re"), "-DNMX_ACCEL", "-DNM_TAHOE", "-DPHX_FB",
                           "-Wno-unused-parameter", "-Wno-inconsistent-missing-override",
                           "-Wno-unused-function", "-Wno-unused-variable"]
            for filename in ("nvrm-accel.cpp", "phxfb.cpp", "phxagdc.cpp"):
                obj = objdir / (Path(filename).stem + ".o")
                run("xcrun", "clang++", *flags, "-c", src / "accel" / filename, "-o", obj)
                objects.append(obj)
            libs = ["-lkmodc++", "-lkmod", "-lcc_kext"]
        bundle = artifacts / (component + ".kext")
        executable = bundle / "Contents/MacOS" / component
        executable.parent.mkdir(parents=True)
        run("xcrun", "clang++", "-arch", "x86_64", "-mmacosx-version-min=11.0", "-nostdlib", "-Xlinker", "-kext",
            "-L" + str(sdk / "Library/x86_64"), *libs, *objects, "-o", executable)
        shutil.copy2(src / "Info.plist", bundle / "Contents/Info.plist")
        run("codesign", "--force", "--sign", "-", bundle)
        run("codesign", "--verify", "--strict", bundle)
        report[component] = inspect_kext(bundle, identifier)
    smoke = artifacts / "metal-smoke"
    run("xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=13.0", "-fobjc-arc", "-fblocks",
        "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", "-framework", "Metal",
        ROOT / "tools/metal_smoke.m", "-o", smoke)
    report["metal-smoke"] = inspect_macho(smoke, 2)
    shutil.copytree(stage / "LICENSES", artifacts / "LICENSES")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(stage / name, artifacts / ("UPSTREAM-" + name))
    shutil.copy2(ROOT / "docs/EXPERIMENTAL.md", artifacts / "READ-BEFORE-USE.md")
    provenance.update({"sdk_commit": lock["MacKernelSDK"]["commit"], "project_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
                       "project_dirty": bool(git(ROOT, "status", "--porcelain").strip()),
                       "compiler": subprocess.check_output(["xcrun", "clang", "--version"]).decode(),
                       "host": platform.platform(), "artifacts": report,
                       "deployment_performed": False, "hardware_tested": False,
                       "metal_stack_complete": False})
    (artifacts / "build-report.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))

if __name__ == "__main__":
    main()
