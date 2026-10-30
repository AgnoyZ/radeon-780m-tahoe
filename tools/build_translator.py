"""Build the pinned real Rust translator as a replaceable plugin-adjacent dylib."""
import hashlib
from pathlib import Path
import shutil
import subprocess

from translator_source import prepare_translator
from test_translator_runtime import required_translator_exports
from verify_artifacts import inspect_macho


def build_translator(archive, spec, out, artifacts, stage, run):
    out, artifacts, stage = Path(out), Path(artifacts), Path(stage)
    source = prepare_translator(archive, out / "translator-source", spec)
    manifest = source / "translator/wrapper/Cargo.toml"
    lock = source / "translator/wrapper/Cargo.lock"
    lock_before = hashlib.sha256(lock.read_bytes()).hexdigest()
    target = out / "translator-target"
    run("cargo", "+" + spec["rust_toolchain"], "build", "--locked", "--release", "--lib",
        "--manifest-path", manifest, "--target", spec["target"], "--target-dir", target)
    if hashlib.sha256(lock.read_bytes()).hexdigest() != lock_before:
        raise RuntimeError("Cargo.lock changed despite a locked build")
    built = target / spec["target"] / "release/libnvmtl_translate.dylib"
    executable = artifacts / "NVMTLDriver.bundle/Contents/MacOS/libnvmtl_translate.dylib"
    shutil.copy2(built, executable)
    run("xcrun", "strip", "-S", executable)
    run("install_name_tool", "-id", "@rpath/libnvmtl_translate.dylib", executable)
    exports = subprocess.check_output(["xcrun", "nm", "-gU", str(executable)], text=True)
    defined = {line.split()[-1] for line in exports.splitlines() if len(line.split()) >= 3}
    required = required_translator_exports(stage / "src/nmplugin/NVMTLLibraryLoad.m")
    missing = {"_" + name for name in required} - defined
    if missing:
        raise RuntimeError("Translator is missing plugin FFI exports: " + ", ".join(sorted(missing)))
    run("codesign", "--force", "--sign", "-", executable)
    run("codesign", "--verify", "--strict", executable)
    notices = artifacts / "DEPENDENCY-LICENSES/nvmtl-translator"
    notices.mkdir(parents=True)
    shutil.copy2(source / "NOTICE", notices / "NOTICE")
    for name in ("LICENSE", "COPYING"):
        shutil.copy2(source / "translator" / name, notices / name)
    source_copy = artifacts / "SOURCE"
    source_copy.mkdir()
    shutil.copy2(archive, source_copy / "nvmtl-translator-source.tar.gz")
    report = inspect_macho(executable, 6)
    report.update({"source_sha256": spec["sha256"], "source_url": spec["url"],
                   "cargo_lock_sha256": lock_before, "rust_toolchain": spec["rust_toolchain"],
                   "rustc": subprocess.check_output(["rustc", "+" + spec["rust_toolchain"], "--version"], text=True).strip(),
                   "plugin_ffi_exports_verified": sorted(required),
                   "hardware_tested": False, "license": spec["license"]})
    return report
