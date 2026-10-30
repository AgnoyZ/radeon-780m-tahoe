"""Native source build of the upstream Metal plugin; no install or GPU initialization."""
import hashlib
from pathlib import Path
import plistlib
import subprocess

from verify_artifacts import inspect_plugin

PLUGIN_IDENTIFIER = "org.agnoyz.radeon780m.NVMTLDriver"


def plugin_command(source, headers, executable):
    # Mirrors the upstream release compiler recipe, not its machine-local copy/deploy script.
    command = ["xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=15.0", "-bundle",
               "-fobjc-arc", "-O1", "-DNVMTL_RELEASE=1", "-Wno-protocol",
               "-Wno-incomplete-implementation", "-Werror=unguarded-availability-new",
               "-I" + str(Path(headers) / "include"), "-o", str(executable),
               str(Path(source) / "NVMTLDevice.m")]
    for framework in ("Foundation", "Metal", "IOSurface", "IOKit", "CoreFoundation"):
        command.extend(["-framework", framework])
    return command


def plugin_info():
    return {
        "CFBundleIdentifier": PLUGIN_IDENTIFIER,
        "CFBundleName": "NVMTLDriver",
        "CFBundleExecutable": "NVMTLDriver",
        "CFBundlePackageType": "BNDL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSPrincipalClass": "NVMTLDevice",
        "LSMinimumSystemVersion": "26.0",
        "NSHumanReadableCopyright": "Derived from nullarc / NullMoth Systems. PolyForm Noncommercial 1.0.0; see included notices.",
    }


def require_plugin_exports(nm_output):
    defined = set()
    for line in nm_output.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in {"S", "D", "B", "T"}:
            defined.add(parts[2])
    required = {"_OBJC_CLASS_$_NVMTLDevice", "_OBJC_METACLASS_$_NVMTLDevice"}
    missing = required - defined
    if missing:
        raise ValueError("Metal plugin is missing defined exports: " + ", ".join(sorted(missing)))


def build_plugin(stage, headers, artifacts, run):
    source = Path(stage) / "src/nmplugin"
    bundle = Path(artifacts) / "NVMTLDriver.bundle"
    if bundle.exists():
        raise RuntimeError("Plugin output already exists; refusing to overwrite")
    executable = bundle / "Contents/MacOS/NVMTLDriver"
    executable.parent.mkdir(parents=True)
    info_bytes = plistlib.dumps(plugin_info())
    (bundle / "Contents/Info.plist").write_bytes(info_bytes)
    run(*plugin_command(source, headers, executable))
    exports = subprocess.check_output(["xcrun", "nm", "-gU", str(executable)], text=True)
    require_plugin_exports(exports)
    run("codesign", "--force", "--sign", "-", bundle)
    run("codesign", "--verify", "--strict", bundle)
    report = inspect_plugin(bundle, PLUGIN_IDENTIFIER)
    report.update({"info_plist_sha256": hashlib.sha256(info_bytes).hexdigest(),
                   "entrypoint_exports_verified": True,
                   "source_entrypoint": "src/nmplugin/NVMTLDevice.m",
                   "runtime_loaded": False,
                   "missing_runtime_dependencies": ["Mesa RADV Darwin ICD", "AIR-to-SPIR-V translator",
                                                    "translator runtime dependencies", "GPU firmware and bring-up"]})
    return report
