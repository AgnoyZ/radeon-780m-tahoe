import hashlib
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
        self.assertEqual(14, len(self.provenance["patches_sha256"]))
    def test_firmware_profile_is_staged_and_bound_to_provenance(self):
        from firmware_profile import checked_header
        data = checked_header()
        self.assertEqual(data, (self.stage / "src/phxbringup/PhxFirmwareProfile.h").read_bytes())
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.provenance["firmware_profile_sha256"])
    def test_bootstrap_memory_headers_are_staged_and_hashed(self):
        for name, key in (("PhxBootMemory.h", "boot_memory_sha256"), ("PhxGartLayout.h", "gart_layout_sha256")):
            data = (ROOT / "src" / name).read_bytes()
            self.assertEqual(data, (self.stage / "src/phxbringup" / name).read_bytes())
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.provenance[key])
    def test_boot_memory_selector_is_read_only_and_privileged(self):
        body = self.bringup.split("IOReturn PhxBringup::bootMemory(")[1].split("IOReturn PhxBringup::configurePspLayout(")[0]
        for write in ("wreg(", "getVirtualAddress(", "pspRunCmd("):
            self.assertNotIn(write, body)
        handler = self.bringup.split("IOReturn IOAccelPhxNativeClient::doDbgBootMemory(")[1].split("IOReturn IOAccelPhxNativeClient::doDbgPspLayout(")[0]
        self.assertIn("!owner->debugEnabled()", handler)
        self.assertIn("!privileged", handler)
        self.assertIn("!shape(a, 0, 0, 0, sizeof(PhxBootMemory))", handler)
        self.assertIn("!a->structureOutput", handler)
    def test_firmware_control_authenticates_snapshot_before_writes(self):
        text = (self.stage / "tools/phxctl/phxctl.c").read_text(encoding="utf-8")
        self.assertEqual(1, text.count("IOConnectCallScalarMethod("))
        self.assertEqual(1, text.count("IOConnectCallMethod("))
        stage = text.split("static void stage_firmware(")[1].split("static int open_kext")[0]
        self.assertLess(stage.index("firmware_snapshot("), stage.index("checked_method("))
        self.assertIn("bytes + offset + staged", stage)
        self.assertNotIn("fread", stage)
        main = text.split("int main(int argc, char **argv)")[1]
        self.assertLess(main.index('"verify-file"'), main.index("open_kext()"))
        self.assertIn("if (got <= 0)", text)
        self.assertIn("CC_SHA256(bytes, *file_size, digest)", text)
    def test_psp_failure_is_not_success_or_a_ready_tmr(self):
        body = self.bringup.split("IOReturn PhxBringup::pspRunCmd(")[1].split("// Selector 103:")[0]
        self.assertIn("return observed != fence ? kIOReturnTimeout : kIOReturnError", body)
        self.assertIn("pspSubmissionFaulted = true", body)
        self.assertLess(body.index("wptr > ringSizeDw"), body.index("cmd[i] = 0"))
        self.assertLess(body.index("fenceCounter == UINT32_MAX"), body.index("cmd[i] = 0"))
        self.assertIn("tmrSetUp = r == kIOReturnSuccess", self.bringup)
        clear = self.bringup.split("void PhxBringup::clearRing() {")[1].split("\n}", 1)[0]
        self.assertNotIn("pspSubmissionFaulted", clear)
    def test_mes_submission_checks_bounds_before_touching_packet_or_vram(self):
        text = (self.stage / "tools/phxctl/mesboot.c").read_text(encoding="utf-8")
        submit = text.split("static int mes_submit(")[1].split("#define CMP_RING")[0]
        self.assertLess(submit.index("exit(76)"), submit.index("vw("))
        self.assertLess(submit.index("exit(76)"), submit.index("memcpy("))
        self.assertIn("sch_seq == UINT64_MAX", submit)
        self.assertIn("sch_wptr > SCH_RING_DWORDS - submission_dwords", submit)
        self.assertIn("size - api_status_off", submit)
        self.assertIn("sch_wptr = vr64(SCH_WB + 16)", text)
    def test_mesboot_rejects_missing_gpu_completion_before_later_writes(self):
        text = (self.stage / "tools/phxctl/mesboot.c").read_text(encoding="utf-8")
        submit = text.split("static int mes_submit(")[1].split("#define CMP_RING")[0]
        self.assertIn('gpu_failure("MES completion")', submit)
        self.assertLess(submit.index('gpu_failure("MES completion")'), submit.index("grbm_select(3, 0, 0, 0)"))
        self.assertIn("st != 1", submit)
        self.assertIn("uint64_t f = vr64(SCH_WB + 32), st = vr64(SCH_WB + 64)", submit)
        self.assertIn("memcpy((char *)pkt + api_status_off, status_words, sizeof(status_words))", submit)
        self.assertNotIn("*(uint64_t *)", submit)
        self.assertIn("vw(TESTBUF + 0x40, ~0x6F7A6F7Au)", text)
        for name, adopt in (("compute", 'env_on("ADOPT")'), ("gfx", 'env_on("ADOPT_GFX")')):
            body = text.split(f"static void {name}_via_mes(void)\n{{")[1].split("\n}\n", 1)[0]
            check = f'gpu_failure("{name} execution")'
            self.assertIn(check, body)
            self.assertLess(body.index(check), body.index(adopt))
    def test_mesboot_checks_all_iokit_calls_and_reply_lengths(self):
        text = (self.stage / "tools/phxctl/mesboot.c").read_text(encoding="utf-8")
        self.assertEqual(1, text.count("IOConnectCallScalarMethod("))
        self.assertEqual(1, text.count("IOConnectCallMethod("))
        self.assertIn("if (kr != KERN_SUCCESS || (output_count && *output_count != expected))", text)
        self.assertIn("(output_size && *output_size != expected_size)", text)
        self.assertIn("exit(74)", text)
        self.assertIn("IOObjectRelease(svc)", text)
        self.assertIn("hout[0] != hin[0]", text)
        for header in ("mes_v11_api_def.h", "csb_gfx11.h"):
            self.assertEqual((ROOT / "upstream/nullarc/tools/phxctl" / header).read_bytes(),
                             (self.stage / "tools/phxctl" / header).read_bytes())
    def test_bringup_bounds_are_checked_before_aperture_access(self):
        doorbell = self.bringup.split("IOReturn PhxBringup::doorbellWrite(")[1].split("IOReturn PhxBringup::vramWrite(")[0]
        self.assertIn("phx780m::rangeWithin(byteOff, 8, doorbellMap->getLength())", doorbell)
        self.assertNotIn("byteOff + 8 >", doorbell)
        self.assertLess(doorbell.index("phx780m::rangeWithin"), doorbell.index("getVirtualAddress()"))
        ring = self.bringup.split("IOReturn PhxBringup::pspRing(")[1].split("IOReturn PhxBringup::pspRunCmd(")[0]
        self.assertIn("phxPspLayoutValid(&pspLayout, fbMcBase, fbPhys, fbSize, fbAperLen)", ring)
        self.assertIn("carveOffset != pspLayout.ringOffset", ring)
        self.assertIn("!pspLayoutConfigured", ring)
        self.assertLess(ring.index("phxPspLayoutValid"), ring.index("getVirtualAddress()"))
        for constant in ("PHX_VRAM_TMR_OFF", "PHX_VRAM_TMR_CAP", "PHX_VRAM_FWBUF_OFF"):
            self.assertNotIn(constant, self.bringup)

    def test_explicit_psp_layout_has_no_hardware_or_privilege_bypass(self):
        body = self.bringup.split("IOReturn PhxBringup::configurePspLayout(")[1].split("IOReturn PhxBringup::pspRing(")[0]
        for mutation in ("wreg(", "getVirtualAddress(", "pspRunCmd("):
            self.assertNotIn(mutation, body)
        self.assertIn("ringMc || tmrSetUp || fwBufSize || gpuReady()", body)
        handler = self.bringup.split("IOReturn IOAccelPhxNativeClient::doDbgPspLayout(")[1].split("IOReturn IOAccelPhxNativeClient::doDbgPspRing(")[0]
        self.assertIn("!owner->debugEnabled()", handler)
        self.assertIn("!privileged", handler)
        self.assertIn("shape(a, 0, 4, sizeof(PhxPspLayout), 0)", handler)
        self.assertEqual((ROOT / "src/PhxPspLayout.h").read_bytes(),
                         (self.stage / "src/phxbringup/PhxPspLayout.h").read_bytes())

    def test_toc_size_is_checked_before_tmr_and_engine_loading(self):
        toc = self.bringup.split("IOReturn PhxBringup::loadToc(")[1].split("IOReturn PhxBringup::loadIpFw(")[0]
        self.assertLess(toc.index("pspRunCmd("), toc.index("PHX_PSP_TOC_SIZE_RESPONSE_REL"))
        self.assertIn("if (r == kIOReturnSuccess)", toc)
        self.assertIn("phxPspTmrFits(&pspLayout", toc)
        tmr = self.bringup.split("IOReturn PhxBringup::pspCtl(")[1].split("IOReturn PhxBringup::pspRaw(")[0]
        self.assertIn("size != tocTmrSize", tmr)
        self.assertIn("if (!tocTmrSize)", tmr)
        self.assertIn("if (tmrSetUp)", tmr)
        load = self.bringup.split("IOReturn PhxBringup::loadIpFw(")[1].split("IOReturn PhxBringup::pspCtl(")[0]
        self.assertIn("!ringMc || pspSubmissionFaulted || !tmrSetUp", load)
        handler = self.bringup.split("IOReturn IOAccelPhxNativeClient::doDbgLoadToc(")[1].split("IOReturn IOAccelPhxNativeClient::doDbgPspLayout(")[0]
        self.assertIn("!privileged", handler)
        self.assertIn("!owner->debugEnabled()", handler)
        self.assertIn("a->scalarInput[1] > UINT32_MAX", handler)
    def test_plugin_uses_only_its_own_radv(self):
        text = (self.stage / "src/nmplugin/nvmtl_vk.c").read_text(encoding="utf-8")
        self.assertTrue('phxRuntimeLibraryPath' in text, 'Plugin-relative path helper is not wired')
        self.assertIn('dlopen(icdPath, RTLD_NOW | RTLD_LOCAL)', text)
        self.assertNotIn('NVMTL_LOADER', text)
        self.assertNotIn('NVMTL_ICD_LIB', text)
        self.assertNotIn('VK_ICD_FILENAMES', text)
        self.assertIn('refusing another Vulkan loader', text)
        self.assertEqual((ROOT / "src/PhxRuntimePath.h").read_bytes(),
                         (self.stage / "src/nmplugin/PhxRuntimePath.h").read_bytes())
    def test_plugin_source_and_notice_are_staged(self):
        self.assertTrue((self.stage / "src/nmplugin/NVMTLDevice.m").is_file())
        self.assertTrue((self.stage / "src/nmplugin/nvmtl_vk.c").is_file())
        notice = (self.stage / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Required Notice: Copyright (c) 2026 NullMoth Systems", notice)
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
