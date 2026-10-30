import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_firmware_control import cases, check_result, expected_result, exercise, compile_native_control


def result(status, counts, stdout=""):
    return subprocess.CompletedProcess([], status, stdout,
        "phxctl checked failure: injected\nfake-control-summary " + json.dumps(counts))


class FirmwareControlRunnerTests(unittest.TestCase):
    def test_suite_covers_snapshot_mutation_and_failed_prerequisites(self):
        actual = list(cases())
        self.assertEqual(60, len(set(actual)))
        for fault in ("mutate-file", "read-short", "read-error", "read-eintr", "hello-short", "hello-long",
                      "stage-first", "stage-second", "load-short", "load-long", "psp-timeout"):
            self.assertIn(("load", fault), actual)
        self.assertIn(("verify", "hash-mismatch"), actual)
        self.assertIn(("layout", "layout-status"), actual)
        self.assertIn(("toc", "toc-no-fit"), actual)

    def test_stage_failure_cannot_load_or_continue_transferring(self):
        status, counts = expected_result("load", "stage-second")
        self.assertEqual(74, status)
        self.assertEqual(4096, counts["accepted_bytes"])
        self.assertEqual(counts, check_result(result(status, counts), "load", "stage-second"))
        for changed in ({**counts, "loads": 1}, {**counts, "stages": 3}, {**counts, "accepted_bytes": 8209},
                        {**counts, "loads": False}):
            with self.assertRaises(RuntimeError): check_result(result(status, changed), "load", "stage-second")

    def test_incomplete_snapshot_cannot_hash_stage_or_report_success(self):
        status, counts = expected_result("load", "read-short")
        self.assertEqual(65, status)
        for changed in ({**counts, "hashes": 1}, {**counts, "stages": 1}):
            with self.assertRaises(RuntimeError): check_result(result(status, changed), "load", "read-short")
        for invalid in (result(0, counts), result(-11, counts), result(status, counts, "loadfw successful")):
            with self.assertRaises(RuntimeError): check_result(invalid, "load", "read-short")

    def test_verify_only_cannot_open_iokit(self):
        status, counts = expected_result("verify", "ok")
        self.assertEqual(counts, check_result(result(status, counts, "verified firmware snapshot"), "verify", "ok"))
        with self.assertRaises(RuntimeError):
            check_result(result(status, {**counts, "opens": 1}), "verify", "ok")

    def test_non_native_host_does_not_create_outputs(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("test_firmware_control.platform.system", return_value="Windows"):
            out = Path(directory) / "new"
            with self.assertRaises(RuntimeError): exercise(out)
            with self.assertRaises(RuntimeError): compile_native_control(Path(directory), out)
            self.assertFalse(out.exists())

    def test_standalone_compile_failure_stops_before_harness_build(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("test_firmware_control.platform.system", return_value="Linux"), \
             mock.patch("test_firmware_control.shutil.which", return_value="clang"), \
             mock.patch("test_firmware_control.prepare", return_value={}), \
             mock.patch("test_firmware_control.subprocess.run", side_effect=subprocess.CalledProcessError(1, "clang")) as run:
            out = Path(directory) / "new"
            with self.assertRaises(subprocess.CalledProcessError):
                exercise(out)
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertIn("-std=c11", command)
            self.assertIn("-Werror", command)
            self.assertIn("-fsyntax-only", command)
            self.assertEqual(str(out.resolve() / "stage/tools/phxctl/phxctl.c"), command[-1])
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
