import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_firmware_sequence import cases, check_result, expected_result, exercise, write_fixtures
from firmware_profile import load_profile


def result(status, counts, stdout=""):
    return subprocess.CompletedProcess([], status, stdout,
        "phxctl checked failure: injected\nfake-sequence-summary " + json.dumps(counts))


class FirmwareSequenceRunnerTests(unittest.TestCase):
    def test_all_components_and_file_verification_faults_are_covered(self):
        actual = list(cases())
        self.assertEqual(len(actual), len(set(actual)))
        for i in range(18): self.assertIn(f"stage-{i}", actual)
        for i in range(1, 18): self.assertIn(f"load-{i}", actual)
        for i in range(9): self.assertIn(f"hash-{i}", actual)
        for name in actual:
            code, counts = expected_result(name)
            self.assertEqual(code == 0, name in ("ok", "mutate-files"))
            if code: self.assertEqual(counts, check_result(result(code, counts), name))

    def test_all_files_before_lookup_and_exact_order(self):
        code, counts = expected_result("ok")
        self.assertEqual(0, code)
        self.assertEqual([f"hash-{i}" for i in range(9)] + ["lookup", "open", "hello", "layout", "ring", "stage-0", "toc", "tmr"],
                         counts["events"][:17])
        self.assertEqual(["stage-17", "load-17", "autoload", "close"], counts["events"][-4:])
        self.assertEqual(sum(s["size_bytes"] for s in load_profile()["steps"]), counts["accepted_bytes"])

    def test_fault_cannot_continue_to_next_component_or_success(self):
        for fault in ("hash-8", "stage-7", "load-17", "toc-capacity", "tmr-alignment", "close-status"):
            code, counts = expected_result(fault)
            for changed in ({**counts, "events": counts["events"] + ["autoload"]},
                            {**counts, "stages": counts["stages"] + 1},
                            {**counts, "accepted_bytes": counts["accepted_bytes"] + 4}):
                with self.assertRaises(RuntimeError): check_result(result(code, changed), fault)
            with self.assertRaises(RuntimeError): check_result(result(code, counts, "firmware-sequence complete"), fault)
            with self.assertRaises(RuntimeError): check_result(result(-11, counts), fault)

    def test_fixture_generation_is_synthetic_and_indexed(self):
        data = {"files": [{"name": "a.bin", "size_bytes": 500}, {"name": "b.bin", "size_bytes": 300}]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "fixtures"
            write_fixtures(out, data, "ok")
            self.assertEqual(bytes(i % 251 for i in range(500)), (out / "a.bin").read_bytes())
            self.assertEqual(bytes((i + 1) % 251 for i in range(300)), (out / "b.bin").read_bytes())

    def test_unsupported_platform_does_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("test_firmware_sequence.platform.system", return_value="Windows"):
            out = Path(directory) / "new"
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_independent_compile_failure_stops_before_harness(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("test_firmware_sequence.platform.system", return_value="Linux"), \
             mock.patch("test_firmware_sequence.shutil.which", return_value="clang"), \
             mock.patch("test_firmware_sequence.prepare", return_value={}), \
             mock.patch("test_firmware_sequence.subprocess.run", side_effect=subprocess.CalledProcessError(1, "clang")) as run:
            with self.assertRaises(subprocess.CalledProcessError): exercise(Path(directory) / "new")
            run.assert_called_once()
            self.assertIn("-fsyntax-only", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
