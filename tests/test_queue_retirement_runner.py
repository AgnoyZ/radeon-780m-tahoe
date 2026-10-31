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
from test_queue_retirement import CASES, METHODS, check_result, exercise, extract_source


class QueueRetirementRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_actual_methods_and_declarations(self):
        constants, declarations, methods, hashes = extract_source(self.source)
        self.assertEqual(set(METHODS), set(hashes))
        for line in (constants + '\n' + declarations).splitlines(): self.assertIn(line, self.source)
        for name, digest in hashes.items():
            start = self.source.rfind('\n', 0, self.source.index('PhxBringup::' + name + '(')) + 1
            body = self.source[start:self.source.index('\n}\n', start) + 3]
            self.assertIn(body, methods); self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), digest)

    def test_nested_paths_use_locked_helper(self):
        for name in ('vmBind', 'vmIdleLocked', 'reapContextsLocked'):
            start = self.source.index('PhxBringup::' + name + '(')
            body = self.source[start:self.source.index('\n}\n', start)]
            self.assertIn('gpuRetiredLocked()', body)
            self.assertNotIn('gpuRetired()', body)
        start = self.source.index('uint64_t PhxBringup::gpuRetired()')
        body = self.source[start:self.source.index('\n}\n', start)]
        self.assertLess(body.index('IOLockLock'), body.index('gpuRetiredLocked'))
        self.assertLess(body.index('gpuRetiredLocked'), body.index('IOLockUnlock'))

    def test_missing_or_duplicate_actual_source_rejected(self):
        for marker in ('PhxBringup::queueProgress(', 'PhxBringup::gpuRetiredLocked(',
                       'PhxBringup::gpuSubmit(', 'struct GpuQueue {'):
            with self.assertRaises(RuntimeError): extract_source(self.source.replace(marker, 'missing'))
        with self.assertRaises(RuntimeError): extract_source(self.source * 2)

    def test_rejects_false_claims_and_crashes(self):
        good = {'case': 'concurrent-submit-retire', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'concurrent-submit-retire'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': False}), (0, {**good, 'passed': 1}),
                          (0, {**good, 'case': 'submit-first'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True}), (0, {**good, 'extra': 1})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'concurrent-submit-retire')

    def test_windows_refuses_native_claim(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_queue_retirement.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_cases_and_ci_wiring(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        harness = (ROOT / 'tests/test_queue_retirement.cpp').read_text(encoding='utf-8')
        for case in CASES: self.assertIn('"' + case + '"', harness)
        self.assertIn('python3 tools/test_queue_retirement.py', (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
