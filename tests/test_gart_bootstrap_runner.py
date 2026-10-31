import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_gart_bootstrap import cases, expected_result, check_result, exercise


def result(status, counts):
    marker = "gart complete: 5 pages, address readbacks and invalidation acknowledged; GPU execution unverified"
    return subprocess.CompletedProcess([], status, marker if not status else "",
        "mesboot GART: injected\nfake-gart-summary " + json.dumps(counts))


class GartBootstrapRunnerTests(unittest.TestCase):
    def test_all_cases_have_terminal_accounting(self):
        names = list(cases())
        self.assertEqual(len(names), len(set(names)))
        for fault in names:
            status, counts = expected_result(fault)
            self.assertEqual(status == 0, fault in ("ok", "relocated", "env-zero", "ack-delayed", "sleep-eintr"))
            self.assertEqual(counts, check_result(result(status, counts), fault))
        for i in range(1, 189): self.assertIn(f"reg-write-{i}", names)

    def test_preconditions_cannot_write_memory(self):
        for fault in ("snapshot-gpu", "snapshot-faulted", "table-ring", "default-stage", "context-eight-active", "rlc-all-ones"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(0, counts["vram_writes"])
            self.assertEqual(0, counts["reg_writes"])
            with self.assertRaises(RuntimeError): check_result(result(status, {**counts, "vram_writes": 1}), fault)

    def test_table_failure_cannot_enable_gart(self):
        for fault in ("vram-write-2048", "vram-bad-1", "vram-bad-4", "vram-read-3"):
            status, counts = expected_result(fault)
            self.assertGreater(status, 0)
            self.assertEqual(0, counts["reg_writes"])
            self.assertEqual(0, counts["ack_reads"])
            self.assertEqual(0, counts["closes"])

    def test_readback_failure_precedes_invalidation(self):
        for i in range(20, 33):
            status, counts = expected_result(f"register-bad-{i}")
            self.assertEqual(75, status)
            self.assertEqual(187, counts["reg_writes"])
            self.assertEqual(0, counts["ack_reads"])

    def test_invalidation_requires_correct_bit_and_bounded_polls(self):
        for fault in ("ack-timeout", "ack-wrong-bit"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(1000, counts["ack_reads"])
            self.assertEqual(1000, counts["sleeps"])
            self.assertEqual(0, counts["closes"])
        _, counts = expected_result("ok")
        self.assertEqual(188, counts["reg_writes"])
        self.assertEqual(2048, counts["accepted_words"])
        self.assertEqual(33, counts["reg_reads"])

    def test_runner_refuses_wrong_platform_before_staging(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("test_gart_bootstrap.platform.system", return_value="Windows"):
            out = Path(directory) / "new"
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
