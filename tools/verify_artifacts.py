"""Structural binary checks only; these do not prove kernel loadability or GPU acceleration."""
import hashlib
from pathlib import Path
import plistlib
import struct

def inspect_macho(path, expected_type):
    data = Path(path).read_bytes()
    if len(data) < 32:
        raise ValueError("Truncated Mach-O header")
    magic, cpu, subtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF or cpu != 0x01000007 or filetype != expected_type:
        raise ValueError("Expected a thin x86_64 Mach-O of the requested type")
    end = 32 + sizeofcmds
    if ncmds == 0 or end > len(data):
        raise ValueError("Invalid load-command table")
    offset = 32
    has_text = False
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError("Truncated load command")
        cmd, size = struct.unpack_from("<II", data, offset)
        if size < 8 or size % 8 or offset + size > end:
            raise ValueError("Invalid load-command size")
        if cmd == 0x19:
            if size < 72:
                raise ValueError("Truncated segment command")
            name = data[offset + 8:offset + 24].rstrip(b"\0")
            fileoff, filesize = struct.unpack_from("<QQ", data, offset + 40)
            if fileoff > len(data) or filesize > len(data) - fileoff:
                raise ValueError("Segment extends beyond file")
            has_text |= name == b"__TEXT" and filesize > 0
        offset += size
    if offset != end or not has_text:
        raise ValueError("Invalid command table or missing executable text segment")
    return {"architecture": "x86_64", "macho_type": filetype,
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

def inspect_kext(bundle, expected_identifier):
    bundle = Path(bundle)
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    if info.get("CFBundlePackageType") != "KEXT" or info.get("CFBundleIdentifier") != expected_identifier:
        raise ValueError("Unexpected kext identity")
    executable = info.get("CFBundleExecutable", "")
    if not executable or Path(executable).name != executable or "/" in executable or "\\" in executable:
        raise ValueError("Invalid executable path")
    result = inspect_macho(bundle / "Contents/MacOS" / executable, 11)
    result["bundle_identifier"] = expected_identifier
    return result
