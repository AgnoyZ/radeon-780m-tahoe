import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_source import prepare
from test_queue_adoption import CASES, check_result, exercise, extract_source


class QueueAdoptionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        stage = Path(cls.temp.name) / 'source'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_extracts_actual_method_and_queue_structure(self):
        structure, method, digest = extract_source(self.source)
        self.assertIn(structure, self.source)
        self.assertIn(method, self.source)
        self.assertEqual(hashlib.sha256(method.encode()).hexdigest(), digest)
        self.assertIn('volatile uint32_t head, tail;', structure)

    def test_missing_or_duplicate_source_is_rejected(self):
        for source in (self.source.replace('PhxBringup::adoptQueue(', 'PhxBringup::missing('),
                       self.source.replace('struct GpuQueue {', 'struct Missing {'), self.source * 2):
            with self.assertRaises(RuntimeError): extract_source(source)

    def test_crash_false_or_wrong_report_is_rejected(self):
        good = {'case': 'compute', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'compute'))
        for code, data in ((1, good), (-11, good), (0, {**good, 'passed': 1}),
                           (0, {**good, 'hardware_executed': 0}), (0, {**good, 'case': 'graphics'}),
                           (0, {**good, 'passed': False}), (0, {**good, 'hardware_executed': True})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(data), ''), 'compute')

    def test_windows_does_not_claim_native_pass(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_queue_adoption.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_all_alias_combinations_and_ci_are_present(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        for kind in ('psp', 'peer'):
            for i in range(3):
                for j in range(3): self.assertIn(f'{kind}-{i}-{j}', CASES)
        self.assertIn('python3 tools/test_queue_adoption.py', (ROOT / '.github/workflows/build.yml').read_text())


if __name__ == '__main__':
    unittest.main()
