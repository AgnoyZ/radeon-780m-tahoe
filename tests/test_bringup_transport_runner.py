from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_bringup_transport import cases, check_case, exercise, compile_native


class TransportRunnerTests(unittest.TestCase):
    def test_failures_cannot_return_zero_or_continue_writes(self):
        valid = subprocess.CompletedProcess([], 74, "", "fake-transport call=1 selector=2\nmesboot transport: stopping\n")
        check_case(valid, 74, 1)
        for invalid in (subprocess.CompletedProcess([], 0, "", valid.stderr),
                        subprocess.CompletedProcess([], -11, "", valid.stderr),
                        subprocess.CompletedProcess([], 74, "transport-returned", valid.stderr),
                        subprocess.CompletedProcess([], 74, "", valid.stderr + "fake-transport call=2 selector=108\n"),
                        subprocess.CompletedProcess([], 74, "", "fake-transport call=1 selector=2\n")):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                check_case(invalid, 74, 1)

    def test_cases_include_both_length_directions_and_valid_zero_data(self):
        actual = list(cases())
        self.assertEqual(47, len(actual))
        self.assertEqual(len(actual), len({(op, mode) for op, mode, _, _ in actual}))
        for op in ("rd", "vr", "wr", "sm", "read-then-write", "vram-read-then-write"):
            self.assertIn((op, "short", 74, 1), actual)
            self.assertIn((op, "long", 74, 1), actual)
            self.assertIn((op, "zero", 0, 2 if "-then-" in op else 1), actual)

    def test_host_rejection_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch("test_bringup_transport.platform.system", return_value="Windows"):
            out = Path(temporary) / "new"
            for function in (exercise, compile_native):
                with self.assertRaises(RuntimeError):
                    function(out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
