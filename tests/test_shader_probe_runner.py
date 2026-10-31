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
from test_shader_probe import MARKER, cases, check_result, exercise, expected_result


class ShaderProbeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.stage = Path(cls.temp.name) / 'stage'
        prepare(cls.stage)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_exact_case_accounting_and_success_marker(self):
        names = list(cases())
        self.assertEqual(len(names), len(set(names)))
        for case in names:
            status, counts = expected_result(case)
            self.assertEqual(status == 0, case in ('ok', 'work-adjacent', 'delay-eintr', 'work-eintr', 'work-delayed'))
            self.assertEqual(counts, check_result(subprocess.CompletedProcess([], status, MARKER if not status else '',
                'fake-mes-queue-summary ' + json.dumps(counts)), case))
        self.assertEqual({'lookups': 1, 'opens': 1, 'hellos': 1, 'snapshots': 1, 'reads': 65, 'writes': 37,
            'vreads': 196, 'vwrites': 13215, 'bells': 3, 'sleeps': 4, 'closes': 1, 'work_bells': 1}, expected_result('ok')[1])

    def test_reference_shader_and_actual_dispatch_are_staged(self):
        source = (self.stage / 'tools/phxctl/mesboot.c').read_text(encoding='utf-8')
        header = (self.stage / 'tools/phxctl/gfx11_shader_probe.h').read_text(encoding='utf-8')
        body = re.search(r'phxGfx11ClearShader\[\] = \{(.*?)\};', header, re.S).group(1)
        words = [int(word, 16) for word in re.findall(r'0x[0-9a-fA-F]+', body)]
        self.assertEqual(79, len(words))
        self.assertEqual('735ea6ea8faa4e398ee231d55e9f80ec5c577346c333533ab2417f9beb2b795c',
            hashlib.sha256(b''.join(word.to_bytes(4, 'little') for word in words)).hexdigest())
        self.assertIn('Copyright 2022 Advanced Micro Devices, Inc.', header)
        self.assertIn('Permission is hereby granted', header)
        self.assertIn('0xc0031502u, 1, 1, 1, 1', header)
        self.assertIn('0xc0065800u, 0, 0xffffffffu, 0xff, 0, 0, 10, 0xc381', header)
        self.assertIn('shader ? 6u : 5u', source)
        self.assertIn('if (shader) compute_shader_probe(&work, &memory)', source)
        self.assertIn('python3 tools/test_shader_probe.py', (ROOT / '.github/workflows/build.yml').read_text())

    def test_invalid_mapping_and_sixth_page_fail_before_memory_writes(self):
        for case in ('work-sixth-page-overlap', 'work-arena-unmapped', 'work-last-page-overlap', 'vbad-13'):
            status, counts = expected_result(case)
            self.assertEqual(75, status)
            self.assertEqual(0, counts['vwrites'])
            self.assertEqual(0, counts['work_bells'])

    def test_every_code_output_and_guard_failure_is_terminal(self):
        for prefix, count in (('shader-code', 40), ('shader-output', 256), ('shader-guard', 4)):
            for i in range(count):
                status, counts = expected_result(f'{prefix}-{i}')
                self.assertEqual(75, status)
                self.assertEqual(0 if prefix == 'shader-code' else 1, counts['work_bells'])
                self.assertEqual(0, counts['closes'])
        for case in ('work-timeout', 'work-fence-low', 'work-fence-high'):
            self.assertEqual(403, expected_result(case)[1]['sleeps'])
            self.assertEqual(462, expected_result(case)[1]['vreads'])

    def test_false_claims_shapes_and_crashes_are_rejected(self):
        counts = expected_result('ok')[1]
        for code, body, marker in ((-11, counts, MARKER), (1, counts, MARKER), (0, {**counts, 'work_bells': True}, MARKER),
                                  (0, {**counts, 'hardware_executed': True}, MARKER), (0, counts, '')):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, marker, 'fake-mes-queue-summary ' + json.dumps(body)), 'ok')

    def test_windows_cannot_claim_native_or_shader_execution(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_shader_probe.platform.system', return_value='Windows'):
            out = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(out)
            self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
