"""Inspect pinned local AMD firmware files; never download, stage or load firmware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import zlib

MAX_BYTES = 16 * 1024 * 1024
COMMON = struct.Struct("<IIHHHHIIII")
LINUX_COMMIT = "7d0a66e4bb9081d75c82ec4957c50034cb0ea449"


class FirmwareError(ValueError):
    pass


def inspect_firmware(data, expected):
    if not isinstance(data, bytes) or not COMMON.size <= len(data) <= MAX_BYTES:
        raise FirmwareError("Firmware size is outside the inspection limit")
    digest = hashlib.sha256(data).hexdigest()
    wanted_hash = expected.get("sha256") if isinstance(expected, dict) else None
    if not isinstance(wanted_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", wanted_hash) or digest != wanted_hash:
        raise FirmwareError("Firmware does not match the reviewed source hash")
    if "size_bytes" in expected and (type(expected["size_bytes"]) is not int or expected["size_bytes"] != len(data)):
        raise FirmwareError("Firmware does not match the reviewed file size")
    total, header_size, major, minor, ip_major, ip_minor, version, payload_size, payload_offset, crc = COMMON.unpack_from(data)
    if total != len(data) or not COMMON.size <= header_size <= total:
        raise FirmwareError("Invalid firmware total or header size")
    if [major, minor] != expected.get("header_version") or [ip_major, ip_minor] != expected.get("ip_version"):
        raise FirmwareError("Firmware header or IP version differs from the reviewed profile")

    def extent(offset, size):
        if offset < header_size or offset % 4 or size <= 0 or size % 4 or offset > total or size > total - offset:
            raise FirmwareError("Firmware payload extent is invalid")

    def word(offset):
        if offset > header_size - 4:
            raise FirmwareError("Firmware type header is truncated")
        return struct.unpack_from("<I", data, offset)[0]

    extent(payload_offset, payload_size)
    regions, absent, jump_table, mes_start = [], [], None, None

    def region(name, offset, size):
        extent(offset, size)
        for previous in regions:
            if offset < previous["file_offset"] + previous["size_bytes"] and previous["file_offset"] < offset + size:
                raise FirmwareError("Firmware component ranges overlap")
        regions.append({"component": name, "file_offset": offset, "size_bytes": size,
                        "sha256": hashlib.sha256(data[offset:offset + size]).hexdigest()})

    kind = expected.get("kind")
    if kind == "mes" and (major, minor) == (1, 0):
        word(68)
        region("instruction", word(40), word(36))
        region("data", word(52), word(48))
        mes_start = word(56) | (word(60) << 32)
        if not mes_start or mes_start & 3:
            raise FirmwareError("MES instruction start must be nonzero and dword aligned")
    elif kind == "sdma" and (major, minor) == (2, 0):
        word(60)
        region("context", payload_offset, word(36))
        region("control", word(48), word(52))
    elif kind == "imu" and (major, minor) == (1, 0):
        word(44)
        region("instruction", payload_offset, word(32))
        region("data", payload_offset + word(32), word(40))
    elif kind == "gfx" and (major, minor) == (2, 0):
        word(56)
        region("instruction", payload_offset, word(36))
        region("data", word(48), word(44))
    elif kind in ("gfx", "gfx-mec") and (major, minor) == (1, 0):
        jt_offset, jt_size = word(36) * 4, word(40) * 4
        if jt_offset > payload_size or jt_size > payload_size - jt_offset:
            raise FirmwareError("Graphics jump table leaves the common payload")
        if jt_size:
            jump_table = {"file_offset": payload_offset + jt_offset, "size_bytes": jt_size,
                          "sha256": hashlib.sha256(data[payload_offset + jt_offset:payload_offset + jt_offset + jt_size]).hexdigest()}
        if kind == "gfx-mec":
            if not jt_size:
                raise FirmwareError("Reviewed MEC profile requires a jump table")
            region("instruction", payload_offset, payload_size - jt_size)
            region("jump_table", payload_offset + jt_offset, jt_size)
        else:
            region("ucode", payload_offset, payload_size)
    elif kind == "psp-toc" and (major, minor) == (1, 0):
        word(40)
        region("toc", payload_offset, payload_size)
    elif kind == "rlc" and (major, minor) == (2, 3):
        word(200)
        region("ucode", payload_offset, payload_size)
        for name, size_field, offset_field in (("restore_cntl", 116, 120), ("restore_gpm", 132, 136),
                                                ("restore_srm", 148, 152), ("iram", 156, 160),
                                                ("dram", 164, 168), ("rlcp", 180, 184), ("rlcv", 196, 200)):
            if word(size_field):
                region(name, word(offset_field), word(size_field))
            else:
                absent.append(name)
    else:
        raise FirmwareError("Firmware component layout is not implemented for this profile")
    return {"sha256": digest, "size_bytes": total, "header_size_bytes": header_size,
            "header_version": [major, minor], "ip_version": [ip_major, ip_minor], "ucode_version": version,
            "common_payload": {"file_offset": payload_offset, "size_bytes": payload_size},
            "crc32_reported": f"{crc:08x}",
            "crc32_zlib_common_payload": f"{zlib.crc32(data[payload_offset:payload_offset + payload_size]):08x}",
            "crc32_convention_verified": False, "components": regions, "jump_table": jump_table,
            "absent_optional_components": absent, "mes_instruction_start": mes_start,
            "vendor_signature_verified": False, "target_compatibility_verified": False}


def inspect_directory(root, lock):
    root = Path(root).resolve(strict=True)
    if not isinstance(lock, dict) or type(lock.get("schema_version")) is not int or lock["schema_version"] != 1 or not isinstance(lock.get("files"), list):
        raise FirmwareError("Invalid firmware lock schema")
    if not 1 <= len(lock["files"]) <= 32:
        raise FirmwareError("Invalid firmware lock entry count")
    files = []
    seen = set()
    for entry in lock["files"]:
        if not isinstance(entry, dict):
            raise FirmwareError("Invalid firmware lock entry")
        name = entry.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]+\.bin", name) or name in seen:
            raise FirmwareError("Invalid or duplicate firmware filename")
        seen.add(name)
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root):
            raise FirmwareError("Firmware file leaves the specified directory")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        files.append({"name": name, "kind": entry.get("kind"), **inspect_firmware(data, entry)})
    return {"schema_version": 1, "linux_parser_reference_commit": LINUX_COMMIT,
            "lock_sha256": hashlib.sha256(json.dumps(lock, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "files": files, "hardware_executed": False, "firmware_loaded": False,
            "safe_to_initialize": False,
            "limitations": ["File offsets are not device addresses or allocation/ownership grants.",
                            "Matching a source hash does not verify a vendor signature or target IP compatibility.",
                            "This report does not authorize firmware loading or replace a target memory-layout audit."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise FirmwareError("Report exists; choose a new output path")
        with args.lock.open("rb") as stream:
            raw_lock = stream.read(256 * 1024 + 1)
        if len(raw_lock) > 256 * 1024:
            raise FirmwareError("Firmware lock exceeds the inspection limit")
        report = inspect_directory(args.root, json.loads(raw_lock))
        args.out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    except (FirmwareError, OSError, ValueError) as error:
        parser.exit(1, "Firmware inspection failed: " + str(error) + "\n")
    print("Local firmware metadata written; no firmware was staged or loaded.")


if __name__ == "__main__":
    main()
