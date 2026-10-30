"""Fetch pinned Mesa/Cobalt sources into a fresh build cache; no installed-system changes."""
import argparse
import json
from pathlib import Path
import subprocess

from prepare_source import ROOT, verify_checkout


def fetch(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Source cache exists; choose a fresh destination")
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    destination.mkdir(parents=True)
    for component, dirname in (("Mesa", "mesa"), ("Cobalt64", "cobalt")):
        path = destination / dirname
        spec = lock[component]
        def git(*args):
            subprocess.run(["git", "-C", str(path), *args], check=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        git("config", "core.autocrlf", "false")
        git("config", "core.longpaths", "true")
        git("remote", "add", "origin", spec["url"])
        if component == "Cobalt64":
            git("config", "remote.origin.promisor", "true")
            git("config", "remote.origin.partialclonefilter", "blob:none")
            git("sparse-checkout", "set", "--cone", spec["patch_directory"])
        git("-c", "http.lowSpeedLimit=1024", "-c", "http.lowSpeedTime=120", "fetch", "--depth", "1",
            *(["--filter=blob:none"] if component == "Cobalt64" else []), "origin", spec["commit"])
        git("checkout", "--detach", spec["commit"])
        verify_checkout(path, spec["commit"])
        print(component, spec["commit"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    fetch(parser.parse_args().destination)
