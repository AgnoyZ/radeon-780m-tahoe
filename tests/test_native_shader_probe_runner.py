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
from test_native_shader_probe import CASES, PASS, CHECK, check_result, exercise, expected_result
from macos_toolchain import native_shader_command, compile_native_shader


class NativeShaderProbeRunnerTests(unittest.TestCase):
    def test_case_accounting_and_terminal_claims(self):
        self.assertEqual(len(CASES), len(set(CASES)))
        self.assertGreater(len(CASES), 900)
        for case in CASES:
            code, events = expected_result(case)
            self.assertEqual(code == 0, case in ('ok', 'number-ok', 'create-mappable', 'va-exact', 'check-ok', 'mixed-services'))
            marker = CHECK if case == 'check-ok' else PASS
            result = subprocess.CompletedProcess([], code, marker if not code else '',
                'fake-native-shader-summary ' + json.dumps({'events': events}))
            self.assertEqual({'events': events}, check_result(result, case))
        with self.assertRaises(ValueError): expected_result('unknown')

    def test_all_failed_dispatches_stop_before_gpu_cleanup_or_another_submit(self):
        for case in CASES:
            if case.startswith(('submit-', 'wait-', 'code-', 'ib-', 'output-', 'byte-')):
                code, events = expected_result(case)
                self.assertNotEqual(0, code)
                self.assertEqual(['cpu-unmap', 'close'], events[-2:])
                self.assertNotIn('gpu-unmap', events)
                self.assertNotIn('free', events)
                self.assertNotIn('ctx-free', events)
                stage = int(case.split('-')[1])
                self.assertEqual(stage, sum(event.startswith('submit-') for event in events))

    def test_check_creates_no_context_memory_or_submission(self):
        code, events = expected_result('check-ok')
        self.assertEqual(0, code)
        self.assertEqual(['host', 'matching', 'enumerate', 'parent', 'vendor', 'device', 'release-parent',
            'release-iterator', 'open', 'release-service', 'hello', 'info', 'close'], events)
        self.assertEqual(2, expected_result('ok')[1].count('wait-1') + expected_result('ok')[1].count('wait-2'))
        # Parsed vendor values are compared after both properties are read;
        # malformed properties stop inside pciValue before reading the device.
        self.assertIn('device', expected_result('vendor-wrong')[1])
        for suffix in ('missing', 'negative', 'wide', 'number-status', 'type', 'short', 'long', 'null'):
            self.assertNotIn('device', expected_result('vendor-' + suffix)[1])

    def test_accounting_crashes_false_markers_and_continuation_are_rejected(self):
        _, events = expected_result('ok')
        for code, stdout, row in ((-11, PASS, {'events': events}), (1, PASS, {'events': events}),
            (0, '', {'events': events}), (0, CHECK, {'events': events}),
            (0, PASS, {'events': events + ['submit-3']}), (0, PASS, {'events': events, 'hardware_executed': True})):
            with self.assertRaises(RuntimeError):
                check_result(subprocess.CompletedProcess([], code, stdout, 'fake-native-shader-summary ' + json.dumps(row)), 'ok')

    def test_dispatch_builder_retains_reference_shader_and_fenced_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / 'stage'; prepare(stage)
            header = (stage / 'tools/phxctl/gfx11_shader_probe.h').read_text(encoding='utf-8')
            body = re.search(r'phxGfx11ClearShader\[\] = \{(.*?)\};', header, re.S).group(1)
            words = [int(value, 16) for value in re.findall(r'0x[0-9a-fA-F]+', body)]
            self.assertEqual(79, len(words))
            self.assertEqual('735ea6ea8faa4e398ee231d55e9f80ec5c577346c333533ab2417f9beb2b795c',
                hashlib.sha256(b''.join(word.to_bytes(4, 'little') for word in words)).hexdigest())
            self.assertIn('#define PHX_SHADER_DISPATCH_DWORDS 78u', header)
            self.assertIn('#define PHX_SHADER_PROBE_PACKET_DWORDS 86u', header)
            dispatch = header.split('static inline unsigned phxGfx11DispatchCommands(')[1].split('static inline unsigned phxGfx11ClearCommands(')[0]
            self.assertNotIn('0xc0064900u', dispatch)
            self.assertIn('0xc0064900u', header.split('static inline unsigned phxGfx11ClearCommands(')[1])

    def test_real_iokit_cxx_recipe_and_ci_never_run_dispatch(self):
        command = native_shader_command(Path('stage with spaces'), Path('native probe'))
        for value in ('clang++', '-std=c++17', 'x86_64', '-Werror', 'IOKit', 'CoreFoundation'):
            self.assertIn(value, command)
        for value in ('-undefined', '-fobjc-arc', '--run'): self.assertNotIn(value, command)
        self.assertIn('-I' + str(Path('stage with spaces').resolve() / 'src/phxbringup'), command)
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertIn('python3 tools/test_native_shader_probe.py', workflow)
        self.assertNotIn('native-shader-probe --run', workflow)
        self.assertIn("native_shader_command(stage, native_shader)", (ROOT / 'tools/build_macos.py').read_text())

    def test_windows_refusal_and_existing_native_output(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('test_native_shader_probe.platform.system', return_value='Windows'):
            output = Path(directory) / 'new'
            with self.assertRaises(RuntimeError): exercise(output)
            with self.assertRaises(RuntimeError): compile_native_shader(Path(directory), output)
            self.assertFalse(output.exists())
        with tempfile.TemporaryDirectory() as directory, mock.patch('macos_toolchain.platform.system', return_value='Darwin'), \
             mock.patch('macos_toolchain.platform.machine', return_value='x86_64'), mock.patch('macos_toolchain.subprocess.run') as run:
            with self.assertRaises(RuntimeError): compile_native_shader(Path('stage'), Path(directory))
            run.assert_not_called()

    def test_native_preflight_requires_explicit_non_target_refusal(self):
        for code, stdout, stderr, good in ((4, '', 'REFUSED: missing device\n', True), (0, CHECK, '', False),
            (4, PASS, 'REFUSED:', False), (-11, '', '', False), (4, '', '', False)):
            with tempfile.TemporaryDirectory() as directory, mock.patch('macos_toolchain.platform.system', return_value='Darwin'), \
                 mock.patch('macos_toolchain.platform.machine', return_value='x86_64'), \
                 mock.patch('macos_toolchain.inspect_macho', return_value={'fixture': True}), \
                 mock.patch('macos_toolchain.subprocess.run') as run:
                run.side_effect = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], code, stdout, stderr)]
                output = Path(directory) / 'probe'
                if good:
                    report = compile_native_shader(Path('stage'), output)
                    self.assertTrue(report['check_only_executed']); self.assertFalse(report['gpu_work_submitted'])
                else:
                    with self.assertRaises(RuntimeError): compile_native_shader(Path('stage'), output)
                self.assertEqual([str(output.resolve()), '--check'], run.call_args.args[0])


if __name__ == '__main__': unittest.main()
