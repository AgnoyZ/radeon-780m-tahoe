import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_source import prepare
from test_bo_retirement import OWNER_METHODS, CLIENT_METHODS
from test_vm_walk_cleanup import CASES, CORRUPTIONS, PT_METHODS, check_result, exercise, extract_source


class WalkCleanupRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        stage = Path(cls.temp.name) / 'stage'
        prepare(stage)
        cls.source = (stage / 'src/phxbringup/PhxBringup.cpp').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_walk_map_and_client_source(self):
        constants, shared, declarations, maps, methods, walks, hashes = extract_source(self.source)
        expected = {'PhxBringup::' + name for name in OWNER_METHODS + PT_METHODS}
        expected |= {'IOAccelPhxNativeClient::' + name for name in CLIENT_METHODS}
        expected |= {'phxPtBacking', 'shape', 'vaCanonical'}
        self.assertEqual(expected, set(hashes))
        for line in '\n'.join((constants, shared, declarations, maps)).splitlines():
            self.assertIn(line, self.source)
        for name, digest in hashes.items():
            marker = name + '('
            found = False
            for match in re.finditer(re.escape(marker), self.source):
                start = self.source.rfind('\n', 0, match.start()) + 1
                body = self.source[start:self.source.find('\n}\n', start) + 3]
                if body in methods + walks and hashlib.sha256(body.encode()).hexdigest() == digest:
                    found = True
            self.assertTrue(found, name)

    def test_missing_or_duplicate_methods_rejected(self):
        for marker in ('PhxBringup::vmPte(', 'PhxBringup::vmMap(', 'PhxBringup::vmUnmap(',
                       'static bool phxPtBacking(', 'IOAccelPhxNativeClient::reapPending(', 'struct Map {'):
            with self.assertRaises(RuntimeError):
                extract_source(self.source.replace(marker, 'missing'))
        with self.assertRaises(RuntimeError):
            extract_source(self.source * 2)

    def test_reports_cannot_claim_hardware_or_ignore_crashes(self):
        good = {'case': 'free-real', 'passed': True, 'hardware_executed': False}
        self.assertEqual(good, check_result(subprocess.CompletedProcess([], 0, json.dumps(good), ''), 'free-real'))
        for code, row in ((1, good), (-11, good), (0, {**good, 'passed': False}), (0, {**good, 'passed': 1}),
                          (0, {**good, 'case': 'map-real'}), (0, {**good, 'hardware_executed': 0}),
                          (0, {**good, 'hardware_executed': True}), (0, {**good, 'extra': 1})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, json.dumps(row), ''), 'free-real')

    def test_windows_does_not_claim_cpp_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_vm_walk_cleanup.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError):
                exercise(out)
            self.assertFalse(out.exists())

    def test_actual_allocator_and_walker_are_not_flat_map_fakes(self):
        harness = (ROOT / 'tests/test_vm_walk_cleanup.cpp').read_text(encoding='utf-8')
        self.assertIn('#define PHX_REAL_PAGE_TABLES', harness)
        common = (ROOT / 'tests/test_bo_retirement.cpp').read_text(encoding='utf-8')
        self.assertIn('#include "walk-methods.inc"', common)
        self.assertIn('#ifndef PHX_NO_BO_TEST_MAIN', common)

    def test_cases_and_ci_wiring(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        harness = (ROOT / 'tests/test_vm_walk_cleanup.cpp').read_text(encoding='utf-8')
        for case in CASES:
            modes = CORRUPTIONS + ('leaf-invalid', 'leaf-flags', 'leaf-zero-physical')
            suffix = next((mode for mode in modes if case in ('map-corrupt-' + mode, 'unmap-corrupt-' + mode)), None)
            self.assertIn('"' + (suffix if suffix else case) + '"', harness)
        self.assertIn('python3 tools/test_vm_walk_cleanup.py', (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
