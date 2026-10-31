import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from target_inventory import CAPTURE_MARKER, COMMANDS, InventoryError, import_capture
from test_target_inventory import fixture_device


def write_capture(source, version='14.7', build='23H124', darwin='23.6.0'):
    source.mkdir()
    (source / '.gitignore').write_bytes(b'*\n')
    (source / 'capture.complete').write_bytes(CAPTURE_MARKER)
    (source / 'platform.txt').write_bytes(b'Darwin\n')
    (source / 'architecture.txt').write_bytes(b'x86_64\n')
    outputs = {'os_version': version.encode() + b'\n', 'os_build': build.encode() + b'\n',
               'darwin_release': darwin.encode() + b'\n', 'ram_bytes': b'34359738368\n',
               'pci': plistlib.dumps([fixture_device()])}
    for label, data in outputs.items():
        (source / (label + '.txt')).write_bytes(data)
        (source / (label + '.status')).write_bytes(b'0\n')
        (source / (label + '.stderr')).write_bytes(b'PRIVATE_STDERR')
    return outputs


class RecoveryImportTests(unittest.TestCase):
    def test_native_script_uses_exact_existing_read_commands_and_lf(self):
        data = (ROOT / 'tools/recovery_inventory.sh').read_bytes()
        self.assertNotIn(b'\r', data)
        calls = re.findall(r'^run_read ([a-z_]+) (.+)$', data.decode('utf-8'), re.M)
        self.assertEqual([(label, ' '.join(command)) for label, command in COMMANDS.items()], calls)
        self.assertIn('*.sh text eol=lf', (ROOT / '.gitattributes').read_text())

    def test_offline_import_runs_no_commands_and_preserves_observed_os(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch('target_inventory.subprocess.run') as run:
            source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
            outputs = write_capture(source)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            result = import_capture(source, out)
            run.assert_not_called()
            self.assertFalse(result['system']['requested_system_family_matches'])
            self.assertEqual('23H124', result['system']['os_build'])
            self.assertEqual('offline_native_capture_v1', result['collection_method'])
            self.assertEqual({k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}, result['capture_files_sha256'])
            for key in ('safe_to_initialize', 'gpu_work_submitted', 'native_capture_source_verified'):
                self.assertIs(result[key], False)
            self.assertEqual(1, result['pci']['target_candidate_count'])
            self.assertEqual(['inventory.json'], [p.name for p in out.iterdir()])
            self.assertNotIn('PRIVATE_', (out / 'inventory.json').read_text(encoding='utf-8'))
            self.assertEqual(before, {p.name: p.read_bytes() for p in source.iterdir()})

    def test_tahoe_report_does_not_grant_initialization_or_prove_capture_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
            write_capture(source, '26.0.1', '25A362', '25.0.0')
            result = import_capture(source, out)
            self.assertTrue(result['system']['requested_system_family_matches'])
            self.assertFalse(result['safe_to_initialize'])
            self.assertFalse(result['native_capture_source_verified'])

    def test_missing_extra_and_failed_entries_refuse_partial_report(self):
        for fault in ('marker', 'missing', 'extra', 'status', 'architecture', 'platform', 'gitignore', 'pci', 'numeric'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
                write_capture(source)
                if fault == 'missing': (source / 'pci.txt').unlink()
                elif fault == 'extra': (source / 'PRIVATE_UNEXPECTED_FILE').write_bytes(b'private')
                else:
                    name = {'marker': 'capture.complete', 'status': 'pci.status', 'architecture': 'architecture.txt',
                            'platform': 'platform.txt', 'gitignore': '.gitignore', 'pci': 'pci.txt', 'numeric': 'os_build.txt'}[fault]
                    (source / name).write_bytes(b'PRIVATE_INVALID_DATA')
                with self.assertRaises(InventoryError) as caught: import_capture(source, out)
                self.assertFalse(out.exists()); self.assertNotIn('PRIVATE', str(caught.exception))

    def test_every_command_status_is_required(self):
        for label in COMMANDS:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
                write_capture(source); (source / (label + '.status')).write_bytes(b'74\n')
                with self.assertRaises(InventoryError): import_capture(source, out)
                self.assertFalse(out.exists())

    def test_oversized_input_and_stderr_are_bounded(self):
        for name in ('pci.txt', 'pci.stderr'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
                write_capture(source)
                with (source / name).open('wb') as stream: stream.truncate(16 * 1024 * 1024 + 1)
                with self.assertRaises(InventoryError): import_capture(source, out)
                self.assertFalse(out.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
            write_capture(source); out.mkdir(); (out / 'inventory.json').write_bytes(b'keep')
            with self.assertRaises(InventoryError): import_capture(source, out)
            self.assertEqual(b'keep', (out / 'inventory.json').read_bytes())

    @unittest.skipIf(os.name == 'nt', 'Real link tests run in POSIX CI')
    def test_file_and_root_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
            write_capture(source)
            alias = Path(temporary) / 'alias'; alias.symlink_to(source, target_is_directory=True)
            with self.assertRaises(InventoryError): import_capture(alias, out)
            original = (source / 'pci.txt').read_bytes()
            private = Path(temporary) / 'private-input'; private.write_bytes(original)
            (source / 'pci.txt').unlink(); (source / 'pci.txt').symlink_to(private)
            with self.assertRaises(InventoryError): import_capture(source, out)
            self.assertFalse(out.exists())

    def test_cli_import_is_available_on_windows_and_runs_no_live_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, out = Path(temporary) / 'private', Path(temporary) / 'parsed'
            write_capture(source)
            result = subprocess.run([sys.executable, str(ROOT / 'tools/target_inventory.py'), '--from-capture', str(source),
                                     '--out', str(out)], capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn('PRIVATE', result.stdout + result.stderr)
            self.assertFalse(json.loads((out / 'inventory.json').read_text())['safe_to_initialize'])


if __name__ == '__main__': unittest.main()
