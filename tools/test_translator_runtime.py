"""Execute the translator C ABI and external SPIR-V validation, without a GPU."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def required_translator_exports(plugin_source):
    text = Path(plugin_source).read_text(encoding="utf-8")
    names = set(re.findall(r'dlsym\(h,\s*"(nvmtl_[^"]+)"', text))
    if not {"nvmtl_translate", "nvmtl_translate_free"}.issubset(names):
        raise ValueError("Cannot find the pinned plugin's translator ABI contract")
    return names


def spirv_instructions(data):
    if len(data) < 20 or len(data) % 4:
        raise ValueError("Invalid SPIR-V byte size")
    words = struct.unpack("<" + "I" * (len(data) // 4), data)
    if words[0] != 0x07230203 or words[3] == 0 or words[4] != 0:
        raise ValueError("Invalid SPIR-V header")
    result = []
    offset = 5
    while offset < len(words):
        count, opcode = words[offset] >> 16, words[offset] & 0xFFFF
        if not count or count > len(words) - offset:
            raise ValueError("Invalid SPIR-V instruction boundary")
        result.append((opcode, words[offset + 1:offset + count]))
        offset += count
    return result


def exercise(library, plugin_source, fixture, validator, output):
    output = Path(output)
    if output.exists():
        raise RuntimeError("Translator test output already exists; choose a fresh directory")
    output.mkdir(parents=True)
    lib = ctypes.CDLL(str(Path(library).resolve()))
    required = required_translator_exports(plugin_source)
    for name in required:
        getattr(lib, name)
    byte_pointer = ctypes.POINTER(ctypes.c_uint8)
    translate = lib.nvmtl_translate
    translate.restype = ctypes.c_int
    translate.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(byte_pointer),
                          ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    release = lib.nvmtl_translate_free
    release.restype = None
    release.argtypes = [byte_pointer, ctypes.c_size_t]

    def invoke(text, stage):
        pointer, size = byte_pointer(), ctypes.c_size_t()
        error = ctypes.create_string_buffer(4096)
        code = translate(text, stage, ctypes.byref(pointer), ctypes.byref(size), error, len(error))
        if size.value > 16 * 1024 * 1024 or (size.value and not pointer):
            raise RuntimeError("Implausible translator output pointer/length")
        try:
            data = ctypes.string_at(pointer, size.value) if pointer else b""
        finally:
            if pointer:
                release(pointer, size.value)
        return code, data, error.value.decode("utf-8", errors="replace")

    fixture_data = Path(fixture).read_bytes()
    for text, stage in ((fixture_data, b"invalid-stage"), (b"this is not LLVM IR", b"kernel")):
        code, data, error = invoke(text, stage)
        if code == 0 or data or not error:
            raise RuntimeError("Translator did not reject invalid input through its real ABI")
    version = subprocess.check_output([str(validator), "--version"], text=True, timeout=30).strip()
    reports = []
    for label, text in (("increment17", fixture_data), ("increment29", fixture_data.replace(b"%index, 17", b"%index, 29"))):
        code, data, error = invoke(text, b"kernel")
        if code != 0:
            raise RuntimeError("Real AIR translation failed: " + error)
        instructions = spirv_instructions(data)
        opcodes = {op for op, _ in instructions}
        if not {62, 128}.issubset(opcodes):
            raise RuntimeError("Translated compute kernel lost the store or integer-add operation")
        if not any(op == 15 and args and args[0] == 5 for op, args in instructions):
            raise RuntimeError("Translated kernel has no GLCompute entrypoint")
        path = output / (label + ".spv")
        path.write_bytes(data)
        subprocess.run([str(validator), "--target-env", "vulkan1.2", str(path)], check=True, timeout=30)
        reports.append({"case": label, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "spirv_val": "passed"})
    if reports[0]["sha256"] == reports[1]["sha256"]:
        raise RuntimeError("Changing the input arithmetic did not change the generated SPIR-V")
    report = {"real_ffi_loaded": True, "exports_present": sorted(required), "invalid_inputs_rejected": 2,
              "cases": reports, "validator_version": version, "hardware_executed": False,
              "limitation": "Translation/validation only; no GPU execution or Metal pipeline integration"}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--plugin-source", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--validator", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    exercise(args.library, args.plugin_source, args.fixture, args.validator, args.out)
