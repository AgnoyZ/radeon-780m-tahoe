"""Collect whitelisted Intel macOS metadata without loading drivers or changing device configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import struct
import subprocess

COMMANDS = {
    "os_version": ["/usr/bin/sw_vers", "-productVersion"],
    "os_build": ["/usr/bin/sw_vers", "-buildVersion"],
    "darwin_release": ["/usr/sbin/sysctl", "-n", "kern.osrelease"],
    "ram_bytes": ["/usr/sbin/sysctl", "-n", "hw.memsize"],
    "pci": ["/usr/sbin/ioreg", "-a", "-l", "-r", "-c", "IOPCIDevice", "-d", "1"],
}
MAX_BYTES = 16 * 1024 * 1024


class InventoryError(ValueError):
    pass


def integer_property(node, key, maximum):
    value = node.get(key)
    if isinstance(value, bytes) and len(value) == 4:
        value = int.from_bytes(value, "little")
    if type(value) is not int or not 0 <= value <= maximum:
        raise InventoryError("Missing or invalid numeric registry property: " + key)
    return value


def reported_ranges(data):
    # Intel IOPCIFamily serializes five native-endian UInt32 fields per range.
    if not isinstance(data, bytes) or not data or len(data) % 20 or len(data) > 20 * 32:
        raise InventoryError("Invalid assigned-addresses record layout")
    ranges, registers = [], set()
    for flags, high, low, size_high, size_low in struct.iter_unpack("<5I", data):
        register = flags & 0xFF
        space = (flags >> 24) & 3
        base, size = (high << 32) | low, (size_high << 32) | size_low
        if register not in (0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x30) or register in registers:
            raise InventoryError("Invalid or repeated PCI resource register")
        if not size or base > (1 << 64) - size or space not in (1, 2, 3):
            raise InventoryError("Invalid PCI resource extent or address space")
        registers.add(register)
        ranges.append({"register_offset": f"0x{register:02x}", "address_space_code": space,
                       "reported_base": f"0x{base:016x}", "length_bytes": size,
                       "source": "IORegistry assigned-addresses; not an ownership grant"})
    return ranges


def pci_inventory(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise InventoryError("Registry response is missing or exceeds the size limit")
    try:
        nodes = plistlib.loads(data)
    except Exception:
        raise InventoryError("Registry property list is invalid") from None
    if not isinstance(nodes, list) or len(nodes) > 4096 or any(not isinstance(n, dict) for n in nodes):
        raise InventoryError("Registry response is not a bounded PCI-root list")
    if any(n.get("IORegistryEntryChildren") for n in nodes):
        raise InventoryError("Registry response exceeds the requested depth")
    targets, unreadable = [], 0
    for node in nodes:
        try:
            vendor = integer_property(node, "vendor-id", 0xFFFF)
            device = integer_property(node, "device-id", 0xFFFF)
        except InventoryError:
            unreadable += 1
            continue
        if (vendor, device) != (0x1002, 0x1900):
            continue
        candidate = {"registry_pci_id": "1002:1900", "warnings": []}
        for key, maximum in (("class-code", 0xFFFFFF), ("revision-id", 0xFF),
                             ("subsystem-vendor-id", 0xFFFF), ("subsystem-id", 0xFFFF)):
            try:
                candidate[key] = integer_property(node, key, maximum)
            except InventoryError:
                candidate[key] = None
                candidate["warnings"].append(key + "_missing_or_invalid")
        if candidate["class-code"] is None or candidate["class-code"] >> 16 != 3:
            candidate["warnings"].append("display_class_not_confirmed")
        candidate["assigned_ranges"] = None
        if "assigned-addresses" not in node:
            candidate["warnings"].append("assigned_ranges_missing")
        else:
            try:
                candidate["assigned_ranges"] = reported_ranges(node["assigned-addresses"])
            except InventoryError:
                candidate["warnings"].append("assigned_ranges_invalid")
        targets.append(candidate)
    count = len(targets)
    return {"pci_root_count": len(nodes), "unreadable_identity_count": unreadable,
            "target_candidate_count": count, "target_candidates": targets,
            "selection": "not_found" if count == 0 else "single_registry_match" if count == 1 else "ambiguous",
            "identity_source": "IORegistry properties; may be injected or spoofed",
            "physical_identity_verified": False, "reserved_region_ownership_verified": False}


def system_inventory(version, build, darwin, ram, architecture):
    checks = ((version, r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}"),
              (build, r"[0-9]{2}[A-Z][0-9]{1,6}[a-z]?"),
              (darwin, r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}"), (ram, r"[0-9]{1,20}"))
    if any(not re.fullmatch(pattern, value) for value, pattern in checks):
        raise InventoryError("Unexpected system metadata format")
    if architecture not in ("x86_64", "arm64") or not 0 < int(ram) < 1 << 64:
        raise InventoryError("Unsupported system architecture or RAM extent")
    return {"os_version": version, "os_build": build, "darwin_release": darwin,
            "architecture": architecture, "ram_bytes": int(ram),
            "requested_system_family_matches": architecture == "x86_64" and
                int(version.split(".")[0]) == 26 and int(darwin.split(".")[0]) == 25}


def capture(out):
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise InventoryError("Capture requires Intel macOS; no target evidence was collected")
    out = Path(out).resolve()
    if out.exists():
        raise InventoryError("Inventory output exists; choose a fresh directory")
    outputs = {}
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "SYSTEM_VERSION_COMPAT": "0"}
    for label, command in COMMANDS.items():
        try:
            result = subprocess.run(command, capture_output=True, timeout=20, env=environment)
        except subprocess.TimeoutExpired:
            raise InventoryError("Metadata command timed out: " + label) from None
        except OSError:
            raise InventoryError("Metadata command unavailable: " + label) from None
        if result.returncode != 0 or len(result.stdout) > MAX_BYTES:
            raise InventoryError("Metadata command failed or exceeded output limit: " + label)
        outputs[label] = result.stdout
    try:
        strings = {key: outputs[key].decode("ascii").strip() for key in COMMANDS if key != "pci"}
    except UnicodeError:
        raise InventoryError("System metadata is not in its expected numeric format") from None
    system = system_inventory(strings["os_version"], strings["os_build"], strings["darwin_release"],
                              strings["ram_bytes"], platform.machine())
    registry = pci_inventory(outputs["pci"])
    try:
        collector_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        raise InventoryError("Could not identify the collector source revision") from None
    report = {"schema_version": 1, "collector_sha256": collector_hash, "system": system, "pci": registry,
              "safe_to_initialize": False, "gpu_work_submitted": False,
              "privacy": "Local-only metadata; review before sharing. Raw registry/stdout/stderr are not saved.",
              "limitations": ["Registry identity and assigned ranges are not independent PCI configuration-space verification.",
                              "Assigned PCI ranges do not establish usable VRAM, firmware/console reservations or exclusive ownership.",
                              "No GPU IP discovery, firmware parsing, device initialization or acceleration test was performed.",
                              "A successful capture is not permission to load the experimental driver."]}
    try:
        out.mkdir(parents=True, mode=0o700)
        fd = os.open(out / "inventory.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    except OSError:
        raise InventoryError("Could not write private inventory; collection is not reported as successful") from None
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("local/target-inventory"))
    args = parser.parse_args()
    try:
        data = capture(args.out)
    except InventoryError as error:
        parser.exit(1, str(error) + "\n")
    print("Inventory captured locally; no GPU work submitted and initialization remains unapproved.")
    print("Registry target candidate count:", data["pci"]["target_candidate_count"])
