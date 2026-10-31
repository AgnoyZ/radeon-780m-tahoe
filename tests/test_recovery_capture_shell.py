import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from target_inventory import COMMANDS, InventoryError, import_capture
from test_target_inventory import fixture_device


@unittest.skipIf(os.name == 'nt', 'POSIX shell execution runs in Linux CI; Windows does not claim it')
class RecoveryCaptureShellTests(unittest.TestCase):
    def fixture(self, directory, fault='ok'):
        work = Path(directory)
        program = work / 'native-command-fake'
        calls = work / 'calls.jsonl'
        pci = work / 'fixture.plist'; pci.write_bytes(plistlib.dumps([fixture_device()]))
        program.write_text('#!' + sys.executable + '\n' + f'''
import json, os, pathlib, sys, time
args = sys.argv[1:]
with open({str(calls)!r}, 'a') as stream: stream.write(json.dumps(args) + '\\n')
fault = {fault!r}
if args == ['uname', '-s']: print('Linux' if fault == 'non-macos' else 'Darwin')
elif args == ['uname', '-m']: print('arm64' if fault == 'arm' else 'x86_64')
elif args == ['sw_vers', '-productVersion']: print('14.7')
elif args == ['sw_vers', '-buildVersion']:
    if fault == 'command-status': sys.exit(74)
    print('23H124')
elif args == ['sysctl', '-n', 'kern.osrelease']: print('23.6.0')
elif args == ['sysctl', '-n', 'hw.memsize']: print('34359738368')
elif args == ['ioreg', '-a', '-l', '-r', '-c', 'IOPCIDevice', '-d', '1']:
    if fault == 'timeout': time.sleep(5)
    if fault == 'oversized': sys.stdout.buffer.write(b'X' * (17 * 1024 * 1024))
    elif fault == 'malformed': sys.stdout.buffer.write(b'PRIVATE_INVALID_XML')
    else: sys.stdout.buffer.write(pathlib.Path({str(pci)!r}).read_bytes())
else: sys.exit(99)
sys.stderr.write('PRIVATE_STDERR')
''', encoding='utf-8')
        program.chmod(0o700)
        script = (ROOT / 'tools/recovery_inventory.sh').read_text(encoding='utf-8')
        for original in ('/usr/bin/uname', '/usr/bin/sw_vers', '/usr/sbin/sysctl', '/usr/sbin/ioreg'):
            script = script.replace(original, shlex.quote(str(program)) + ' ' + original.rsplit('/', 1)[1])
        script = script.replace('/bin/sleep 20 &', '/bin/sleep 1 &')
        path = work / 'staged-capture.sh'; path.write_text(script, encoding='utf-8')
        return path, calls

    def run_capture(self, script, out):
        result = subprocess.run(['/bin/sh', str(script), str(out)], capture_output=True, text=True, timeout=15,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'DYLD_LIBRARY_PATH': 'unused-test-value'})
        self.assertNotIn('PRIVATE', result.stdout + result.stderr)
        return result

    def test_actual_script_fixed_command_sequence_and_private_offline_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, calls = self.fixture(temporary)
            out = Path(temporary) / 'capture with spaces'
            result = self.run_capture(script, out)
            self.assertEqual(0, result.returncode, result.stderr)
            sequence = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual([['uname', '-s'], ['uname', '-m']] + [[Path(v[0]).name] + v[1:] for v in COMMANDS.values()], sequence)
            self.assertEqual(0o700, out.stat().st_mode & 0o777)
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in out.iterdir()))
            report = import_capture(out, Path(temporary) / 'imported')
            self.assertEqual(1, report['pci']['target_candidate_count'])
            self.assertFalse(report['system']['requested_system_family_matches'])
            self.assertFalse(report['safe_to_initialize'])
            self.assertFalse(report['gpu_work_submitted'])
            subprocess.run(['git', 'init', '-q', temporary], check=True, capture_output=True)
            ignored = subprocess.run(['git', '-C', temporary, 'check-ignore', '--quiet', str(out / 'pci.txt')],
                                     capture_output=True)
            self.assertEqual(0, ignored.returncode)

    def test_host_refusal_does_not_create_a_capture(self):
        for fault in ('non-macos', 'arm'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                script, _ = self.fixture(temporary, fault)
                out = Path(temporary) / 'private'
                self.assertNotEqual(0, self.run_capture(script, out).returncode)
                self.assertFalse(out.exists())

    def test_failed_command_stops_before_later_queries_and_completion_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, calls = self.fixture(temporary, 'command-status')
            out = Path(temporary) / 'private'
            self.assertNotEqual(0, self.run_capture(script, out).returncode)
            self.assertFalse((out / 'capture.complete').exists())
            self.assertNotIn('ioreg', calls.read_text())
            self.assertEqual(b'74\n', (out / 'os_build.status').read_bytes())
            with self.assertRaises(InventoryError): import_capture(out, Path(temporary) / 'imported')

    def test_timeout_preserves_only_an_incomplete_private_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, _ = self.fixture(temporary, 'timeout')
            out = Path(temporary) / 'private'
            self.assertNotEqual(0, self.run_capture(script, out).returncode)
            self.assertTrue((out / 'pci.timeout').exists())
            self.assertFalse((out / 'capture.complete').exists())

    def test_file_limit_rejects_oversized_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, _ = self.fixture(temporary, 'oversized')
            out = Path(temporary) / 'private'
            self.assertNotEqual(0, self.run_capture(script, out).returncode)
            self.assertLessEqual((out / 'pci.txt').stat().st_size, 16 * 1024 * 1024)
            self.assertFalse((out / 'capture.complete').exists())

    def test_complete_command_marker_is_not_a_valid_inventory_by_itself(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, _ = self.fixture(temporary, 'malformed')
            out = Path(temporary) / 'private'
            self.assertEqual(0, self.run_capture(script, out).returncode)
            with self.assertRaises(InventoryError): import_capture(out, Path(temporary) / 'imported')
            self.assertFalse((Path(temporary) / 'imported').exists())

    def test_existing_output_is_never_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            script, _ = self.fixture(temporary)
            out = Path(temporary) / 'private'; out.mkdir(); (out / 'keep').write_bytes(b'preserve')
            self.assertNotEqual(0, self.run_capture(script, out).returncode)
            self.assertEqual(['keep'], [p.name for p in out.iterdir()])
            self.assertEqual(b'preserve', (out / 'keep').read_bytes())


if __name__ == '__main__': unittest.main()
