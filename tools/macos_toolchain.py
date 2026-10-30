"""Check real Apple Metal tooling and compile native probes before dependency builds."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import subprocess

from build_radv import runtime_destination, runtime_metadata_destination, write_runtime_metadata, seal_runtime_bundle
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


def packaging_preflight(out):
    """Exercise code/resource sealing with synthetic binaries, never real drivers."""
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Bundle packaging preflight requires Intel macOS")
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("Packaging output exists; choose a fresh directory")
    code = out / "NVMTLDriver.bundle/Contents/MacOS"
    code.mkdir(parents=True)
    source = ROOT / "tests/fixtures/packaging_only.c"
    command = ["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-Wall", "-Wextra", "-Werror"]
    subprocess.run(command + ["-bundle", str(source), "-o", str(code / "NVMTLDriver")], check=True, timeout=60)
    info = {"CFBundleIdentifier": "org.agnoyz.radeon780m.PackagingFixture", "CFBundleExecutable": "NVMTLDriver",
            "CFBundlePackageType": "BNDL", "CFBundleVersion": "1", "CFBundleInfoDictionaryVersion": "6.0"}
    (code.parent / "Info.plist").write_bytes(plistlib.dumps(info))
    destination = runtime_destination(out, True)
    binaries = {}
    for name in ("libvulkan_radeon.dylib", "libnvmtl_translate.dylib", "air-runtime/libLLVM.dylib"):
        library = destination / name
        library.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(command + ["-dynamiclib", str(source), "-o", str(library)], check=True, timeout=60)
        subprocess.run(["codesign", "--force", "--sign", "-", str(library)], check=True, timeout=30)
        subprocess.run(["codesign", "--verify", "--strict", str(library)], check=True, timeout=30)
        binaries[name] = inspect_macho(library, 6)
    write_runtime_metadata(out, True, {"file_format_version": "1.0.0", "ICD": {"api_version": "1.0.0"}},
                           {"synthetic_packaging_fixture": True, "driver_runtime_tested": False})
    seal_runtime_bundle(out)
    resources = runtime_metadata_destination(out, True)
    sealed_resources = []
    for name in ("radeon_icd.json", "radv-build-report.json"):
        resource = resources / name
        original = resource.read_bytes()
        try:
            resource.write_bytes(original + b"\n")
            result = subprocess.run(["codesign", "--verify", "--strict", str(code.parent.parent)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode <= 0:
                raise RuntimeError("Signature verification did not reject altered resource: " + name)
        finally:
            resource.write_bytes(original)
        subprocess.run(["codesign", "--verify", "--strict", str(code.parent.parent)], check=True, timeout=30)
        sealed_resources.append(name)
    return {"synthetic_packaging_fixture": True, "nested_binaries": binaries,
            "sealed_resources_verified": sealed_resources, "bundle_signing_verified": True,
            "driver_runtime_tested": False, "hardware_executed": False}


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
    packaging = packaging_preflight(out / "packaging")
    report = {"metal_compiler": compiler, "cases": reports, "compiled_probes": probes, "packaging": packaging,
              "native_probes_executed": False, "driver_runtime_tested": False, "hardware_executed": False}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    preflight(parser.parse_args().out)
