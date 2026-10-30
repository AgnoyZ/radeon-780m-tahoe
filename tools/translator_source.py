"""Fetch and stage the exact LGPL translator source archive; never execute its installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

from prepare_source import ROOT, export_archive

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024


def validate_archive(data, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Translator source SHA-256 mismatch; refusing to extract or build")


def fetch(destination, spec):
    destination = Path(destination)
    if destination.exists():
        validate_archive(destination.read_bytes(), spec["sha256"])
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "radeon-780m-source-build"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if not response.url.startswith("https://"):
                raise RuntimeError("Source download redirected away from HTTPS")
            data = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Translator archive exceeds the pinned source size limit")
        validate_archive(data, spec["sha256"])
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        # Link rather than replace: never overwrite an existing cache or a racing download.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_translator(archive, destination, spec):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Translator staging directory already exists; choose a fresh output")
    data = Path(archive).read_bytes()
    validate_archive(data, spec["sha256"])
    destination.mkdir(parents=True)
    export_archive(data, destination)
    root = (destination / spec["archive_root"]).resolve()
    if not root.is_relative_to(destination):
        raise RuntimeError("Translator source root escapes staging directory")
    for name in ("NOTICE", "translator/LICENSE", "translator/COPYING", "translator/wrapper/Cargo.toml",
                 "translator/wrapper/Cargo.lock", "translator/wrapper/src/lib.rs", "translator/translator/Cargo.toml"):
        if not (root / name).is_file():
            raise RuntimeError("Missing translator source or notice: " + name)
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    spec = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))["nvmtl-translator"]
    fetch(args.destination, spec)
    print(json.dumps({"sha256": spec["sha256"], "verified": True, "executed": False}))
