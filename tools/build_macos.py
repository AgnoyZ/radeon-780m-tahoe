"""Build experimental x86_64 kexts, Metal plugin and correctness probe; NEVER install/load them."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess

from prepare_source import ROOT, git, prepare, verify_checkout
from verify_artifacts import inspect_kext, inspect_macho, inspect_plugin
from build_userspace import build_plugin, PLUGIN_IDENTIFIER
from build_translator import build_translator

def run(*args):
    print("RUN", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--vulkan-headers", type=Path, required=True)
    parser.add_argument("--translator-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "build/experimental")
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("A macOS build host with Xcode Command Line Tools is required; Windows is not a build pass")
    sdk = args.sdk.resolve()
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    verify_checkout(sdk, lock["MacKernelSDK"]["commit"])
    headers = args.vulkan_headers.resolve()
    verify_checkout(headers, lock["Vulkan-Headers"]["commit"])
    if not (headers / "include/vulkan/vulkan.h").is_file():
        raise RuntimeError("Vulkan-Headers dependency lacks vulkan.h")
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
    report["NVMTLDriver"] = build_plugin(stage, headers, artifacts, run)
    report["nvmtl-translator"] = build_translator(args.translator_source.resolve(), lock["nvmtl-translator"],
                                                 out, artifacts, stage, run)
    plugin = artifacts / "NVMTLDriver.bundle"
    run("codesign", "--force", "--sign", "-", plugin)
    run("codesign", "--verify", "--strict", plugin)
    # Adding the dylib changes the enclosing resource seal; report the final signed binary.
    report["NVMTLDriver"].update(inspect_plugin(plugin, PLUGIN_IDENTIFIER))
    report["NVMTLDriver"]["missing_runtime_dependencies"].remove("AIR-to-SPIR-V translator")
    smoke = artifacts / "metal-smoke"
    run("xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=13.0", "-fobjc-arc", "-fblocks",
        "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", "-framework", "Metal",
        ROOT / "tools/metal_smoke.m", "-o", smoke)
    report["metal-smoke"] = inspect_macho(smoke, 2)
    shutil.copytree(stage / "LICENSES", artifacts / "LICENSES")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(stage / name, artifacts / ("UPSTREAM-" + name))
    header_notices = artifacts / "DEPENDENCY-LICENSES/Vulkan-Headers"
    header_notices.mkdir(parents=True)
    shutil.copy2(headers / "LICENSE.md", header_notices / "LICENSE.md")
    shutil.copytree(headers / "LICENSES", header_notices / "LICENSES")
    shutil.copy2(ROOT / "docs/EXPERIMENTAL.md", artifacts / "READ-BEFORE-USE.md")
    provenance.update({"sdk_commit": lock["MacKernelSDK"]["commit"],
                       "vulkan_headers_commit": lock["Vulkan-Headers"]["commit"],
                       "translator_source_sha256": lock["nvmtl-translator"]["sha256"],
                       "project_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
                       "project_dirty": bool(git(ROOT, "status", "--porcelain").strip()),
                       "compiler": subprocess.check_output(["xcrun", "clang", "--version"]).decode(),
                       "host": platform.platform(), "artifacts": report,
                       "deployment_performed": False, "hardware_tested": False,
                       "metal_stack_complete": False})
    (artifacts / "build-report.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))

if __name__ == "__main__":
    main()
