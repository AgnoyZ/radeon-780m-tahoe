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
from test_bo_retirement import CASES, OWNER_METHODS, CLIENT_METHODS, check_result, exercise, extract_source


class BoRetirementRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_actual_methods_structures_and_hashes(self):
        constants, shared, declarations, maps, methods, hashes = extract_source(self.source)
        expected = {'PhxBringup::' + n for n in OWNER_METHODS} | {'IOAccelPhxNativeClient::' + n for n in CLIENT_METHODS} | {'shape', 'vaCanonical'}
        self.assertEqual(expected, set(hashes))
        for line in (constants + '\n' + shared + '\n' + declarations + '\n' + maps).splitlines():
            self.assertIn(line, self.source)
        for name, digest in hashes.items():
            marker = name + '('
            starts = [self.source.rfind('\n', 0, i) + 1 for i in range(len(self.source)) if self.source.startswith(marker, i)]
            bodies = [self.source[i:self.source.find('\n}\n', i) + 3] for i in starts]
            self.assertTrue(any(body in methods and hashlib.sha256(body.encode()).hexdigest() == digest for body in bodies))

    def test_missing_or_duplicate_actual_source_rejected(self):
        for marker in ('PhxBringup::vmMap(', 'PhxBringup::vmIdleLocked(', 'IOAccelPhxNativeClient::reapPending(',
                       'struct Map {', 'static bool vaCanonical('):
            with self.assertRaises(RuntimeError): extract_source(self.source.replace(marker, 'missing'))
        with self.assertRaises(RuntimeError): extract_source(self.source * 2)

    def test_rejects_false_claims_and_crashes(self):
        good = {'case': 'free-late-completion', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'free-late-completion'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': False}), (0, {**good, 'passed': 1}),
                          (0, {**good, 'case': 'free-repeat'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True}), (0, {**good, 'extra': 1})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'free-late-completion')

    def test_windows_does_not_claim_native_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_bo_retirement.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_all_cases_present_and_ci_enabled(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        harness = (ROOT / 'tests/test_bo_retirement.cpp').read_text(encoding='utf-8')
        for case in CASES: self.assertIn('"' + case + '"', harness)
        self.assertIn('python3 tools/test_bo_retirement.py', (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
