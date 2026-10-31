import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from target_preflight import PreflightError, evaluate, read_inventory, save_report


def inventory(**overrides):
    value = {
        "schema_version": 1,
        "system": {
            "os_version": "26.0.1", "os_build": "25A362", "darwin_release": "25.0.0",
            "architecture": "x86_64", "requested_system_family_matches": True,
        },
        "pci": {
            "selection": "single_registry_match",
            "target_candidates": [{"registry_pci_id": "1002:1900", "assigned_ranges": [{"reported_base": "0x1000"}]}],
            "physical_identity_verified": False,
            "reserved_region_ownership_verified": False,
        },
        "safe_to_initialize": False,
        "gpu_work_submitted": False,
        "hardware_executed": False,
    }
    for key, value_override in overrides.items():
        value[key] = value_override
    return value


class TargetPreflightTests(unittest.TestCase):
    def test_exact_target_allows_only_non_submitting_check(self):
        result = evaluate(inventory())
        self.assertTrue(result["native_probe_check_allowed"])
        self.assertFalse(result["native_probe_run_allowed"])
        self.assertFalse(result["safe_to_initialize"])
        self.assertFalse(result["gpu_work_submitted"])

    def test_wrong_system_or_ambiguous_identity_blocks_check(self):
        value = inventory()
        value["system"]["requested_system_family_matches"] = False
        self.assertFalse(evaluate(value)["native_probe_check_allowed"])
        value = inventory()
        value["pci"]["selection"] = "ambiguous"
        value["pci"]["target_candidates"].append(value["pci"]["target_candidates"][0].copy())
        self.assertFalse(evaluate(value)["native_probe_check_allowed"])

    def test_missing_ranges_blocks_check(self):
        value = inventory()
        value["pci"]["target_candidates"][0]["assigned_ranges"] = []
        self.assertFalse(evaluate(value)["native_probe_check_allowed"])

    def test_positive_execution_claim_blocks_check(self):
        value = inventory(safe_to_initialize=True)
        self.assertFalse(evaluate(value)["native_probe_check_allowed"])

    def test_read_and_output_are_bounded_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "inventory.json"
            source.write_text(json.dumps(inventory()), encoding="utf-8")
            report = save_report(root / "out", evaluate(read_inventory(source)))
            self.assertTrue(report["native_probe_check_allowed"])
            mode = stat.S_IMODE((root / "out" / "preflight.json").stat().st_mode)
            if os.name != "nt":
                self.assertEqual(mode, 0o600)
            self.assertRaises(PreflightError, save_report, root / "out", report)

    def test_malformed_inventory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "inventory.json"
            source.write_text("[]", encoding="utf-8")
            self.assertRaises(PreflightError, read_inventory, source)


if __name__ == "__main__":
    unittest.main()
