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
from test_bo_retirement import extract_source
from test_ib_debug import CASES, check_regression, check_result, exercise, expected_result, write_extracted


class IbDebugRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.stage = Path(cls.temporary.name) / 'stage'
        prepare(cls.stage)
        cls.source = (cls.stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def test_actual_source_and_reverse_patch_match_previous_audited_method(self):
        current = extract_source(self.source)[-1]['IOAccelPhxNativeClient::doSubmit']
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cpp = directory / 'src/phxbringup/PhxBringup.cpp'
            cpp.parent.mkdir(parents=True)
            cpp.write_text(self.source, encoding='utf-8', newline='\n')
            subprocess.run(['git', 'init', '-q', str(directory)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(directory), 'apply', '-R',
                str(ROOT / 'patches/0027-bounded-ib-debug-reads.patch')], check=True, capture_output=True)
            old = extract_source(cpp.read_text(encoding='utf-8'))[-1]['IOAccelPhxNativeClient::doSubmit']
            previous_evidence = json.loads((ROOT / 'docs/validation/ci-4d71c0c-native-shader.json').read_text(encoding='utf-8'))
            self.assertEqual(previous_evidence['actual_bo_method_sha256']['IOAccelPhxNativeClient::doSubmit'], old)
            self.assertNotEqual(old, current)
            extracted = directory / 'extracted'
            self.assertEqual(extract_source(self.source)[-1], write_extracted(extracted, self.source))
            body = (extracted / 'bo-methods.inc').read_text(encoding='utf-8')
            self.assertIn('const Map &mp = maps[m];', body)
            self.assertIn('if (cnt > available / 4)', body)
            self.assertIn('offset > UINTPTR_MAX - base', body)
            self.assertIn('address & 3', body)
            self.assertIn('bo->md->getLength()', body)

    def test_exact_scenario_counts_and_boolean_types(self):
        self.assertEqual(56, len(CASES))
        self.assertEqual(len(CASES), len(set(CASES)))
        for variant in ('low', 'upper'):
            for case in CASES:
                row = expected_result(case, variant)
                self.assertEqual(row, check_result(subprocess.CompletedProcess([], 0, json.dumps(row), ''), case, variant))
        self.assertEqual(64, expected_result('multi-max', 'low')['log_rows'])
        self.assertEqual(2, expected_result('cross-97', 'upper')['log_rows'])
        self.assertEqual(1, expected_result('cross-1', 'low')['prefix_words'])
        self.assertEqual(1, expected_result('missing-md', 'low')['submissions'])
        with self.assertRaises(ValueError): expected_result('missing', 'low')
        with self.assertRaises(ValueError): expected_result('cross-1', 'missing')

    def test_rejects_crashes_false_counts_types_and_hardware_claims(self):
        row = expected_result('cross-1', 'low')
        for code, value in ((1, row), (-11, row), (0, {**row, 'log_rows': 3}), (0, {**row, 'prefix_words': True}),
            (0, {**row, 'hardware_executed': True}), (0, {**row, 'passed': 1}), (0, {**row, 'extra': 1})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(value), ''), 'cross-1', 'low')

    def test_previous_failure_requires_actual_sanitizer_diagnosis_and_stays_private(self):
        report = check_regression(subprocess.CompletedProcess([], 1, '', 'PRIVATE AddressSanitizer: heap-buffer-overflow PRIVATE'))
        self.assertTrue(report['actual_previous_method_executed'])
        self.assertFalse(report['raw_sanitizer_output_logged'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        for code, stdout, stderr in ((0, '', 'AddressSanitizer: heap-buffer-overflow'), (-11, '', ''),
            (1, '', 'assertion failed'), (1, 'false success', 'AddressSanitizer: heap-buffer-overflow')):
            with self.assertRaises(RuntimeError): check_regression(subprocess.CompletedProcess([], code, stdout, stderr))

    def test_windows_cannot_claim_cpp_or_hardware_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_ib_debug.platform.system', return_value='Windows'):
            output = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(output)
            self.assertFalse(output.exists())

    def test_ci_uses_real_method_harness_and_only_suppresses_unused_fixture_helpers(self):
        workflow = (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8')
        self.assertIn('python3 tools/test_ib_debug.py', workflow)
        source = (ROOT / 'tools/test_ib_debug.py').read_text(encoding='utf-8')
        for flag in ('-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-sanitize-recover=all'):
            self.assertIn(flag, source)
        self.assertNotIn('-Wno-error', source)
        self.assertIn('#include "test_bo_retirement.cpp"', (ROOT / 'tests/test_ib_debug.cpp').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
