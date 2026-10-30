import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_radv import ordered_patches, prepare_radv
from build_radv import meson_command, test_no_device as run_no_device_test, system_dependencies


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.PIPE).decode().strip()


class RadvSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mesa, self.cobalt, self.nullarc = [self.root / name for name in ("mesa", "cobalt", "nullarc")]
        for path in (self.mesa, self.cobalt, self.nullarc):
            path.mkdir()
            git(path, "init", "-q")
            git(path, "config", "core.autocrlf", "false")
        (self.mesa / "sequence.txt").write_text("0\n")
        for source, offset, count in ((self.cobalt, 0, 9), (self.nullarc, 9, 6)):
            (source / "patches").mkdir()
            for n in range(1, count + 1):
                old = offset + n - 1
                patch = f"diff --git a/sequence.txt b/sequence.txt\n--- a/sequence.txt\n+++ b/sequence.txt\n@@ -1 +1 @@\n-{old}\n+{old+1}\n"
                (source / "patches" / f"{n:04d}-step.patch").write_text(patch)
        self.lock = {}
        for name, path in (("Mesa", self.mesa), ("Cobalt64", self.cobalt), ("nullarc", self.nullarc)):
            git(path, "add", ".")
            git(path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
            self.lock[name] = {"commit": git(path, "rev-parse", "HEAD")}
        self.lock["nullarc"]["path"] = "nullarc"
        self.lock["Cobalt64"].update({"patch_directory": "patches", "patch_count": 9})
        self.lock["radv-phoenix"] = {"patch_directory": "patches", "patch_count": 6}
        self.save_lock()

    def save_lock(self):
        (self.root / "upstream.lock.json").write_text(json.dumps(self.lock))

    def test_real_git_patch_sequence_and_provenance(self):
        out = self.root / "stage"
        report = prepare_radv(self.mesa, self.cobalt, out, self.root)
        self.assertEqual("15\n", (out / "sequence.txt").read_text())
        self.assertEqual("0\n", (self.mesa / "sequence.txt").read_text())
        self.assertEqual("", git(self.mesa, "status", "--porcelain"))
        self.assertEqual(15, len(report["patches"]))
        self.assertEqual(["Cobalt64"] * 9 + ["radv-phoenix"] * 6,
                         [entry["component"] for entry in report["patches"]])
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in report["patches"]))
        self.assertFalse(report["hardware_tested"])
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            prepare_radv(self.mesa, self.cobalt, out, self.root)

    def test_dirty_or_wrong_revision_is_rejected_before_output(self):
        out = self.root / "stage"
        (self.mesa / "sequence.txt").write_text("dirty\n")
        with self.assertRaisesRegex(RuntimeError, "must be clean"):
            prepare_radv(self.mesa, self.cobalt, out, self.root)
        self.assertFalse(out.exists())
        (self.mesa / "sequence.txt").write_text("0\n")
        self.lock["Mesa"]["commit"] = "0" * 40
        self.save_lock()
        with self.assertRaisesRegex(RuntimeError, "Unexpected source revision"):
            prepare_radv(self.mesa, self.cobalt, out, self.root)
        self.assertFalse(out.exists())

    def test_staging_cannot_contaminate_upstream(self):
        with self.assertRaisesRegex(RuntimeError, "outside all upstream"):
            prepare_radv(self.mesa, self.cobalt, self.mesa / "stage", self.root)

    def test_missing_or_misnumbered_patch_is_rejected(self):
        directory = self.cobalt / "patches"
        (directory / "0002-step.patch").rename(directory / "0010-step.patch")
        with self.assertRaisesRegex(RuntimeError, "consecutively numbered"):
            ordered_patches(directory, 9)
        with self.assertRaisesRegex(RuntimeError, "exactly 8"):
            ordered_patches(directory, 8)


class RadvBuildTests(unittest.TestCase):
    def test_real_amd_build_options_without_install_or_fallback(self):
        command = meson_command(Path("source"), Path("native"))
        self.assertEqual(["meson", "setup", "native", "source"], command[:4])
        for option in ("-Dvulkan-drivers=amd", "-Dllvm=disabled", "--wrap-mode=nofallback", "-Dspirv-tools=disabled"):
            self.assertIn(option, command)
        self.assertNotIn("install", command)

    def test_rejects_the_observed_host_spirv_tools_dependency(self):
        output = ("library:\n\t@rpath/libvulkan_radeon.dylib (compatibility version 0.0.0)\n"
                  "\t/usr/local/opt/spirv-tools/lib/libSPIRV-Tools.dylib (compatibility version 0.0.0)\n")
        with self.assertRaisesRegex(ValueError, "Non-system RADV dependency"):
            system_dependencies(output)

    def test_accepts_system_frameworks_and_rejects_wrong_icd_identity(self):
        dependencies = ["/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit", "/usr/lib/libz.1.dylib"]
        output = "library:\n\t@rpath/libvulkan_radeon.dylib (compatibility version 0.0.0)\n"
        output += "".join("\t" + item + " (compatibility version 1.0.0)\n" for item in dependencies)
        self.assertEqual(dependencies, system_dependencies(output))
        with self.assertRaisesRegex(ValueError, "Unexpected RADV dylib identity"):
            system_dependencies(output.replace("@rpath/libvulkan_radeon.dylib", "/tmp/libvulkan_radeon.dylib"))

    def test_negative_runner_checks_all_four_variants_and_cleans_environment(self):
        stdout = '{"runtime_loaded":true,"physical_devices":0,"gpu_submitted":false}'
        messages = ["IOServiceOpen(PhxBringup", "mock and host-only backends are disabled",
                    "mock and host-only backends are disabled", "only the Phoenix device profile is supported"]
        replies = [subprocess.CompletedProcess([], 0, stdout, message) for message in messages]
        with patch.dict("os.environ", {"RADV_DARWIN_MOCK": "1", "VK_ICD_FILENAMES": "untrusted", "DYLD_INSERT_LIBRARIES": "untrusted"}):
            with patch("build_radv.subprocess.run", side_effect=replies) as run:
                report = run_no_device_test(Path("probe"), Path("library"))
        self.assertEqual(4, len(report))
        first_env = run.call_args_list[0].kwargs["env"]
        for key in ("RADV_DARWIN_MOCK", "VK_ICD_FILENAMES", "DYLD_INSERT_LIBRARIES"):
            self.assertNotIn(key, first_env)
        self.assertEqual("1", run.call_args_list[1].kwargs["env"]["RADV_DARWIN_MOCK"])
        self.assertTrue(all(call.kwargs["timeout"] == 30 for call in run.call_args_list))

    def test_hardware_present_skip_or_unexplained_empty_result_is_not_pass(self):
        for code, stderr in ((77, "target service present"), (0, "")):
            with self.subTest(code=code):
                with patch("build_radv.subprocess.run", return_value=subprocess.CompletedProcess([], code, "{}", stderr)):
                    with self.assertRaisesRegex(RuntimeError, "no-device test native failed"):
                        run_no_device_test(Path("probe"), Path("library"))

    def test_fake_device_is_not_an_acceptable_negative_result(self):
        result = subprocess.CompletedProcess([], 0,
                    '{"runtime_loaded":true,"physical_devices":1,"gpu_submitted":false}', "IOServiceOpen(PhxBringup")
        with patch("build_radv.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Unexpected no-device"):
                run_no_device_test(Path("probe"), Path("library"))


if __name__ == "__main__":
    unittest.main()
