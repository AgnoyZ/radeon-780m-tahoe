from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_air_runtime import cmake_command, system_dependencies
from test_air_runtime import llvm_exports


class AirRuntimeBuildTests(unittest.TestCase):
    def test_exports_come_from_the_actual_plugin_contract(self):
        names = llvm_exports(ROOT / "upstream/nullarc/src/nmplugin/NVMTLLibraryLoad.m")
        self.assertEqual(38, len(names))
        for name in ("LLVMParseBitcodeInContext2", "LLVMGetDiagInfoSeverity", "LLVMRunPasses", "LLVMGetArrayLength2"):
            self.assertIn(name, names)
        self.assertNotIn("name", names)

    def test_runtime_build_has_real_reader_and_pass_components(self):
        command = cmake_command(Path("source"), Path("native"))
        self.assertIn("-DLLVM_BUILD_LLVM_DYLIB=ON", command)
        self.assertIn("-DLLVM_DYLIB_COMPONENTS=core;bitreader;bitwriter;irreader;passes", command)
        self.assertIn("-DCMAKE_OSX_ARCHITECTURES=x86_64", command)
        self.assertIn("-DLLVM_ENABLE_ZSTD=OFF", command)
        self.assertNotIn("install", command)
        self.assertNotIn("-DLLVM_INCLUDE_TOOLS=OFF", command)

    def test_accepts_only_system_library_dependencies(self):
        text = "library:\n\t@rpath/libLLVM.dylib (compatibility version 1.0.0)\n\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0)\n"
        self.assertEqual(["/usr/lib/libc++.1.dylib"], system_dependencies(text))

    def test_rejects_build_machine_or_unbundled_dependencies(self):
        for path in ("/usr/local/lib/libzstd.1.dylib", "/opt/homebrew/lib/libxml2.dylib",
                     "@rpath/libLLVMSupport.dylib", "/tmp/build/libLLVM.dylib"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "Non-system LLVM dependency"):
                    system_dependencies("library:\n\t@rpath/libLLVM.dylib (compatibility version 1.0.0)\n\t" + path + " (compatibility version 1.0.0)\n")


if __name__ == "__main__":
    unittest.main()
