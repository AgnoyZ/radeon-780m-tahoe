import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_firmware_sequence import power_cases, expected_result, check_result


def report(status, counts, success=False):
    stdout = ("gfx-power-sequence complete: PMFW 0x13004001, IMU acknowledged and GFX boot readiness observed; "
              "queues/shaders/display unverified") if success else ""
    return subprocess.CompletedProcess([], status, stdout,
        "phxctl checked failure: injected\nfake-sequence-summary " + json.dumps(counts))


class GfxPowerRunnerTests(unittest.TestCase):
    def test_case_inventory_and_result_contract(self):
        all_cases = list(power_cases())
        self.assertEqual(157, len(all_cases))
        self.assertEqual(len(all_cases), len(set(all_cases)))
        for case in all_cases:
            with self.subTest(case=case):
                status, counts = expected_result(case, power=True)
                self.assertEqual(status == 0, case in ("ok", "mutate-files", "ready-delayed", "sleep-eintr"))
                self.assertEqual(counts, check_result(report(status, counts, status == 0), case, power=True))

    def test_interface_queries_precede_layout_and_power_follows_autoload(self):
        _, counts = expected_result("ok", power=True)
        events = counts["events"]
        self.assertEqual(["hello", "smu-if", "smu-version", "layout"], events[11:15])
        self.assertEqual(["load-17", "autoload", "smu-enable", "readiness", "close"], events[-5:])
        self.assertEqual(3, counts["smus"])
        self.assertEqual((1, 1, 3, 0), tuple(counts[k] for k in ("cp_reads", "rlc_reads", "clocks", "sleeps")))

    def test_firmware_failure_never_requests_power(self):
        for fault in ("hash-8", "load-17", "autoload-psp", "smu-if-mismatch"):
            status, counts = expected_result(fault, power=True)
            self.assertNotEqual(0, status)
            self.assertNotIn("smu-enable", counts["events"])
            self.assertEqual(0, counts["clocks"])
            self.assertEqual(0, counts["cp_reads"])
        _, counts = expected_result("smu-if-mismatch", power=True)
        self.assertEqual(0, counts["stages"])
        self.assertNotIn("layout", counts["events"])

    def test_late_or_busy_registers_cannot_be_success(self):
        for fault in ("clock-after-deadline", "cp-busy", "rlc-not-ready", "rlc-wrong-bit", "read-all-ones"):
            status, counts = expected_result(fault, power=True)
            self.assertEqual(75, status)
            self.assertNotIn("close", counts["events"])
            self.assertGreater(counts["rlc_reads"], 0)
            with self.assertRaises(RuntimeError): check_result(report(status, counts, True), fault, power=True)

    def test_frozen_time_has_independent_sample_limit(self):
        status, counts = expected_result("clock-frozen", power=True)
        self.assertEqual(75, status)
        self.assertEqual(2000, counts["cp_reads"])
        self.assertEqual(2000, counts["rlc_reads"])
        self.assertEqual(4001, counts["clocks"])
        self.assertNotIn("close", counts["events"])

    def test_malformed_first_register_read_cannot_read_second(self):
        for suffix in ("status", "short", "long"):
            fault = "read-cp-" + suffix
            status, counts = expected_result(fault, power=True)
            self.assertEqual((74, 1, 0, 2), (status, counts["cp_reads"], counts["rlc_reads"], counts["clocks"]))
            with self.assertRaises(RuntimeError):
                check_result(report(status, {**counts, "rlc_reads": 1}), fault, power=True)

    def test_interrupts_allow_a_new_bounded_observation(self):
        status, counts = expected_result("sleep-eintr", power=True)
        self.assertEqual(0, status)
        self.assertEqual(3, counts["rlc_reads"])
        self.assertEqual(2, counts["sleeps"])
        self.assertEqual(7, counts["clocks"])
        for key in ("smus", "clocks", "sleeps", "cp_reads", "rlc_reads"):
            with self.assertRaises(RuntimeError):
                check_result(report(status, {**counts, key: counts[key] + 1}, True), "sleep-eintr", power=True)


if __name__ == "__main__":
    unittest.main()
