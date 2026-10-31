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
from test_page_tables import CASES, METHODS, check_result, exercise, extract_source


class PageTableRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_methods_and_declarations(self):
        constants, declarations, methods, hashes = extract_source(self.source)
        self.assertEqual(set(METHODS) | {'phxPtBacking'}, set(hashes))
        for line in (constants + '\n' + declarations).splitlines():
            self.assertIn(line, self.source)
        for name, digest in hashes.items():
            marker = ('phxPtBacking' if name == 'phxPtBacking' else 'PhxBringup::' + name) + '('
            start = self.source.rfind('\n', 0, self.source.index(marker)) + 1
            body = self.source[start:self.source.index('\n}\n', start) + 3]
            self.assertIn(body, methods)
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), digest)

    def test_missing_or_duplicate_actual_source_rejected(self):
        for marker in ('static bool phxPtBacking(', 'PhxBringup::ptTable(', 'PhxBringup::ptTablePhys(',
                       'PhxBringup::vmPte(', 'PhxBringup::vmidAlloc(', 'struct VmCtx {',
                       'static constexpr uint64_t kPtAddrMask'):
            with self.assertRaises(RuntimeError):
                extract_source(self.source.replace(marker, 'missing'))
        with self.assertRaises(RuntimeError):
            extract_source(self.source * 2)

    def test_rejects_false_claims_and_crashes(self):
        good = {'case': 'root-fresh', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'root-fresh'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': False}), (0, {**good, 'passed': 1}),
                          (0, {**good, 'case': 'root-cached'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True}), (0, {**good, 'extra': 1})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'root-fresh')

    def test_windows_refuses_native_claim(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_page_tables.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError):
                exercise(out)
            self.assertFalse(out.exists())

    def test_cases_and_ci_wiring(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        harness = (ROOT / 'tests/test_page_tables.cpp').read_text(encoding='utf-8')
        for case in CASES:
            if case.startswith(('fresh-', 'cached-', 'lookup-')):
                mode = case.split('-', 1)[1]
                if mode in ('short-length', 'long-length', 'null-cpu', 'unaligned-cpu', 'cpu-overflow',
                            'zero-physical', 'unaligned-physical', 'high-physical', 'physical-overflow', 'short-segment'):
                    self.assertIn('"' + mode + '"', harness)
                    continue
            if case.startswith('walk-bad-flags-'):
                self.assertIn('"walk-bad-flags-"', harness)
            else:
                self.assertIn('"' + case + '"', harness)
        self.assertIn('python3 tools/test_page_tables.py', (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8'))

    def test_cached_roots_revalidate_before_context_publication(self):
        body = extract_source(self.source)[2].split('uint32_t PhxBringup::vmidAlloc()', 1)[1]
        self.assertLess(body.index('ptTablePhys(c, 0)'), body.index('c.busy = true'))
        self.assertIn('if (!root) continue;', body)


if __name__ == '__main__':
    unittest.main()
