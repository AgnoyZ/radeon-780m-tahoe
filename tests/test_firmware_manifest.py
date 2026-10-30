import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from firmware_manifest import COMMON, FirmwareError, inspect_firmware, inspect_directory


def fixture(kind="mes"):
    data = bytearray(320)
    major, minor = {"mes": (1, 0), "sdma": (2, 0), "imu": (1, 0), "gfx": (2, 0),
                    "rlc": (2, 3), "psp-toc": (1, 0)}[kind]
    COMMON.pack_into(data, 0, len(data), 256, major, minor, 11, 0, 123, 64, 256, 0)
    fields = {"mes": {36: 32, 40: 256, 48: 32, 52: 288},
              "sdma": {36: 32, 48: 288, 52: 32},
              "imu": {32: 32, 36: 0xBAD, 40: 32, 44: 0xBAD},
              "gfx": {36: 32, 40: 0xBAD, 44: 32, 48: 288},
              "rlc": {20: 32, 132: 32, 136: 288}, "psp-toc": {}}[kind]
    for offset, value in fields.items(): struct.pack_into("<I", data, offset, value)
    data[256:] = bytes(range(64))
    return bytes(data), {"kind": kind, "sha256": hashlib.sha256(data).hexdigest(),
                         "header_version": [major, minor], "ip_version": [11, 0]}


def changed(data, expected, offset, value):
    result = bytearray(data)
    struct.pack_into("<I", result, offset, value)
    return bytes(result), {**expected, "sha256": hashlib.sha256(result).hexdigest()}


class FirmwareManifestTests(unittest.TestCase):
    def test_mes_offsets_and_payload_hashes_are_derived(self):
        data, entry = fixture()
        result = inspect_firmware(data, entry)
        self.assertEqual([256, 288], [r["file_offset"] for r in result["components"]])
        self.assertEqual(hashlib.sha256(data[288:]).hexdigest(), result["components"][1]["sha256"])
        self.assertFalse(result["vendor_signature_verified"])
        self.assertFalse(result["target_compatibility_verified"])

    def test_hash_mismatch_precedes_layout_parsing(self):
        data, entry = fixture()
        with self.assertRaisesRegex(FirmwareError, "source hash"):
            inspect_firmware(b"x" * len(data), entry)
        for invalid in (None, "", "a" * 63, "A" * 64):
            with self.assertRaises(FirmwareError): inspect_firmware(data, {**entry, "sha256": invalid})

    def test_declared_lock_size_cannot_disagree_with_hashed_file(self):
        data, entry = fixture()
        for size in (True, "320", 319, 321):
            with self.assertRaises(FirmwareError): inspect_firmware(data, {**entry, "size_bytes": size})

    def test_total_header_and_payload_bounds(self):
        data, entry = fixture()
        for offset, value in ((0, 321), (4, 31), (4, 400), (4, 32), (20, 0), (20, 65),
                              (20, 0xFFFFFFFF), (24, 252), (24, 257), (24, 0xFFFFFFFC)):
            with self.subTest(offset=offset, value=value), self.assertRaises(FirmwareError):
                inspect_firmware(*changed(data, entry, offset, value))

    def test_unreviewed_header_ip_and_kind_are_rejected(self):
        data, entry = fixture()
        for override in ({"header_version": [2, 0]}, {"ip_version": [12, 0]}, {"kind": "unknown"}):
            with self.assertRaises(FirmwareError): inspect_firmware(data, {**entry, **override})

    def test_engine_layouts_follow_linux_loader_offsets(self):
        for kind in ("mes", "sdma", "imu", "gfx"):
            with self.subTest(kind=kind):
                result = inspect_firmware(*fixture(kind))
                self.assertEqual([256, 288], [r["file_offset"] for r in result["components"]])
                self.assertEqual([32, 32], [r["size_bytes"] for r in result["components"]])
        result = inspect_firmware(*fixture("psp-toc"))
        self.assertEqual("toc", result["components"][0]["component"])

    def test_component_overlap_and_outside_file_are_rejected(self):
        data, entry = fixture()
        for offset, value in ((52, 256), (52, 272), (52, 320), (48, 36), (36, 0), (40, 64)):
            with self.subTest(offset=offset, value=value), self.assertRaises(FirmwareError):
                inspect_firmware(*changed(data, entry, offset, value))

    def test_mec_instruction_excludes_jump_table_in_dword_units(self):
        data, entry = fixture("mes")
        data, entry = changed(data, {**entry, "kind": "gfx-mec"}, 36, 12)
        data, entry = changed(data, entry, 40, 4)
        result = inspect_firmware(data, entry)
        self.assertEqual([("instruction", 256, 48), ("jump_table", 304, 16)],
                         [(r["component"], r["file_offset"], r["size_bytes"]) for r in result["components"]])
        for offset, value in ((36, 0), (36, 17), (40, 0), (40, 17), (40, 0xFFFFFFFF)):
            with self.subTest(offset=offset, value=value), self.assertRaises(FirmwareError):
                inspect_firmware(*changed(data, entry, offset, value))

    def test_pfp_jump_table_is_nested_not_an_extra_load_segment(self):
        data, entry = fixture("mes")
        data, entry = changed(data, {**entry, "kind": "gfx"}, 36, 12)
        data, entry = changed(data, entry, 40, 4)
        result = inspect_firmware(data, entry)
        self.assertEqual(1, len(result["components"]))
        self.assertEqual(64, result["components"][0]["size_bytes"])
        self.assertEqual(16, result["jump_table"]["size_bytes"])

    def test_rlc_optional_segments_are_explicitly_absent(self):
        result = inspect_firmware(*fixture("rlc"))
        self.assertEqual(["ucode", "restore_gpm"], [r["component"] for r in result["components"]])
        self.assertIn("restore_cntl", result["absent_optional_components"])
        self.assertNotIn("restore_gpm", result["absent_optional_components"])

    def test_crc_observation_is_not_authenticated_firmware(self):
        result = inspect_firmware(*fixture())
        self.assertFalse(result["crc32_convention_verified"])
        self.assertNotEqual(result["crc32_reported"], result["crc32_zlib_common_payload"])

    def test_directory_rejects_duplicate_or_escaping_names(self):
        data, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "mes.bin").write_bytes(data)
            valid = {**entry, "name": "mes.bin"}
            for files in ([valid, valid], [{**valid, "name": "../mes.bin"}], [], [None]):
                with self.assertRaises(FirmwareError):
                    inspect_directory(directory, {"schema_version": 1, "files": files})

    def test_local_report_omits_paths_and_never_claims_loading(self):
        data, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "mes.bin").write_bytes(data)
            result = inspect_directory(directory, {"schema_version": 1, "files": [{**entry, "name": "mes.bin"}]})
            self.assertNotIn(directory, json.dumps(result))
            for key in ("hardware_executed", "firmware_loaded", "safe_to_initialize"):
                self.assertFalse(result[key])

    def test_cli_writes_fresh_metadata_and_refuses_overwrite(self):
        data, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mes.bin").write_bytes(data)
            lock = root / "lock.json"
            lock.write_text(json.dumps({"schema_version": 1, "files": [{**entry, "name": "mes.bin"}]}))
            out = root / "private" / "firmware-manifest.json"
            command = [sys.executable, str(ROOT / "tools/firmware_manifest.py"), "--root", str(root),
                       "--lock", str(lock), "--out", str(out)]
            subprocess.run(command, check=True, capture_output=True)
            original = out.read_bytes()
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(1, result.returncode)
            self.assertEqual(original, out.read_bytes())

    def test_cli_failure_does_not_create_success_report(self):
        data, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mes.bin").write_bytes(data[:-1])
            lock = root / "lock.json"
            lock.write_text(json.dumps({"schema_version": 1, "files": [{**entry, "name": "mes.bin"}]}))
            out = root / "new" / "firmware-manifest.json"
            result = subprocess.run([sys.executable, str(ROOT / "tools/firmware_manifest.py"),
                                     "--root", str(root), "--lock", str(lock), "--out", str(out)], capture_output=True)
            self.assertEqual(1, result.returncode)
            self.assertFalse(out.exists())
            self.assertFalse(out.parent.exists())


if __name__ == "__main__":
    unittest.main()
