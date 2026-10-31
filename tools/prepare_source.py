"""Export pinned source into a NEW staging directory, apply local patches; never install."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from firmware_profile import checked_header

ROOT = Path(__file__).resolve().parents[1]

def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args])

def verify_checkout(path, expected):
    actual = git(path, "rev-parse", "HEAD").decode().strip()
    if actual != expected:
        raise RuntimeError(f"Unexpected source revision: {actual}; expected {expected}")
    if git(path, "status", "--porcelain", "--untracked-files=all").strip():
        raise RuntimeError(f"Source checkout must be clean: {path}")

def export_archive(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for item in archive:
            target = (destination / item.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Archive path leaves staging directory")
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as stream:
                    target.write_bytes(stream.read())
            else:
                raise RuntimeError(f"Unsupported archive entry: {item.name}")

def prepare(destination, root=ROOT):
    destination = Path(destination).resolve()
    lock = json.loads((root / "upstream.lock.json").read_text())
    source = root / lock["nullarc"]["path"]
    verify_checkout(source, lock["nullarc"]["commit"])
    if destination.exists():
        raise RuntimeError("Staging directory already exists; choose a fresh output, do not overwrite")
    firmware_profile = checked_header(root)
    archive = git(source, "archive", lock["nullarc"]["commit"], "src/phxbringup", "src/phxaccel", "src/nmplugin",
                  "tools/phxctl/mesboot.c", "tools/phxctl/phxctl.c", "tools/phxctl/mes_v11_api_def.h", "tools/phxctl/csb_gfx11.h",
                  "LICENSE", "LICENSES", "THIRD_PARTY_NOTICES.md")
    destination.mkdir(parents=True)
    export_archive(archive, destination)
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    patch_hashes = {}
    for name in lock["patches"]:
        path = root / name
        git(destination, "apply", "--check", str(path))
        git(destination, "apply", str(path))
        patch_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = (root / "src/PhxHardwarePolicy.hpp").read_bytes()
    for relative in ("src/phxbringup/PhxHardwarePolicy.hpp", "src/phxaccel/PhxHardwarePolicy.hpp"):
        (destination / relative).write_bytes(policy)
    psp_layout = (root / "src/PhxPspLayout.h").read_bytes()
    (destination / "src/phxbringup/PhxPspLayout.h").write_bytes(psp_layout)
    (destination / "src/phxbringup/PhxFirmwareProfile.h").write_bytes(firmware_profile)
    boot_memory = (root / "src/PhxBootMemory.h").read_bytes()
    gart_layout = (root / "src/PhxGartLayout.h").read_bytes()
    (destination / "src/phxbringup/PhxBootMemory.h").write_bytes(boot_memory)
    (destination / "src/phxbringup/PhxGartLayout.h").write_bytes(gart_layout)
    runtime_path = (root / "src/PhxRuntimePath.h").read_bytes()
    (destination / "src/nmplugin/PhxRuntimePath.h").write_bytes(runtime_path)
    result = {"nullarc_commit": lock["nullarc"]["commit"], "patches_sha256": patch_hashes,
              "policy_sha256": hashlib.sha256(policy).hexdigest(),
              "psp_layout_sha256": hashlib.sha256(psp_layout).hexdigest(),
              "firmware_profile_sha256": hashlib.sha256(firmware_profile).hexdigest(),
              "boot_memory_sha256": hashlib.sha256(boot_memory).hexdigest(),
              "gart_layout_sha256": hashlib.sha256(gart_layout).hexdigest(),
              "runtime_path_sha256": hashlib.sha256(runtime_path).hexdigest(), "hardware_tested": False}
    (destination / "source-provenance.json").write_text(json.dumps(result, indent=2) + "\n")
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.destination), indent=2))
