from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_radv import runtime_destination, runtime_metadata_destination, icd_library_path, write_runtime_metadata


class RuntimeLayoutTests(unittest.TestCase):
    def test_standalone_layout_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(root / "nvmtl", runtime_destination(root, False))
            (root / "nvmtl").mkdir()
            with self.assertRaises(RuntimeError):
                runtime_destination(root, False)

    def test_bundle_layout_requires_actual_plugin_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(RuntimeError):
                runtime_destination(root, True)
            target = root / "NVMTLDriver.bundle/Contents/MacOS"
            target.mkdir(parents=True)
            (target / "NVMTLDriver").write_bytes(b"layout fixture, not a binary")
            self.assertEqual(target, runtime_destination(root, True))
            for name in ("libvulkan_radeon.dylib", "radeon_icd.json", "radv-build-report.json"):
                with self.subTest(name=name):
                    path = target / name
                    path.write_bytes(b"existing")
                    with self.assertRaises(RuntimeError):
                        runtime_destination(root, True)
                    path.unlink()

    def test_bundle_json_is_resource_data_with_a_correct_relative_library(self):
        root = Path("artifacts")
        self.assertEqual(root / "NVMTLDriver.bundle/Contents/Resources", runtime_metadata_destination(root, True))
        self.assertEqual("../MacOS/libvulkan_radeon.dylib", icd_library_path(True))
        self.assertEqual(root / "nvmtl", runtime_metadata_destination(root, False))
        self.assertEqual("./libvulkan_radeon.dylib", icd_library_path(False))

    def test_bundle_does_not_overwrite_resource_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "NVMTLDriver.bundle/Contents/MacOS"
            target.mkdir(parents=True)
            (target / "NVMTLDriver").write_bytes(b"layout fixture, not a binary")
            resources = runtime_metadata_destination(root, True)
            resources.mkdir()
            for name in ("radeon_icd.json", "radv-build-report.json"):
                path = resources / name
                path.write_bytes(b"existing resource")
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    runtime_destination(root, True)
                path.unlink()

    def test_metadata_writer_preserves_api_and_resolves_staged_library(self):
        for bundled in (True, False):
            with self.subTest(bundled=bundled), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                code = root / ("NVMTLDriver.bundle/Contents/MacOS" if bundled else "nvmtl")
                code.mkdir(parents=True)
                library = code / "libvulkan_radeon.dylib"
                library.write_bytes(b"path fixture only")
                manifest = {"file_format_version": "1.0.0", "ICD": {"api_version": "1.4.0", "library_path": "build-only"}}
                report = {"hardware_executed": False}
                write_runtime_metadata(root, bundled, manifest, report)
                resources = runtime_metadata_destination(root, bundled)
                actual = json.loads((resources / "radeon_icd.json").read_text())
                self.assertEqual(library.resolve(), (resources / actual["ICD"]["library_path"]).resolve())
                self.assertEqual("1.4.0", actual["ICD"]["api_version"])
                self.assertEqual("build-only", manifest["ICD"]["library_path"])
                self.assertEqual(report, json.loads((resources / "radv-build-report.json").read_text()))
                if bundled:
                    self.assertEqual([], list(code.glob("*.json")))
                with self.assertRaises(RuntimeError):
                    write_runtime_metadata(root, bundled, manifest, {"overwrite": True})
                self.assertEqual(report, json.loads((resources / "radv-build-report.json").read_text()))


if __name__ == "__main__":
    unittest.main()
