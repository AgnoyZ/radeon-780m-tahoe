import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from target_inventory import COMMANDS, InventoryError, capture, pci_inventory, reported_ranges, system_inventory


def fixture_device(device=0x1900):
    return {"vendor-id": struct.pack("<I", 0x1002), "device-id": struct.pack("<I", device),
            "class-code": struct.pack("<I", 0x030000), "revision-id": struct.pack("<I", 0xC2),
            "assigned-addresses": struct.pack("<5I", 0x82000110, 1, 0, 0, 0x10000000),
            "IORegistryEntryName": "PRIVATE_NAME", "IORegistryEntryID": 123456789,
            "IOPlatformSerialNumber": "PRIVATE_SERIAL", "system-id": b"PRIVATE_UUID",
            "ROM": b"PRIVATE_ROM", "other": {"nested": "PRIVATE_NESTED"}}


class TargetInventoryTests(unittest.TestCase):
    def test_whitelisted_properties_do_not_export_names_serials_or_dumps(self):
        result = pci_inventory(plistlib.dumps([fixture_device()]))
        self.assertEqual(1, result["target_candidate_count"])
        target = result["target_candidates"][0]
        self.assertEqual("1002:1900", target["registry_pci_id"])
        self.assertEqual("0x0000000100000000", target["assigned_ranges"][0]["reported_base"])
        self.assertEqual(0x10000000, target["assigned_ranges"][0]["length_bytes"])
        text = json.dumps(result)
        for sensitive in ("PRIVATE_", "123456789", '"IORegistryEntryName"', '"ROM"', '"system-id"'):
            self.assertNotIn(sensitive, text)
        self.assertFalse(result["physical_identity_verified"])
        self.assertFalse(result["reserved_region_ownership_verified"])

    def test_missing_and_multiple_matches_are_not_a_ready_device(self):
        absent = pci_inventory(plistlib.dumps([fixture_device(0xFFFF)]))
        self.assertEqual("not_found", absent["selection"])
        ambiguous = pci_inventory(plistlib.dumps([fixture_device(), fixture_device()]))
        self.assertEqual("ambiguous", ambiguous["selection"])
        self.assertEqual(2, ambiguous["target_candidate_count"])

    def test_malformed_identity_remains_unknown_not_zero(self):
        for value in (b"\x02\x10", True, -1, 0x10000, "1002"):
            node = fixture_device(); node["vendor-id"] = value
            result = pci_inventory(plistlib.dumps([node]))
            self.assertEqual(1, result["unreadable_identity_count"])
            self.assertEqual(0, result["target_candidate_count"])

    def test_missing_and_invalid_resources_are_not_fabricated(self):
        node = fixture_device(); del node["assigned-addresses"]
        target = pci_inventory(plistlib.dumps([node]))["target_candidates"][0]
        self.assertIsNone(target["assigned_ranges"])
        self.assertIn("assigned_ranges_missing", target["warnings"])
        node["assigned-addresses"] = b"PRIVATE_INVALID_RESOURCE"
        target = pci_inventory(plistlib.dumps([node]))["target_candidates"][0]
        self.assertIsNone(target["assigned_ranges"])
        self.assertIn("assigned_ranges_invalid", target["warnings"])

    def test_range_parser_rejects_overflow_duplicates_and_partial_records(self):
        valid = struct.pack("<5I", 0x82000010, 1, 0, 0, 4096)
        for data in (b"x", valid[:-1], valid + valid, struct.pack("<5I", 0x82000010, 0xFFFFFFFF, 0xFFFFFFFF, 0, 2),
                     struct.pack("<5I", 0x82000010, 0, 0, 0, 0)):
            with self.subTest(data=data), self.assertRaises(InventoryError):
                reported_ranges(data)

    def test_registry_input_must_be_bounded_flat_xml(self):
        for data in (b"PRIVATE_INVALID_XML", plistlib.dumps({}), plistlib.dumps(["not a PCI node"]),
                     plistlib.dumps([{"IORegistryEntryChildren": [fixture_device()]}])):
            with self.assertRaises(InventoryError) as caught:
                pci_inventory(data)
            self.assertNotIn("PRIVATE", str(caught.exception))

    def test_system_version_is_observed_not_assumed(self):
        result = system_inventory("26.0.1", "25A362", "25.0.0", "34359738368", "x86_64")
        self.assertTrue(result["requested_system_family_matches"])
        self.assertEqual("25A362", result["os_build"])
        self.assertFalse(system_inventory("14.7", "23H124", "23.6.0", "34359738368", "x86_64")["requested_system_family_matches"])
        self.assertFalse(system_inventory("26.0.1", "25A362", "25.0.0", "34359738368", "arm64")["requested_system_family_matches"])
        with self.assertRaises(InventoryError):
            system_inventory("PRIVATE_NAME", "25A362", "25.0.0", "34359738368", "x86_64")

    def test_capture_uses_only_fixed_read_commands_and_writes_no_raw_data(self):
        outputs = {"os_version": b"26.0.1\n", "os_build": b"25A362\n", "darwin_release": b"25.0.0\n",
                   "ram_bytes": b"34359738368\n", "pci": plistlib.dumps([fixture_device()])}
        def run(command, **kwargs):
            label = next(k for k, v in COMMANDS.items() if v == command)
            self.assertEqual(20, kwargs["timeout"])
            self.assertEqual("0", kwargs["env"]["SYSTEM_VERSION_COMPAT"])
            self.assertNotIn("DYLD_LIBRARY_PATH", kwargs["env"])
            self.assertFalse(kwargs.get("shell", False))
            return subprocess.CompletedProcess(command, 0, outputs[label], b"PRIVATE_STDERR")
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch("target_inventory.platform.system", return_value="Darwin"), \
             mock.patch("target_inventory.platform.machine", return_value="x86_64"), \
             mock.patch("target_inventory.subprocess.run", side_effect=run) as called:
            out = Path(temporary) / "capture"
            result = capture(out)
            self.assertEqual(5, called.call_count)
            self.assertEqual(["inventory.json"], sorted(p.name for p in out.iterdir()))
            self.assertFalse(result["safe_to_initialize"])
            self.assertFalse(result["gpu_work_submitted"])
            self.assertNotIn("PRIVATE", (out / "inventory.json").read_text())
            with self.assertRaises(InventoryError):
                capture(out)
            self.assertEqual(5, called.call_count)

    def test_failed_capture_does_not_publish_a_partial_success(self):
        for error in (subprocess.TimeoutExpired("ioreg", 20, output=b"PRIVATE_TIMEOUT"),
                      subprocess.CompletedProcess([], 1, b"PRIVATE_STDOUT", b"PRIVATE_STDERR")):
            with tempfile.TemporaryDirectory() as temporary, \
                 mock.patch("target_inventory.platform.system", return_value="Darwin"), \
                 mock.patch("target_inventory.platform.machine", return_value="x86_64"), \
                 mock.patch("target_inventory.subprocess.run") as run:
                if isinstance(error, Exception): run.side_effect = error
                else: run.return_value = error
                out = Path(temporary) / "new"
                with self.assertRaises(InventoryError) as caught: capture(out)
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertFalse(out.exists())

    def test_non_macos_host_is_not_a_capture_pass(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch("target_inventory.platform.system", return_value="Windows"), \
             mock.patch("target_inventory.subprocess.run") as run:
            out = Path(temporary) / "new"
            with self.assertRaises(InventoryError): capture(out)
            run.assert_not_called()
            self.assertFalse(out.exists())

    def test_arm_mac_does_not_use_the_intel_resource_layout(self):
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch("target_inventory.platform.system", return_value="Darwin"), \
             mock.patch("target_inventory.platform.machine", return_value="arm64"), \
             mock.patch("target_inventory.subprocess.run") as run:
            out = Path(temporary) / "new"
            with self.assertRaises(InventoryError): capture(out)
            run.assert_not_called()
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
