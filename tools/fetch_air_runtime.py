"""Fetch exact LLVM sources for the AIR reader, not a prebuilt host library."""
import argparse
import json
from pathlib import Path
import subprocess

from prepare_source import ROOT, verify_checkout


def fetch(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("LLVM source cache exists; choose a fresh destination")
    spec = json.loads((ROOT / "upstream.lock.json").read_text())["LLVM"]
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    def git(*args):
        subprocess.run(["git", "-C", str(destination), *args], check=True)
    git("config", "core.longpaths", "true")
    git("config", "core.autocrlf", "false")
    git("remote", "add", "origin", spec["url"])
    git("config", "remote.origin.promisor", "true")
    git("config", "remote.origin.partialclonefilter", "blob:none")
    git("sparse-checkout", "set", "--cone", "llvm/lib", "llvm/include", "llvm/cmake", "llvm/utils",
        "llvm/tools/llvm-shlib", "llvm/projects", "cmake", "third-party")
    git("-c", "http.lowSpeedLimit=1024", "-c", "http.lowSpeedTime=120", "fetch", "--depth", "1",
        "--filter=blob:none", "origin", spec["commit"])
    git("checkout", "--detach", spec["commit"])
    verify_checkout(destination, spec["commit"])
    print(json.dumps({"llvm_commit": spec["commit"], "source_verified": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    fetch(parser.parse_args().destination)
