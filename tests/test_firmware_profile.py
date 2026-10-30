import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from firmware_profile import checked_header, load_profile, profile, render
from prepare_source import prepare


class FirmwareProfileTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((ROOT / "firmware.lock.json").read_text())
        self.audit = json.loads((ROOT / "docs/validation/firmware-08624cd.json").read_text())

    def test_exact_reference_recipe_and_component_selection(self):
        data = profile(self.lock, self.audit)
        self.assertEqual(9, len(data["files"]))
        self.assertEqual([0, 2, 1, 4, 71, 72, 33, 34, 81, 82, 68, 69, 20, 21, 26, 48, 25, 8],
                         [s["fw_type"] for s in data["steps"]])
        self.assertEqual("toc", data["steps"][0]["component"])
        self.assertEqual((256, 267008), (data["steps"][3]["file_offset"], data["steps"][3]["size_bytes"]))
        self.assertNotIn("jump_table", [s["component"] for s in data["steps"]])

    def test_profile_header_is_deterministic_and_metadata_only(self):
        first = checked_header()
        self.lock["files"].reverse()
        # Canonical array order is part of the lock digest, so refresh that binding.
        self.audit["manifest"]["lock_sha256"] = hashlib.sha256(
            json.dumps(self.lock, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        data = profile(self.lock, self.audit)
        self.assertEqual(load_profile()["files"], data["files"])
        self.assertEqual(load_profile()["steps"], data["steps"])
        self.assertEqual(first, render(load_profile()).encode())
        self.assertLess(len(first), 4096)

    def test_mismatched_revision_and_identity_are_rejected(self):
        for field, value in (("sha256", "0" * 64), ("size_bytes", 1), ("kind", "wrong"),
                             ("header_version", [9, 9]), ("ip_version", [9, 9])):
            audit = copy.deepcopy(self.audit)
            audit["manifest"]["files"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): profile(self.lock, audit)
        for place, field in ((self.audit, "source_commit"), (self.audit["manifest"], "lock_sha256")):
            old = place[field]
            place[field] = "0" * len(old)
            with self.assertRaises(ValueError): profile(self.lock, self.audit)
            place[field] = old

    def test_missing_duplicate_extra_files_are_rejected(self):
        for collection in (self.lock["files"], self.audit["manifest"]["files"]):
            saved = copy.deepcopy(collection)
            for replacement in (saved[:-1], saved + [saved[0]], saved[:-1] + [saved[0]]):
                collection[:] = replacement
                with self.assertRaises(ValueError): profile(self.lock, self.audit)
            collection[:] = saved

    def test_missing_duplicate_and_invalid_components_are_rejected(self):
        entry = self.audit["manifest"]["files"][0]
        saved = copy.deepcopy(entry["components"])
        for replacement in ([], saved + [saved[0]]):
            entry["components"] = replacement
            with self.assertRaises(ValueError): profile(self.lock, self.audit)
        entry["components"] = saved
        for field, values in (("file_offset", (True, -4, 0, 257, 0xffffffff, "256")),
                              ("size_bytes", (False, 0, -4, 3, 0xffffffff, "16"))):
            old = saved[0][field]
            for value in values:
                saved[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    profile(self.lock, self.audit)
            saved[0][field] = old
        for value in (True, 0, "48", entry["size_bytes"] + 1):
            entry["header_size_bytes"] = value
            with self.assertRaises(ValueError): profile(self.lock, self.audit)

    def test_header_check_accepts_crlf_but_rejects_stale_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            header = root / "src/PhxFirmwareProfile.h"
            with mock.patch("firmware_profile.load_profile", return_value=load_profile()):
                with self.assertRaises(ValueError): checked_header(root)
                header.write_bytes(render(load_profile()).replace("\n", "\r\n").encode())
                self.assertEqual(checked_header(), checked_header(root))
                header.write_text("stale\n")
                with self.assertRaises(ValueError): checked_header(root)

    def test_stale_header_stops_source_export(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("prepare_source.checked_header", side_effect=ValueError("stale profile")), \
             mock.patch("prepare_source.verify_checkout"), mock.patch("prepare_source.git") as git:
            out = Path(directory) / "new"
            with self.assertRaisesRegex(ValueError, "stale profile"): prepare(out)
            self.assertFalse(out.exists())
            git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
