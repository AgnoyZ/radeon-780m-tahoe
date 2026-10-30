import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_source import prepare
from test_psp_submission import METHODS, CASES, check_result, exercise, extract_methods


class PSPSubmissionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        stage = Path(cls.temp.name) / "source"
        prepare(stage)
        cls.source = (stage / "src/phxbringup/PhxBringup.cpp").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_extracts_actual_methods_and_frame_without_reimplementation(self):
        frame, methods, hashes = extract_methods(self.source)
        self.assertIn(frame.strip(), self.source)
        self.assertEqual(set(METHODS), set(hashes))
        for name in METHODS:
            marker = ("void" if name == "clearRing" else "IOReturn") + " PhxBringup::" + name + "("
            body = marker + self.source.split(marker)[1].split("\n}\n", 1)[0] + "\n}\n"
            self.assertIn(body, methods)
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), hashes[name])

    def test_missing_or_duplicate_method_is_not_silently_skipped(self):
        for source in (self.source.replace("PhxBringup::pspRunCmd(", "PhxBringup::missing("), self.source + self.source):
            with self.assertRaises(RuntimeError): extract_methods(source)

    def test_crash_wrong_case_or_hardware_claim_is_not_a_pass(self):
        good = {"case": "timeout", "passed": True, "hardware_executed": False}
        result = subprocess.CompletedProcess([], 0, json.dumps(good), "")
        self.assertEqual(good, check_result(result, "timeout"))
        for code, data in ((-11, good), (1, good), (0, {**good, "case": "success"}),
                           (0, {**good, "passed": False}), (0, {**good, "passed": 1}),
                           (0, {**good, "hardware_executed": 0}), (0, {**good, "hardware_executed": True})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(data), ""), "timeout")

    def test_non_native_host_does_not_create_test_output(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("test_psp_submission.platform.system", return_value="Windows"):
            out = Path(directory) / "new"
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_ci_runs_completion_staging_and_lifetime_cases(self):
        self.assertEqual(32, len(set(CASES)))
        for case in ("success", "timeout", "psp-error", "tmr-timeout", "stage-overrun",
                     "load-address-overflow", "create-timeout", "destroy-timeout"):
            self.assertIn(case, CASES)
        self.assertIn("python3 tools/test_psp_submission.py", (ROOT / ".github/workflows/build.yml").read_text())


if __name__ == "__main__":
    unittest.main()
