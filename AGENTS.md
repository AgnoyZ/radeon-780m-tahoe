# Project instructions

- Target Radeon 780M on macOS Tahoe; record the actual OS build after migration. Do not claim Tahoe is already installed.
- The owner authorized public visibility on 2026-10-30. Keep this repository public unless the owner requests otherwise. Never commit credentials, serials, UUIDs, ROM values, raw IORegistry/ACPI/firmware dumps, diagnostic archives, photos, personal EFI configurations or OS images.
- Preserve the working EFI in its separate repository. Do not auto-deploy drivers, alter internal Windows EFI, partition disks, reset NVRAM, change BIOS or weaken OS security as part of repository work.
- This is an experimental patched-source project, not a hardware-validated working driver. Label untested changes and require real GPU execution evidence for acceleration claims.
- Audit each upstream component and its license before copying code or binaries. Do not assume all components share one license.
- Keep experiments isolated, change one variable per test, and document rollback.
- After every coherent change: update relevant docs, run available checks and git diff --check, review privacy and the staged diff, commit, push, and verify the remote SHA.
- A local commit alone is not synchronized. Report push failures honestly. Never force-push, change visibility, rewrite history or overwrite unrelated work without explicit permission.
- Do not use Hindsight. Do not spawn subagents unless the user explicitly requests them.

- Public repository CI must not upload experimental binaries until the upstream license/provenance audit is resolved and publication is explicitly approved. Keep raw logs and local caches ignored.
