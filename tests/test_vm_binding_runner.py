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
from test_vm_binding import CASES, METHODS, check_result, exercise, extract_source


class VMBindingRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_extracts_actual_methods_constants_and_structures(self):
        constants, declarations, methods, hashes = extract_source(self.source)
        self.assertEqual(set(METHODS), set(hashes))
        for name in METHODS:
            marker = next(x for x in ('bool', 'uint32_t', 'void', 'IOReturn') if x + ' PhxBringup::' + name + '(' in self.source)
            start = self.source.index(marker + ' PhxBringup::' + name + '(')
            body = self.source[start:self.source.index('\n}\n', start) + 3]
            self.assertIn(body, methods); self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), hashes[name])
        for line in (constants + '\n' + declarations).splitlines(): self.assertIn(line, self.source)
        self.assertLess(declarations.index('kPtChunkBytes'), declarations.index('struct VmCtx'))

    def test_missing_or_duplicate_methods_and_structures_rejected(self):
        for original in ('PhxBringup::vmBind(', 'PhxBringup::gpuSubmit(', 'struct VmCtx {', 'kRegInvEng17Req ='):
            with self.assertRaises(RuntimeError): extract_source(self.source.replace(original, 'missing'))
        with self.assertRaises(RuntimeError): extract_source(self.source * 2)

    def test_crashes_and_false_or_wrong_reports_are_not_passes(self):
        good = {'case': 'submit-first', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'submit-first'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': 1}), (0, {**good, 'passed': False}),
                          (0, {**good, 'case': 'bind-first'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True})):
            with self.assertRaises(RuntimeError): check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'submit-first')

    def test_windows_does_not_claim_native_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_vm_binding.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())

    def test_coverage_and_ci_wiring(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        for i in range(7): self.assertIn(f'submit-readback-{i}', CASES)
        self.assertIn('submit-retry-timeout', CASES)
        self.assertIn('python3 tools/test_vm_binding.py', (ROOT / '.github/workflows/build.yml').read_text())


if __name__ == '__main__': unittest.main()
