import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from translator_source import prepare_translator, validate_archive
from test_translator_runtime import spirv_instructions, required_translator_exports


class TranslatorSourceTests(unittest.TestCase):
    def test_rejects_wrong_hash_before_extraction(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_archive(b"untrusted", "0" * 64)

    def test_accepts_matching_bytes(self):
        data = b"source"
        validate_archive(data, hashlib.sha256(data).hexdigest())

    def test_refuses_existing_staging_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            archive = path / "input.tar.gz"
            archive.write_bytes(b"test")
            lock = {"sha256": hashlib.sha256(b"test").hexdigest(), "archive_root": "source"}
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                prepare_translator(archive, path, lock)

    def test_rejects_bad_source_layout(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            member = tarfile.TarInfo("source/NOTICE")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            archive = path / "source.tar.gz"
            archive.write_bytes(data.getvalue())
            lock = {"sha256": hashlib.sha256(data.getvalue()).hexdigest(), "archive_root": "source"}
            with self.assertRaisesRegex(RuntimeError, "Missing translator source"):
                prepare_translator(archive, path / "staged", lock)

    def test_plugin_contract_has_translate_and_free(self):
        names = required_translator_exports(ROOT / "upstream/nullarc/src/nmplugin/NVMTLLibraryLoad.m")
        self.assertIn("nvmtl_translate", names)
        self.assertIn("nvmtl_translate_free", names)
        self.assertEqual(16, len(names))


class SpirvEnvelopeTests(unittest.TestCase):
    def test_rejects_truncated_or_invalid_magic(self):
        for data in (b"", bytes(20), b"\x03\x02\x23\x07" + bytes(17)):
            with self.assertRaises(ValueError): spirv_instructions(data)

    def test_rejects_zero_word_count(self):
        import struct
        data = struct.pack("<6I", 0x07230203, 0x10000, 0, 1, 0, 0)
        with self.assertRaisesRegex(ValueError, "instruction"):
            spirv_instructions(data)


if __name__ == "__main__":
    unittest.main()
