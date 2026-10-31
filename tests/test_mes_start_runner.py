import json
import subprocess
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_mes_start import MARKER, cases, expected_result, check_result


class MesStartRunnerTests(unittest.TestCase):
    def test_all_cases_have_exact_accounting(self):
        names = list(cases())
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            status, counts = expected_result(name)
            self.assertEqual(status == 0, name in ("ok", "poll-delayed", "delay-interrupted"))
            result = subprocess.CompletedProcess([], status, MARKER if not status else "",
                "fake-mes-start-summary " + json.dumps(counts))
            self.assertEqual(counts, check_result(result, name))
        for i in range(1, 10): self.assertIn(f"write-{i}", names)
        for i in range(1, 26): self.assertIn(f"read-{i}", names)

    def test_prerequisites_cannot_reset_or_activate(self):
        for fault in ("snapshot-faulted", "snapshot-adopted", "arg-mapping-mismatch", "bad-15", "vread-bad-4",
                      "mes-active", "mes-all-ones", "selection-busy"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(0, counts["writes"])
            self.assertEqual(0, counts["polls"])

    def test_each_entrypoint_and_selection_readback_gates_activation(self):
        for i in range(18, 25):
            status, counts = expected_result(f"bad-{i}")
            self.assertEqual(75, status)
            self.assertLess(counts["writes"], 9)
            self.assertEqual(0, counts["polls"])

    def test_inactive_wrong_pipe_reset_and_halt_are_bounded(self):
        for fault in ("poll-timeout", "poll-wrong-pipe", "poll-reset-stuck", "poll-halted"):
            status, counts = expected_result(fault)
            self.assertEqual(75, status)
            self.assertEqual(1000, counts["polls"])
            self.assertEqual(1001, counts["sleeps"])
            self.assertEqual(0, counts["closes"])

    def test_validator_rejects_success_on_failed_readback(self):
        status, counts = expected_result("bad-24")
        with self.assertRaises(RuntimeError):
            check_result(subprocess.CompletedProcess([], status, MARKER,
                "fake-mes-start-summary " + json.dumps(counts)), "bad-24")
        status, counts = expected_result("ok")
        with self.assertRaises(RuntimeError):
            check_result(subprocess.CompletedProcess([], status, MARKER,
                "fake-mes-start-summary " + json.dumps({**counts, "writes": 10})), "ok")


if __name__ == "__main__": unittest.main()
