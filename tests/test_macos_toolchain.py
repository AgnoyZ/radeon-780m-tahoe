from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from macos_toolchain import metal_command, probe_command, preflight, packaging_preflight, native_capture_preflight


class MacOSToolchainTests(unittest.TestCase):
    def test_metal_31_uses_the_actual_compiler_standard_spelling(self):
        command = metal_command(Path("source with spaces.metal"), Path("output.air"), 17)
        self.assertIn("-std=metal3.1", command)
        self.assertNotIn("-std=macos-metal3.1", command)
        self.assertEqual(["xcrun", "-sdk", "macosx", "metal"], command[:4])
        self.assertIn("-DADD_VALUE=17", command)
        self.assertIn(str(Path("source with spaces.metal").resolve()), command)

    def test_native_probe_recipes_keep_required_frameworks_and_warnings(self):
        for kind in ("metal-smoke", "plugin-compile-probe"):
            with self.subTest(kind=kind):
                command = probe_command(kind, Path("probe"))
                for item in ("x86_64", "-fobjc-arc", "-Werror", "Foundation", "Metal", "IOKit"):
                    self.assertIn(item, command)
                self.assertNotIn("-undefined", command)
        self.assertIn("-I" + str(ROOT / "src"), probe_command("metal-smoke", Path("probe")))
        with self.assertRaises(ValueError):
            probe_command("unknown", Path("probe"))

    def test_preflight_refuses_non_native_host_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("macos_toolchain.platform.system", return_value="Windows"):
            output = Path(directory) / "new"
            with self.assertRaises(RuntimeError):
                preflight(output)
            self.assertFalse(output.exists())

    def test_preflight_refuses_existing_output_before_running_tools(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("macos_toolchain.platform.system", return_value="Darwin"), \
             mock.patch("macos_toolchain.platform.machine", return_value="x86_64"), \
             mock.patch("macos_toolchain.subprocess.run") as run:
            with self.assertRaises(RuntimeError):
                preflight(Path(directory))
            run.assert_not_called()

    def test_preflight_precedes_expensive_dependency_builds(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertLess(workflow.index("tools/macos_toolchain.py"), workflow.index("Checkout pinned MacKernelSDK"))

    def test_packaging_fixture_refuses_non_native_host(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch("macos_toolchain.platform.system", return_value="Windows"):
            output = Path(directory) / "new"
            with self.assertRaises(RuntimeError):
                packaging_preflight(output)
            self.assertFalse(output.exists())

    def test_packaging_fixture_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("macos_toolchain.platform.system", return_value="Darwin"), \
             mock.patch("macos_toolchain.platform.machine", return_value="x86_64"), \
             mock.patch("macos_toolchain.subprocess.run") as run:
            with self.assertRaises(RuntimeError):
                packaging_preflight(Path(directory))
            run.assert_not_called()

    def test_native_capture_refuses_non_native_host_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('macos_toolchain.subprocess.run') as run:
            with mock.patch('macos_toolchain.platform.system', return_value='Windows'):
                with self.assertRaises(RuntimeError): native_capture_preflight(Path(directory) / 'new')
            with mock.patch('macos_toolchain.platform.system', return_value='Darwin'), \
                 mock.patch('macos_toolchain.platform.machine', return_value='x86_64'):
                with self.assertRaises(RuntimeError): native_capture_preflight(Path(directory))
            run.assert_not_called()

    def test_native_capture_failure_does_not_expose_raw_output(self):
        import subprocess
        for response in (subprocess.CompletedProcess([], 1, b'PRIVATE_STDOUT', b'PRIVATE_STDERR'),
                         subprocess.TimeoutExpired('capture', 130, output=b'PRIVATE_TIMEOUT')):
            with tempfile.TemporaryDirectory() as directory, \
                 mock.patch('macos_toolchain.platform.system', return_value='Darwin'), \
                 mock.patch('macos_toolchain.platform.machine', return_value='x86_64'), \
                 mock.patch('macos_toolchain.import_capture') as importer, \
                 mock.patch('macos_toolchain.subprocess.run') as run:
                if isinstance(response, Exception): run.side_effect = response
                else: run.return_value = response
                with self.assertRaises(RuntimeError) as caught: native_capture_preflight(Path(directory) / 'new')
                self.assertNotIn('PRIVATE', str(caught.exception)); importer.assert_not_called()
                self.assertTrue(run.call_args.kwargs['capture_output'])
                self.assertEqual(130, run.call_args.kwargs['timeout'])
                self.assertNotIn('DYLD_LIBRARY_PATH', run.call_args.kwargs['env'])


if __name__ == "__main__":
    unittest.main()
