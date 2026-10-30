# Downstream source

PhxHardwarePolicy.hpp is compiled into the patched PhxBringup and PhxAccel builds. The complete upstream source is pinned in upstream/nullarc; patches are applied to a separate build staging directory, never to the source submodule or the installed EFI.

This is not a standalone complete graphics driver. See docs/BUILD.md and docs/IMPLEMENTATION-STATUS.md for dependencies, tests, and missing runtime integration.
