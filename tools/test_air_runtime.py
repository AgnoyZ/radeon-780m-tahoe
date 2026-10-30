"""Exercise LLVM bitcode reading and Metal-source -> AIR -> SPIR-V, without a GPU."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from test_translator_runtime import spirv_instructions

LIMIT = 16 * 1024 * 1024
DIAGNOSTIC = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


def llvm_exports(plugin_source):
    text = Path(plugin_source).read_text(encoding="utf-8")
    required = set(re.findall(r"NV_LLVM_LOAD\((LLVM\w+)\)", text))
    if not {"LLVMParseBitcodeInContext2", "LLVMPrintModuleToString"}.issubset(required):
        raise ValueError("Missing pinned plugin LLVM contract")
    return required | set(re.findall(r'"(LLVM\w+)"', text))


class Reader:
    def __init__(self, library, plugin_source):
        self.lib = C.CDLL(str(Path(library).resolve()))
        self.exports = sorted(llvm_exports(plugin_source))
        for name in self.exports:
            getattr(self.lib, name)
        pointer, count = C.c_void_p, C.c_size_t
        signatures = {
            "LLVMContextCreate": (pointer, []),
            "LLVMContextDispose": (None, [pointer]),
            "LLVMContextSetDiagnosticHandler": (None, [pointer, DIAGNOSTIC, pointer]),
            "LLVMCreateMemoryBufferWithMemoryRangeCopy": (pointer, [C.c_char_p, count, C.c_char_p]),
            "LLVMDisposeMemoryBuffer": (None, [pointer]),
            "LLVMParseBitcodeInContext2": (C.c_int, [pointer, pointer, C.POINTER(pointer)]),
            "LLVMParseIRInContext": (C.c_int, [pointer, pointer, C.POINTER(pointer), C.POINTER(pointer)]),
            "LLVMWriteBitcodeToMemoryBuffer": (pointer, [pointer]),
            "LLVMGetBufferStart": (pointer, [pointer]),
            "LLVMGetBufferSize": (count, [pointer]),
            "LLVMPrintModuleToString": (pointer, [pointer]),
            "LLVMDisposeModule": (None, [pointer]),
            "LLVMDisposeMessage": (None, [pointer]),
            "LLVMGetDiagInfoSeverity": (C.c_int, [pointer]),
            "LLVMGetDiagInfoDescription": (pointer, [pointer]),
            "LLVMGetVersion": (None, [C.POINTER(C.c_uint)] * 3),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args
        major, minor, patch = C.c_uint(), C.c_uint(), C.c_uint()
        self.lib.LLVMGetVersion(C.byref(major), C.byref(minor), C.byref(patch))
        self.version = (major.value, minor.value, patch.value)
        if self.version != (21, 1, 8):
            raise RuntimeError(f"Unexpected LLVM runtime version: {self.version}")

    def context(self):
        context, errors = self.lib.LLVMContextCreate(), []
        if not context:
            raise RuntimeError("LLVM context allocation failed")
        @DIAGNOSTIC
        def diagnostic(info, _):
            message = self.lib.LLVMGetDiagInfoDescription(info)
            try:
                if self.lib.LLVMGetDiagInfoSeverity(info) == 0:
                    errors.append(C.string_at(message).decode("utf-8", errors="replace") if message else "LLVM error")
            finally:
                if message:
                    self.lib.LLVMDisposeMessage(message)
        self.lib.LLVMContextSetDiagnosticHandler(context, diagnostic, None)
        return context, errors, diagnostic

    def bitcode(self, ir):
        context, errors, callback = self.context()
        module, message = C.c_void_p(), C.c_void_p()
        output = None
        try:
            buffer = self.lib.LLVMCreateMemoryBufferWithMemoryRangeCopy(ir, len(ir), b"project-fixture")
            if not buffer:
                raise RuntimeError("LLVM memory buffer allocation failed")
            # LLVMParseIRInContext takes ownership of this memory buffer.
            result = self.lib.LLVMParseIRInContext(context, buffer, C.byref(module), C.byref(message))
            if result or not module or errors:
                raise RuntimeError("LLVM could not parse the project IR fixture")
            output = self.lib.LLVMWriteBitcodeToMemoryBuffer(module)
            if not output:
                raise RuntimeError("LLVM bitcode writer failed")
            size = self.lib.LLVMGetBufferSize(output)
            if size < 4 or size > LIMIT:
                raise RuntimeError("Implausible LLVM bitcode length")
            return C.string_at(self.lib.LLVMGetBufferStart(output), size)
        finally:
            if output:
                self.lib.LLVMDisposeMemoryBuffer(output)
            if message:
                self.lib.LLVMDisposeMessage(message)
            if module:
                self.lib.LLVMDisposeModule(module)
            self.lib.LLVMContextDispose(context)

    def read(self, data):
        if not 4 <= len(data) <= LIMIT:
            raise ValueError("AIR bitcode length outside test bound")
        context, errors, callback = self.context()
        module, text = C.c_void_p(), None
        buffer = self.lib.LLVMCreateMemoryBufferWithMemoryRangeCopy(data, len(data), b"air-input")
        try:
            if not buffer:
                raise RuntimeError("LLVM memory buffer allocation failed")
            result = self.lib.LLVMParseBitcodeInContext2(context, buffer, C.byref(module))
            if result or not module or errors:
                raise ValueError("LLVM rejected AIR bitcode: " + "; ".join(errors))
            text = self.lib.LLVMPrintModuleToString(module)
            if not text:
                raise RuntimeError("LLVM module printing failed")
            ir = C.string_at(text)
            if len(ir) > LIMIT or b"!air.kernel" not in ir:
                raise RuntimeError("AIR reader output lacks kernel metadata or exceeds test bound")
            return ir
        finally:
            if text:
                self.lib.LLVMDisposeMessage(text)
            if module:
                self.lib.LLVMDisposeModule(module)
            if buffer:
                self.lib.LLVMDisposeMemoryBuffer(buffer)
            self.lib.LLVMContextDispose(context)


def translate(library, ir):
    lib = C.CDLL(str(Path(library).resolve()))
    pointer = C.POINTER(C.c_uint8)
    lib.nvmtl_translate.argtypes = [C.c_char_p, C.c_char_p, C.POINTER(pointer), C.POINTER(C.c_size_t), C.c_void_p, C.c_size_t]
    lib.nvmtl_translate.restype = C.c_int
    lib.nvmtl_translate_free.argtypes = [pointer, C.c_size_t]
    lib.nvmtl_translate_free.restype = None
    output, size, message = pointer(), C.c_size_t(), C.create_string_buffer(4096)
    result = lib.nvmtl_translate(ir, b"kernel", C.byref(output), C.byref(size), message, len(message))
    try:
        if result or not output or not 20 <= size.value <= LIMIT:
            raise RuntimeError("AIR translation failed: " + message.value.decode("utf-8", errors="replace"))
        data = C.string_at(output, size.value)
    finally:
        if output:
            lib.nvmtl_translate_free(output, size.value)
    instructions = spirv_instructions(data)
    if not {62, 128}.issubset({op for op, _ in instructions}):
        raise RuntimeError("Generated shader lost integer addition or buffer store")
    if not any(op == 15 and args and args[0] == 5 for op, args in instructions):
        raise RuntimeError("Generated shader lacks a GLCompute entrypoint")
    return data


def exercise(llvm, translator, plugin_source, ir_fixture, metal_fixture, validator, out):
    out = Path(out).resolve()
    if out.exists():
        raise RuntimeError("AIR runtime test output exists; choose a fresh path")
    out.mkdir(parents=True)
    reader = Reader(llvm, plugin_source)
    try:
        reader.read(b"not valid bitcode!")
    except ValueError:
        pass
    else:
        raise RuntimeError("LLVM accepted malformed bitcode")
    bitcode = reader.bitcode(Path(ir_fixture).read_bytes())
    (out / "project-fixture.bc").write_bytes(bitcode)
    cases = [("llvm_roundtrip", bitcode)]
    compiler = subprocess.check_output(["xcrun", "-sdk", "macosx", "metal", "--version"], text=True, timeout=30).strip()
    for value in (17, 29):
        path = out / f"metal{value}.air"
        subprocess.run(["xcrun", "-sdk", "macosx", "metal", "-std=macos-metal3.1", "-c",
                        str(Path(metal_fixture).resolve()), f"-DADD_VALUE={value}", "-o", str(path)], check=True, timeout=60)
        cases.append((f"apple_metal{value}", path.read_bytes()))
    reports = []
    for name, data in cases:
        ir = reader.read(data)
        (out / (name + ".ll")).write_bytes(ir)
        spirv = translate(translator, ir)
        path = out / (name + ".spv")
        path.write_bytes(spirv)
        subprocess.run([str(validator), "--target-env", "vulkan1.2", str(path)], check=True, timeout=30)
        reports.append({"case": name, "bitcode_sha256": hashlib.sha256(data).hexdigest(),
                        "spirv_bytes": len(spirv), "spirv_sha256": hashlib.sha256(spirv).hexdigest(), "spirv_val": "passed"})
    if reports[1]["spirv_sha256"] == reports[2]["spirv_sha256"]:
        raise RuntimeError("Changing real Metal-source arithmetic did not change SPIR-V")
    report = {"llvm_version": list(reader.version), "exports_present": reader.exports, "malformed_bitcode_rejected": True,
              "llvm_sha256": hashlib.sha256(Path(llvm).read_bytes()).hexdigest(),
              "translator_sha256": hashlib.sha256(Path(translator).read_bytes()).hexdigest(),
              "cases": reports, "metal_compiler": compiler, "hardware_executed": False,
              "full_plugin_pipeline_tested": False,
              "limitation": "Host compilation/reading/translation only; not GPU execution or full Metal plugin integration"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("llvm", "translator", "plugin-source", "ir-fixture", "metal-fixture", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--validator", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        exercise(args.llvm, args.translator, args.plugin_source, args.ir_fixture, args.metal_fixture, args.validator, args.out)
    else:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"], check=True, timeout=240)
