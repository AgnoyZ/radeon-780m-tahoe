import io
import json
from pathlib import Path
import plistlib
import struct
import sys
import tarfile
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_source import prepare, export_archive
from verify_artifacts import inspect_macho, inspect_kext

class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.stage = Path(cls.temp.name) / "source"
        cls.provenance = prepare(cls.stage)
        cls.bringup = (cls.stage / "src/phxbringup/PhxBringup.cpp").read_text(encoding='utf-8')
        cls.fb = (cls.stage / "src/phxaccel/accel/phxfb.cpp").read_text(encoding='utf-8')
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def test_no_fake_retirement(self):
        self.assertNotIn("const uint64_t seq = ++emitted;", self.bringup)
        self.assertNotIn("not busy: E1 retires", self.bringup)
        submit = self.bringup.split("IOReturn IOAccelPhxNativeClient::doSubmit(")[1].split("IOReturn IOAccelPhxNativeClient::doDbgSmu(")[0]
        self.assertTrue(submit.rstrip().endswith("return kIOReturnNotReady;\n}"))
        wait = self.bringup.split("IOReturn IOAccelPhxNativeClient::doWaitSeq(")[1]
        self.assertTrue(wait.rstrip().endswith("return kIOReturnNotReady;\n}"))
        self.assertIn("owner->gpuReady() ? owner->gpuRetired() : 0", self.bringup)
    def test_exact_queue_policy_is_wired(self):
        self.assertIn("phx780m::queueIndex(gfx, gq[0].ready, gq[1].ready)", self.bringup)
        self.assertIn("phx780m::sameEngine(firstIb.ip_type, ib.ip_type)", self.bringup)
        self.assertNotIn("with one of them missing, the other runs both", self.bringup)
    def test_gate_precedes_hardware_changes(self):
        start = self.bringup.split("bool PhxBringup::start(")[1].split("void PhxBringup::stop(")[0]
        self.assertLess(start.index("phx780m::allowDevice"), start.index("setBusMasterEnable"))
        fb_start = self.fb.split("bool PhxAMDFB::start(")[1]
        self.assertLess(fb_start.index("phx780m::allowDevice"), fb_start.index("takeBootArming()"))
    def test_policy_copy_identical(self):
        policy = (ROOT / "src/PhxHardwarePolicy.hpp").read_bytes()
        for name in ("phxbringup", "phxaccel"):
            self.assertEqual(policy, (self.stage / "src" / name / "PhxHardwarePolicy.hpp").read_bytes())
    def test_does_not_overwrite_source(self):
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            prepare(self.stage)
    def test_provenance_is_not_hardware_pass(self):
        self.assertFalse(self.provenance["hardware_tested"])
        self.assertEqual(1, len(self.provenance["patches_sha256"]))
    def test_reject_path_traversal(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            entry = tarfile.TarInfo("../escape")
            entry.size = 1
            archive.addfile(entry, io.BytesIO(b"x"))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "leaves staging"):
                export_archive(data.getvalue(), Path(temp))

class BinaryTests(unittest.TestCase):
    def make_binary(self, path, filetype=11):
        header = struct.pack("<8I", 0xfeedfacf, 0x1000007, 3, filetype, 1, 72, 0, 0)
        segment = struct.pack("<II16sQQQQIIII", 0x19, 72, b"__TEXT", 0, 108, 0, 108, 7, 5, 0, 0)
        path.write_bytes(header + segment + b"test")
    def test_valid_structural_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test"
            self.make_binary(path)
            self.assertEqual("x86_64", inspect_macho(path, 11)["architecture"])
    def test_truncated_and_wrong_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test"
            path.write_bytes(b"invalid")
            with self.assertRaises(ValueError): inspect_macho(path, 11)
            self.make_binary(path, 1)
            with self.assertRaises(ValueError): inspect_macho(path, 11)
    def test_segment_outside_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test"
            self.make_binary(path)
            data = bytearray(path.read_bytes())
            struct.pack_into("<Q", data, 32 + 48, 999999)
            path.write_bytes(data)
            with self.assertRaises(ValueError): inspect_macho(path, 11)
    def test_kext_identity_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            (bundle / "Contents/MacOS").mkdir(parents=True)
            info = {"CFBundlePackageType": "KEXT", "CFBundleIdentifier": "example", "CFBundleExecutable": "../escape"}
            (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError): inspect_kext(bundle, "example")

if __name__ == "__main__": unittest.main()
