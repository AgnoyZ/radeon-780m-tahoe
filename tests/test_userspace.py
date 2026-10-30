"""Host-independent checks for the real Metal-plugin build, not a GPU simulation."""
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_userspace import plugin_command, plugin_info, require_plugin_exports
from verify_artifacts import inspect_plugin


class PluginRecipeTests(unittest.TestCase):
    def test_compiles_real_translation_unit_without_unresolved_symbol_escape(self):
        cmd = plugin_command(Path("source tree"), Path("Vulkan Headers"), Path("out/NVMTLDriver"))
        self.assertIn("-bundle", cmd)
        self.assertIn("-fobjc-arc", cmd)
        self.assertIn("-DNVMTL_RELEASE=1", cmd)
        self.assertIn("-mmacosx-version-min=15.0", cmd)
        self.assertIn(str(Path("source tree/NVMTLDevice.m")), cmd)
        self.assertIn("-I" + str(Path("Vulkan Headers/include")), cmd)
        self.assertNotIn("dynamic_lookup", cmd)
        self.assertNotIn("-undefined", cmd)
        self.assertNotIn("-fsyntax-only", cmd)
        self.assertEqual(cmd[cmd.index("-arch") + 1], "x86_64")
        for framework in ("Foundation", "Metal", "IOSurface", "IOKit", "CoreFoundation"):
            self.assertIn(framework, cmd)

    def test_bundle_matches_kernel_plugin_name_and_class(self):
        info = plugin_info()
        self.assertEqual(info["CFBundleExecutable"], "NVMTLDriver")
        self.assertEqual(info["CFBundlePackageType"], "BNDL")
        self.assertEqual(info["NSPrincipalClass"], "NVMTLDevice")
        self.assertEqual(info["LSMinimumSystemVersion"], "26.0")
        kernel = plistlib.loads((ROOT / "upstream/nullarc/src/phxaccel/Info.plist").read_bytes())
        matching = [p for p in kernel["IOKitPersonalities"].values() if p.get("MetalPluginClassName")]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["MetalPluginClassName"], info["NSPrincipalClass"])
        self.assertEqual(Path(matching[0]["MetalPluginName"]).name, info["CFBundleExecutable"])

    def test_requires_real_objc_exports(self):
        symbols = "00000001 S _OBJC_CLASS_$_NVMTLDevice\n00000002 S _OBJC_METACLASS_$_NVMTLDevice\n"
        require_plugin_exports(symbols)
        for invalid in ("", symbols.replace("_OBJC_CLASS_$_NVMTLDevice", "_other"),
                        symbols.replace("_OBJC_METACLASS_$_NVMTLDevice", "_other")):
            with self.assertRaisesRegex(ValueError, "missing"):
                require_plugin_exports(invalid)

    def test_rejects_wrong_plugin_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "NVMTLDriver.bundle"
            (bundle / "Contents").mkdir(parents=True)
            info = plugin_info()
            info["NSPrincipalClass"] = "UnrelatedDevice"
            (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaisesRegex(ValueError, "principal class"):
                inspect_plugin(bundle, info["CFBundleIdentifier"])


if __name__ == "__main__":
    unittest.main()
