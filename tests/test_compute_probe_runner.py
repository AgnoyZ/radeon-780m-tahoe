import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_compute_probe import MARKER, cases, expected_result, check_result, WORK_LAYOUT_FAILURES


class ComputeProbeRunnerTests(unittest.TestCase):
    def test_cases_have_exact_terminal_accounting(self):
        names = list(cases())
        self.assertEqual(len(names), len(set(names)))
        for fault in names:
            status, counts = expected_result(fault)
            self.assertEqual(status == 0, fault in ("ok", "work-adjacent", "delay-eintr", "work-eintr", "work-delayed"))
            self.assertEqual(counts, check_result(subprocess.CompletedProcess([], status, MARKER if not status else "",
                "fake-mes-queue-summary " + json.dumps(counts)), fault))
        self.assertEqual({"lookups": 1, "opens": 1, "hellos": 1, "snapshots": 1, "reads": 65, "writes": 37,
            "vreads": 26, "vwrites": 11781, "bells": 3, "sleeps": 4, "closes": 1, "work_bells": 1}, expected_result("ok")[1])

    def test_layout_and_preexisting_compute_queue_fail_before_memory_mutation(self):
        for fault in (*WORK_LAYOUT_FAILURES, "work-hqd-active", "work-hqd-all-ones", "vbad-12", "bad-23"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(0, counts["vwrites"])
            self.assertEqual(0, counts["bells"])
            self.assertEqual(0, counts["work_bells"])

    def test_add_queue_failure_and_hqd_mismatch_cannot_ring_compute(self):
        for fault in ("bell-3", "add-timeout", "add-bad-token", "bad-53", "bad-65"):
            status, counts = expected_result(fault)
            self.assertNotEqual(0, status)
            self.assertEqual(3, counts["bells"])
            self.assertEqual(0, counts["work_bells"])
            self.assertEqual(0, counts["closes"])

    def test_full_width_release_fence_is_bounded(self):
        for fault in ("work-timeout", "work-fence-low", "work-fence-high"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(403, counts["sleeps"])
            self.assertEqual(421, counts["vreads"])
            self.assertEqual(1, counts["work_bells"])

    def test_result_guards_and_close_failure_never_claim_success(self):
        for fault in ("work-fence-changed", "work-missing-data", "work-data-high", "work-guard-before", "work-guard-after", "close-status"):
            status, counts = expected_result(fault)
            self.assertNotEqual(0, status)
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], status, MARKER,
                    "fake-mes-queue-summary " + json.dumps(counts)), fault)


if __name__ == "__main__": unittest.main()
