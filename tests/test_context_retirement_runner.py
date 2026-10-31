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
from test_context_retirement import CASES, OWNER_METHODS, CLIENT_METHODS, check_result, exercise, extract_source


class ContextRetirementRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_actual_methods_structures_and_hashes(self):
        constants, shared, declarations, methods, hashes = extract_source(self.source)
        expected = {'PhxBringup::' + n for n in OWNER_METHODS} | {'IOAccelPhxNativeClient::' + n for n in CLIENT_METHODS} | {'shape', 'phxReleaseBuffers'}
        self.assertEqual(expected, set(hashes))
        for line in (constants + '\n' + shared + '\n' + declarations).splitlines(): self.assertIn(line, self.source)
        for name, digest in hashes.items():
            marker = name + '('
            starts = [self.source.rfind('\n', 0, i) + 1 for i in range(len(self.source)) if self.source.startswith(marker, i)]
            bodies = [self.source[i:self.source.find('\n}\n', i) + 3] for i in starts]
            self.assertTrue(any(body in methods and hashlib.sha256(body.encode()).hexdigest() == digest for body in bodies))

    def test_ownership_declarations_follow_includes_and_precede_service(self):
        self.assertLess(self.source.index('#include "PhxNativeABI.h"'), self.source.index('\nstruct PhxClientBo {'))
        self.assertLess(self.source.index('\nstruct PhxRetiredBuffers {'), self.source.index('\nclass PhxBringup :'))
        self.assertNotIn('void PhxBringup::vmidFree(', self.source)
        close = self.source.split('void IOAccelPhxNativeClient::closeResources() {')[1].split('\n}\n')[0]
        self.assertLess(close.index('owner->deferClient'), close.index('bufferStorage = nullptr'))
        stop = self.source.split('void PhxBringup::stop(IOService *provider) {')[1].split('\n}\n')[0]
        self.assertLess(stop.index('stopQuarantined'), stop.index('clearRing()'))

    def test_missing_or_duplicate_source_rejected(self):
        for marker in ('PhxBringup::deferClient(', 'IOAccelPhxNativeClient::closeResources(', 'struct PhxRetiredBuffers {', 'static void phxReleaseBuffers('):
            with self.assertRaises(RuntimeError): extract_source(self.source.replace(marker, 'missing'))
        with self.assertRaises(RuntimeError): extract_source(self.source * 2)

    def test_rejects_false_claims_and_crashes(self):
        good = {'case': 'late-completion', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'late-completion'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': False}), (0, {**good, 'passed': 1}),
                          (0, {**good, 'case': 'defer-pending'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True})):
            with self.assertRaises(RuntimeError): check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'late-completion')

    def test_windows_does_not_claim_native_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_context_retirement.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_ci_and_lifetime_scenarios(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        for case in ('late-completion', 'ack-retry', 'faulted-peer-recovered', 'host-pins-preserved',
                     'client-close-then-free', 'close-during-wait', 'stop-repeat', 'alloc-reclaims'):
            self.assertIn(case, CASES)
        self.assertIn('python3 tools/test_context_retirement.py', (ROOT / '.github/workflows/build.yml').read_text())


if __name__ == '__main__': unittest.main()
