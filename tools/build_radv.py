"""Build the real Mesa RADV Darwin ICD; never install or initialize a GPU."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_source import ROOT, git, verify_checkout
from prepare_radv import prepare_radv
from verify_artifacts import inspect_macho


def meson_command(stage, build):
    return ["meson", "setup", str(build), str(stage), "--buildtype=release", "--wrap-mode=nofallback",
            "-Dvulkan-drivers=amd", "-Dgallium-drivers=", "-Dplatforms=", "-Dllvm=disabled",
            "-Dglx=disabled", "-Degl=disabled", "-Dgbm=disabled", "-Dopengl=false",
            "-Dgles1=disabled", "-Dgles2=disabled", "-Dxmlconfig=disabled", "-Dvalgrind=disabled",
            "-Dlibunwind=disabled", "-Dzstd=disabled", "-Dspirv-tools=disabled",
            "-Dbuild-tests=false", "-Dvulkan-layers=", "-Dtools="]


def system_dependencies(otool_output):
    entries = [line.strip().split(" (", 1)[0] for line in otool_output.splitlines()[1:] if line.strip()]
    if not entries or entries[0] != "@rpath/libvulkan_radeon.dylib":
        raise ValueError("Unexpected RADV dylib identity")
    for entry in entries[1:]:
        if not entry.startswith(("/usr/lib/", "/System/Library/")):
            raise ValueError("Non-system RADV dependency: " + entry)
    return entries[1:]


def run(*args):
    print("RUN", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def test_no_device(probe, library):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("RADV_", "AMD_", "VK_", "MESA_", "DYLD_"))}
    variants = [("native", {}, "IOServiceOpen(PhxBringup"),
                ("reject_mock", {"RADV_DARWIN_MOCK": "1"}, "mock and host-only backends are disabled"),
                ("reject_host_only", {"RADV_DARWIN_HOST_BO": "1"}, "mock and host-only backends are disabled"),
                ("reject_other_gpu", {"RADV_DARWIN_CANNED": "gfx1201"}, "only the Phoenix device profile is supported")]
    report = {}
    for name, environment, diagnostic in variants:
        result = subprocess.run([str(probe), str(library)], env={**clean, **environment},
                                capture_output=True, text=True, timeout=30)
        print(name, result.stdout, result.stderr, flush=True)
        if result.returncode != 0 or diagnostic not in result.stderr:
            raise RuntimeError(f"RADV no-device test {name} failed ({result.returncode})")
        data = json.loads(result.stdout)
        if data != {"runtime_loaded": True, "physical_devices": 0, "gpu_submitted": False}:
            raise RuntimeError(f"Unexpected no-device result for {name}")
        report[name] = data
    return report


def runtime_metadata_destination(artifacts, plugin_bundle):
    return Path(artifacts) / ("NVMTLDriver.bundle/Contents/Resources" if plugin_bundle else "nvmtl")


def icd_library_path(plugin_bundle):
    return "../MacOS/libvulkan_radeon.dylib" if plugin_bundle else "./libvulkan_radeon.dylib"


def write_runtime_metadata(artifacts, plugin_bundle, manifest, report):
    destination = runtime_metadata_destination(artifacts, plugin_bundle)
    paths = [destination / name for name in ("radeon_icd.json", "radv-build-report.json")]
    if any(path.exists() for path in paths):
        raise RuntimeError("RADV metadata already exists; refusing overwrite")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {**manifest, "ICD": {**manifest["ICD"], "library_path": icd_library_path(plugin_bundle)}}
    for path, data in zip(paths, (manifest, report)):
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(data, indent=2) + "\n")


def seal_runtime_bundle(artifacts):
    plugin = Path(artifacts) / "NVMTLDriver.bundle"
    run("codesign", "--force", "--sign", "-", plugin)
    run("codesign", "--verify", "--strict", plugin)


def runtime_destination(artifacts, plugin_bundle):
    artifacts = Path(artifacts)
    destination = artifacts / ("NVMTLDriver.bundle/Contents/MacOS" if plugin_bundle else "nvmtl")
    if plugin_bundle:
        if not (destination / "NVMTLDriver").is_file():
            raise RuntimeError("Build the actual plugin before staging its RADV runtime")
        if any((destination / name).exists() for name in
               ("libvulkan_radeon.dylib", "radeon_icd.json", "radv-build-report.json")):
            raise RuntimeError("RADV artifacts already exist; refusing overwrite")
        resources = runtime_metadata_destination(artifacts, True)
        if any((resources / name).exists() for name in ("radeon_icd.json", "radv-build-report.json")):
            raise RuntimeError("RADV metadata already exists; refusing overwrite")
    elif destination.exists():
        raise RuntimeError("RADV artifacts already exist; refusing overwrite")
    return destination


def build_radv(mesa, cobalt, headers, out, artifacts, plugin_bundle=False):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("RADV requires a native Intel macOS build host; other hosts are not a build pass")
    mesa, cobalt, headers, out, artifacts = map(lambda p: Path(p).resolve(), (mesa, cobalt, headers, out, artifacts))
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    verify_checkout(headers, lock["Vulkan-Headers"]["commit"])
    if out.exists():
        raise RuntimeError("RADV output exists; choose a fresh path")
    destination = runtime_destination(artifacts, plugin_bundle)
    stage = out / "source"
    provenance = prepare_radv(mesa, cobalt, stage)
    abi_probe = out / "radv-abi"
    run("xcrun", "clang", "-arch", "x86_64", "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-I" + str(stage / "include/darwin"), "-I" + str(ROOT / "upstream/nullarc/src/phxbringup"),
        ROOT / "tests/test_radv_abi.c", "-o", abi_probe)
    run(abi_probe)
    native = out / "native"
    run(*meson_command(stage, native))
    run("ninja", "-C", native, "-j", str(min(os.cpu_count() or 2, 4)))
    library = native / "src/amd/vulkan/libvulkan_radeon.dylib"
    inspect_macho(library, 6)
    destination.mkdir(parents=True, exist_ok=plugin_bundle)
    final = destination / library.name
    shutil.copy2(library, final)
    dependencies = system_dependencies(subprocess.check_output(["xcrun", "otool", "-L", str(final)], text=True))
    run("codesign", "--force", "--sign", "-", final)
    run("codesign", "--verify", "--strict", final)
    exports = subprocess.check_output(["xcrun", "nm", "-gU", str(final)], text=True)
    defined = {line.split()[-1] for line in exports.splitlines() if line.split()}
    for symbol in ("_vk_icdGetInstanceProcAddr", "_radv_darwin_set_service_class"):
        if symbol not in defined:
            raise RuntimeError(f"RADV lacks required export {symbol}")
    # Preserve upstream-generated API metadata, but make the staged manifest relocatable.
    manifest = json.loads((native / "src/amd/vulkan/radeon_devenv_icd.x86_64.json").read_text())
    licenses = artifacts / "DEPENDENCY-LICENSES/Mesa-RADV"
    shutil.copytree(stage / "licenses", licenses / "licenses")
    shutil.copy2(stage / "docs/license.rst", licenses / "Mesa-license.rst")
    shutil.copy2(cobalt / "LICENSE", licenses / "Cobalt64-LICENSE")
    shutil.copy2(cobalt / "mesa-patches/README.txt", licenses / "Cobalt64-patches-README.txt")
    (licenses / "source-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    probe = out / "radv-no-device"
    run("xcrun", "clang", "-arch", "x86_64", "-std=c11", "-mmacosx-version-min=15.0", "-Wall", "-Wextra", "-Werror",
        "-I" + str(headers / "include"), "-framework", "IOKit", "-framework", "CoreFoundation",
        ROOT / "tools/radv_no_device.c", "-o", probe)
    tests = test_no_device(probe, final)
    report = {**provenance, **inspect_macho(final, 6), "runtime_tests": tests,
              "native_transport_layout_verified": True,
              "host": platform.platform(), "metal_stack_complete": False,
              "dependencies": dependencies, "runtime_dependency_policy": "system-only",
              "runtime_layout": "plugin-relative" if plugin_bundle else "standalone-nvmtl",
              "meson_version": subprocess.check_output(["meson", "--version"], text=True).strip(),
              "ninja_version": subprocess.check_output(["ninja", "--version"], text=True).strip(),
              "glslang_version": subprocess.check_output(["glslangValidator", "--version"], text=True).strip(),
              "compiler": subprocess.check_output(["xcrun", "clang", "--version"], text=True).strip(),
              "project_commit": git(ROOT, "rev-parse", "HEAD").decode().strip()}
    write_runtime_metadata(artifacts, plugin_bundle, manifest, report)
    if plugin_bundle:
        # Seal resources and nested code now, before the expensive LLVM build.
        seal_runtime_bundle(artifacts)
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesa", type=Path, required=True)
    parser.add_argument("--cobalt", type=Path, required=True)
    parser.add_argument("--vulkan-headers", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    build_radv(args.mesa, args.cobalt, args.vulkan_headers, args.out, args.artifacts)
