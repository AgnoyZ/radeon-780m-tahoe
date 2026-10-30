from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_bringup_transport import cases, check_case, exercise, compile_native, completion_cases, check_completion_case
from test_bringup_transport import submission_cases, check_submission_case


class TransportRunnerTests(unittest.TestCase):
    def test_submission_rejection_has_no_transport_or_state_changes(self):
        data = {"calls": 0, "ring_writes": 0, "wptr": 897, "seq": 0}
        def result(summary, status=76):
            return subprocess.CompletedProcess([], status, "", "mesboot submission: rejected\nfake-submission-summary " + json.dumps(summary))
        self.assertEqual(data, check_submission_case(result(data), "ring-one-over"))
        for changed in ({**data, "calls": 1}, {**data, "ring_writes": 1}, {**data, "seq": 1},
                        {**data, "wptr": 0}, {**data, "calls": False}):
            with self.assertRaises(RuntimeError): check_submission_case(result(changed), "ring-one-over")
        for status in (0, -11, 75):
            with self.assertRaises(RuntimeError): check_submission_case(result(data, status), "ring-one-over")

    def test_submission_suite_keeps_positive_boundaries_and_exhaustion(self):
        cases = submission_cases()
        self.assertEqual(16, len(set(cases)))
        for name in ("last-frame", "last-sequence", "unaligned", "ring-high-word", "sequence-exhausted"):
            self.assertIn(name, cases)
        for fault, wptr, seq in (("last-frame", 1024, 1), ("last-sequence", 128, (1 << 64) - 1)):
            data = {"calls": 142, "ring_writes": 128, "wptr": wptr, "seq": seq}
            result = subprocess.CompletedProcess([], 0, "submission-returned", "fake-submission-summary " + json.dumps(data))
            self.assertEqual(data, check_submission_case(result, fault))

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
        self.assertEqual(52, len(actual))
        self.assertEqual(len(actual), len({(op, mode) for op, mode, _, _ in actual}))
        for op in ("rd", "vr", "vr64", "wr", "sm", "read-then-write", "vram-read-then-write"):
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

    def test_completion_cases_cover_each_adoption_prerequisite(self):
        actual = list(completion_cases())
        self.assertEqual(20, len(actual))
        for operation in ("mes", "sched", "compute", "gfx"):
            self.assertIn((operation, "ok"), actual)
            self.assertIn((operation, "timeout"), actual)
        for operation in ("compute", "gfx"):
            self.assertIn((operation, "wrong-scratch"), actual)
            self.assertIn((operation, "wrong-memory"), actual)
        for operation in ("mes", "sched"):
            self.assertIn((operation, "wrong-fence-high"), actual)
            self.assertIn((operation, "wrong-token-high"), actual)

    def test_completion_failure_cannot_adopt_write_continue_or_skip_polling(self):
        data = {"scheduler_bells": 1, "work_bells": 1, "adoptions": 0, "writes_after_failure": 0, "sleeps": 51}
        def result(summary, code=75, stdout="", diagnostic="mesboot GPU: compute execution not confirmed\n"):
            return subprocess.CompletedProcess([], code, stdout, diagnostic + "fake-gpu-summary " + json.dumps(summary))
        self.assertEqual(data, check_completion_case(result(data), "compute", "timeout"))
        for changed in ({**data, "adoptions": 1}, {**data, "writes_after_failure": 1},
                        {**data, "sleeps": 0}, {**data, "work_bells": 0}, {**data, "work_bells": True}):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                check_completion_case(result(changed), "compute", "timeout")
        for invalid in (result(data, code=0), result(data, code=-11), result(data, stdout="gpu-returned"),
                        result(data, diagnostic="")):
            with self.assertRaises(RuntimeError):
                check_completion_case(invalid, "compute", "timeout")


if __name__ == "__main__":
    unittest.main()
