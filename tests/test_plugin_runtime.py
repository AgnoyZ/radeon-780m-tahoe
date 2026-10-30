import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from plugin_runtime import check_probe, clean_environment, copy_bundle


class PluginRuntimeTests(unittest.TestCase):
    def test_environment_removes_inherited_driver_and_loader_overrides(self):
        env = clean_environment({"PATH": "tools", "NVMTL_ENABLE": "1", "VK_ICD_FILENAMES": "fake",
                                 "DYLD_INSERT_LIBRARIES": "fake", "RADV_DARWIN_MOCK": "1", "NAK_DEBUG": "1"})
        self.assertEqual({"PATH": "tools"}, env)

    def test_positive_requires_actual_load_and_no_commands(self):
        data = {"plugin_loaded": True, "plugin_compiler_executed": True, "bundled_runtimes_loaded": True,
                "gpu_commands_begun": 0, "gpu_commands_submitted": 0, "gpu_commands_abandoned": 0}
        self.assertEqual(data, check_probe(subprocess.CompletedProcess([], 0, json.dumps(data), "")))
        for key in data:
            bad = {**data, key: not data[key] if isinstance(data[key], bool) else 1}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                check_probe(subprocess.CompletedProcess([], 0, json.dumps(bad), ""))
        with self.assertRaises(RuntimeError):
            check_probe(subprocess.CompletedProcess([], 0, json.dumps({**data, "gpu_commands_begun": False}), ""))

    def test_negative_is_not_a_crash_or_missing_plugin_pass(self):
        self.assertIsNone(check_probe(subprocess.CompletedProcess([], 20, "", "Plugin library index failed"), negative=True))
        for code in (0, 5, 77, -11):
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                check_probe(subprocess.CompletedProcess([], code, "", "Plugin library index failed"), negative=True)
        with self.assertRaises(RuntimeError):
            check_probe(subprocess.CompletedProcess([], 20, "", "different error"), negative=True)

    def test_copy_omits_one_runtime_without_changing_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bundle"
            for name in ("NVMTLDriver", "libnvmtl_translate.dylib", "air-runtime/libLLVM.dylib"):
                path = source / "Contents/MacOS" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic copy fixture, not a binary")
            copy_bundle(source, root / "copy.bundle", omit="libnvmtl_translate.dylib")
            self.assertTrue((source / "Contents/MacOS/libnvmtl_translate.dylib").is_file())
            self.assertFalse((root / "copy.bundle/Contents/MacOS/libnvmtl_translate.dylib").exists())
            self.assertTrue((root / "copy.bundle/Contents/MacOS/air-runtime/libLLVM.dylib").is_file())
            with self.assertRaises(FileExistsError):
                copy_bundle(source, root / "copy.bundle")


if __name__ == "__main__":
    unittest.main()
