# Firmware file inspection, not a firmware loader

`tools/firmware_manifest.py` replaces guessed file slices with hash-locked,
header-derived metadata for the firmware candidates used by the pinned reference
bring-up script. It does not replace that script's initialization sequence, open
IOKit, choose device addresses, reserve memory, send PSP commands or install files.
The selected filenames are reference inputs, not verified ThinkBook GPU IP matches.

## Reviewed sources

- Firmware repository: `https://gitlab.com/kernel-firmware/linux-firmware.git`,
  commit `08624cd0b8ac0fde63c0099efbe043f6ecd74b25`, directory `amdgpu`.
- `firmware.lock.json` pins nine exact file hashes/sizes and their observed header
  and IP versions, plus the `WHENCE` and `LICENSES/LICENSE.amdgpu` hashes.
- Linux v6.18 commit `7d0a66e4bb9081d75c82ec4957c50034cb0ea449`,
  `drivers/gpu/drm/amd/amdgpu/amdgpu_ucode.h`, `amdgpu_ucode.c`, `amdgpu_rlc.c`
  and `amdgpu_psp.c` define the documented header fields and loader offsets.
  The source files retain AMD permissive notices; no Linux source file is bundled
  by this change. The parser implements these format facts independently.
- The AMD firmware license permits binary copying under its notice conditions
  and prohibits reverse engineering, decompilation and disassembly. Only public
  header formats, file extents and hashes were inspected; no instructions were
  decoded or firmware modified. Binary files and the original license remain in
  the ignored local audit directory. This is not approval for public binary
  releases; the broader project license/provenance audit remains open.

## Offline use

Using already obtained, unmodified files corresponding to the lock:

```sh
python3 tools/firmware_manifest.py --root /path/to/local/amdgpu \
  --lock firmware.lock.json --out local/firmware-check-01/firmware-manifest.json
```

This command has no network operation and requires no privileges or GPU access.
Use a fresh output filename. A missing/changed file, unsupported header, invalid
extent or overlapping component fails the entire inspection before writing a
success report. The input directory may contain unrelated files, which are not
read. The output omits local input paths and contains no payload bytes.

The lock must be reviewed together with its source commit. Replacing its hashes
with hashes of arbitrary inputs is not provenance verification. The canonical
JSON lock digest in the report identifies the supplied profile; it is not a
vendor signature.

## Layout semantics

- Common fields are little-endian. Total/header/payload lengths, dword alignment
  and all component ranges are checked against the actual bounded file.
- MES instructions/data use their explicit offsets. SDMA context uses the common
  payload offset; its control thread uses the type-specific offset.
- IMU data follows the instruction section, matching the Linux loader. GFX v2
  instructions use the common payload offset, not an assumed interpretation of
  every field whose name contains `offset`.
- GFX v1 jump-table sizes/offsets are in **dwords**. MEC instructions exclude the
  jump table. PFP/ME retain their combined payload and describe the jump table as
  nested metadata, not a second independent load request.
- RLC v2.3 handles the main ucode, restore lists, IRAM/DRAM and RLCP/RLCV. Zero-size
  optional components are explicitly recorded as absent. TOC uses the common
  payload as `psp_init_toc_microcode` does, not generic PSP SOS-descriptor rules.
- The reported CRC and a zlib CRC observation are retained separately. The
  vendor CRC convention has **not** been established; these fields must not be
  treated as an authenticated checksum pass. Exact SHA-256 matching is mandatory.

## Observed validation and remaining integration

On 2026-10-31, all nine pinned official files passed this local parser. All 17
explicit `L` file extents in reference `bringup5.sh` and its separate TOC extent
match the header-derived ranges. For example, MEC has a 267,904-byte common
payload containing 267,008 bytes of instructions and an 896-byte jump table.
This explains the script's smaller MEC length; it is not an outdated-size bug.
The evidence contains metadata only: `validation/firmware-08624cd.json`.

Fifteen synthetic tests additionally exercise malformed hashes/lengths, version
mismatches, overlap, dword conversion, missing optional components, path/name
rejection and output overwrite/failure handling. They do not execute firmware.

Neither file parsing nor matching reference slices verifies firmware signatures,
PSP command IDs/order, target IP discovery, device-memory placement, exclusive
ownership or successful hardware boot. The MEC jump-table record alone is not
permission to add a load command. A checked loader, target layout, firmware/PSP
response handling and actual GPU output are still required. Every report keeps
`firmware_loaded`, `hardware_executed` and `safe_to_initialize` false.
