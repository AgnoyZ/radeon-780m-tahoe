"""Build a conservative, read-only bring-up checklist from a private inventory."""
import argparse
import json
import os
from pathlib import Path
import stat


class PreflightError(ValueError):
    pass


MAX_BYTES = 1024 * 1024


def read_inventory(path):
    path = Path(path).absolute()
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PreflightError("Inventory must be a regular file without links")
        if info.st_size > MAX_BYTES:
            raise PreflightError("Inventory exceeds its size limit")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError:
        raise PreflightError("Inventory cannot be read") from None
    if len(raw) > MAX_BYTES:
        raise PreflightError("Inventory exceeds its size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PreflightError("Inventory is not valid UTF-8 JSON") from None
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PreflightError("Unsupported inventory schema")
    return value


def evaluate(inventory):
    system = inventory.get("system")
    pci = inventory.get("pci")
    if not isinstance(system, dict) or not isinstance(pci, dict):
        raise PreflightError("Inventory is missing system or PCI metadata")
    candidates = pci.get("target_candidates")
    if not isinstance(candidates, list):
        raise PreflightError("Inventory target candidate list is malformed")

    checks = []
    checks.append({
        "name": "darwin25_x86_64",
        "passed": system.get("requested_system_family_matches") is True
        and system.get("architecture") == "x86_64",
        "observed": {key: system.get(key) for key in ("os_version", "os_build", "darwin_release", "architecture")},
    })
    checks.append({
        "name": "single_radeon_780m_identity",
        "passed": pci.get("selection") == "single_registry_match"
        and len(candidates) == 1
        and candidates[0].get("registry_pci_id") == "1002:1900",
        "observed": {"selection": pci.get("selection"), "candidate_count": len(candidates)},
    })
    ranges = candidates[0].get("assigned_ranges") if len(candidates) == 1 else None
    checks.append({
        "name": "assigned_ranges_present",
        "passed": isinstance(ranges, list) and bool(ranges),
        "observed": {"range_count": len(ranges) if isinstance(ranges, list) else None},
    })
    # The collector keeps identity/ownership flags under `pci`, while execution
    # flags are report-level fields. Treat missing or true values as unsafe.
    unsafe_flags = {
        "safe_to_initialize": inventory.get("safe_to_initialize"),
        "physical_identity_verified": pci.get("physical_identity_verified"),
        "reserved_region_ownership_verified": pci.get("reserved_region_ownership_verified"),
        "gpu_work_submitted": inventory.get("gpu_work_submitted"),
        "hardware_executed": inventory.get("hardware_executed"),
    }
    state_safe = all(value is False for value in unsafe_flags.values())
    checks.append({
        "name": "inventory_has_no_positive_execution_claims",
        "passed": state_safe,
        "observed": unsafe_flags,
    })
    identity_ok = all(check["passed"] for check in checks[:2])
    check_allowed = identity_ok and checks[2]["passed"] and checks[3]["passed"]
    return {
        "schema_version": 1,
        "checks": checks,
        "native_probe_check_allowed": check_allowed,
        "native_probe_run_allowed": False,
        "safe_to_initialize": False,
        "physical_identity_verified": False,
        "reserved_region_ownership_verified": False,
        "gpu_work_submitted": False,
        "hardware_executed": False,
        "next_steps": [
            "Review the private inventory and confirm the external Tahoe EFI/recovery path.",
            "On the target only, run native-shader-probe --check; it must create no context, BO or submission.",
            "Do not run native-shader-probe --run until firmware, GPUVM, queue ownership and recovery are separately reviewed.",
        ],
        "limitations": [
            "IORegistry identity and assigned ranges are not independent PCI configuration-space evidence.",
            "This report does not discover GPU IP, firmware residency, UMA reservations, queue ownership or display state.",
            "A passing checklist authorizes only the manual non-submitting --check path, never driver installation or --run.",
        ],
    }


def save_report(out, report):
    out = Path(out).absolute()
    if out.exists():
        raise PreflightError("Preflight output exists; choose a fresh directory")
    try:
        out.mkdir(parents=True, mode=0o700)
        fd = os.open(out / "preflight.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    except OSError:
        raise PreflightError("Could not write private preflight report") from None
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = save_report(args.out, evaluate(read_inventory(args.inventory)))
    except PreflightError as error:
        parser.exit(1, str(error) + "\n")
    print("Preflight written locally; GPU work and initialization remain unapproved.")
    print("native_probe_check_allowed:", result["native_probe_check_allowed"])
