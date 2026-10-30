from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_radv import runtime_destination


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


if __name__ == "__main__":
    unittest.main()
