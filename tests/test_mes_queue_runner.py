import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_mes_queue import MARKER, cases, expected_result, check_result, LAYOUT_FAILURES


class MesQueueRunnerTests(unittest.TestCase):
    def test_case_accounting_and_success_boundaries(self):
        names = list(cases())
        self.assertEqual(len(names), len(set(names)))
        for fault in names:
            status, counts = expected_result(fault)
            self.assertEqual(status == 0, fault in ("ok", "delay-eintr"))
            result = subprocess.CompletedProcess([], status, MARKER if not status else "",
                "fake-mes-queue-summary " + json.dumps(counts))
            self.assertEqual(counts, check_result(result, fault))
        self.assertEqual({"lookups": 1, "opens": 1, "hellos": 1, "snapshots": 1, "reads": 44,
            "writes": 31, "vreads": 13, "vwrites": 5962, "bells": 2, "sleeps": 2, "closes": 1}, expected_result("ok")[1])

    def test_layout_and_readiness_fail_before_memory_writes(self):
        for fault in (*LAYOUT_FAILURES, "cp-busy", "mes-inactive", "selection-busy", "hqd-active", "bad-20", "vbad-3", "vbad-7"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(0, counts["vwrites"])
            self.assertEqual(0, counts["bells"])

    def test_hqd_readback_gates_submission(self):
        for i in range(24, 36):
            status, counts = expected_result(f"bad-{i}")
            self.assertEqual(75, status)
            self.assertEqual(5694, counts["vwrites"])
            self.assertEqual(0, counts["bells"])

    def test_first_failure_cannot_submit_second_packet_or_claim_success(self):
        for fault in ("bell-1", "bad-token", "token-high", "timeout", "fence-high", "delay-error"):
            status, counts = expected_result(fault)
            self.assertNotEqual(0, status)
            self.assertEqual(1, counts["bells"])
            self.assertEqual(5828, counts["vwrites"])
            self.assertEqual(0, counts["closes"])
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], status, MARKER,
                    "fake-mes-queue-summary " + json.dumps(counts)), fault)

    def test_timeout_is_bounded_and_keeps_full_width_fence(self):
        for fault in ("timeout", "fence-high"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(400, counts["sleeps"])
            self.assertEqual(409, counts["vreads"])


if __name__ == "__main__": unittest.main()
