"""Stage pinned Mesa and ordered Darwin/Phoenix patches; never install anything."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from prepare_source import ROOT, git, verify_checkout


def ordered_patches(directory, count):
    paths = sorted(Path(directory).glob("*.patch"))
    if len(paths) != count or [p.name[:4] for p in paths] != [f"{i:04d}" for i in range(1, count + 1)]:
        raise RuntimeError(f"Expected exactly {count} consecutively numbered patches in {directory}")
    return paths


def prepare_radv(mesa, cobalt, destination, root=ROOT):
    root, mesa, cobalt, destination = map(lambda p: Path(p).resolve(), (root, mesa, cobalt, destination))
    lock = json.loads((root / "upstream.lock.json").read_text())
    nullarc = root / lock["nullarc"]["path"]
    for path, component in ((mesa, "Mesa"), (cobalt, "Cobalt64"), (nullarc, "nullarc")):
        verify_checkout(path, lock[component]["commit"])
        if destination.is_relative_to(path):
            raise RuntimeError("Staging must be outside all upstream source checkouts")
    if destination.exists():
        raise RuntimeError("Staging directory already exists; choose a fresh destination")
    series = []
    for name, source in (("Cobalt64", cobalt), ("radv-phoenix", nullarc)):
        entry = lock[name]
        for patch in ordered_patches(source / entry["patch_directory"], entry["patch_count"]):
            data = git(source, "show", f"{lock['nullarc' if name == 'radv-phoenix' else name]['commit']}:{patch.relative_to(source).as_posix()}")
            series.append((name, patch.name, data))
    for patch in lock.get("radv-patches", []):
        path = root / patch
        series.append(("downstream", path.name, path.read_bytes().replace(b"\r\n", b"\n")))
    # A detached worktree preserves Git's symlink/mode semantics without unpacking
    # a large tar in memory. Only Git bookkeeping changes in the source cache.
    destination.parent.mkdir(parents=True, exist_ok=True)
    git(mesa, "-c", "core.autocrlf=false", "worktree", "add", "--detach", str(destination), lock["Mesa"]["commit"])
    applied = []
    for component, name, data in series:
        for options in (("--check",), ()):
            subprocess.run(["git", "-C", str(destination), "apply", *options, "-"], input=data, check=True)
        applied.append({"component": component, "name": name,
                        "sha256": hashlib.sha256(data).hexdigest()})
    result = {"mesa_commit": lock["Mesa"]["commit"], "cobalt_commit": lock["Cobalt64"]["commit"],
              "nullarc_commit": lock["nullarc"]["commit"], "patches": applied,
              "hardware_tested": False, "deployment_performed": False}
    (destination / "radv-source-provenance.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesa", type=Path, required=True)
    parser.add_argument("--cobalt", type=Path, required=True)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_radv(args.mesa, args.cobalt, args.destination), indent=2))
