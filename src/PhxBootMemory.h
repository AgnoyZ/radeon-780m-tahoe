/* Read-only bootstrap metadata. Reported ranges are not ownership grants. */
#ifndef PHX_BOOT_MEMORY_H
#define PHX_BOOT_MEMORY_H
#include "PhxPspLayout.h"
#define PHX_BOOT_MEMORY_VERSION 1ull
#define PHX_BOOT_MEMORY_SELECTOR 116u
#define PHX_BOOT_LAYOUT_CONFIGURED 1ull
#define PHX_BOOT_RING_ACTIVE 2ull
#define PHX_BOOT_TMR_ACTIVE 4ull
#define PHX_BOOT_GPU_ACTIVE 8ull
#define PHX_BOOT_PSP_FAULTED 16ull
struct PhxBootMemory {
    uint64_t version, flags, mcBase, physicalBase, vramBytes, apertureBytes;
    uint64_t tmrBytes, reserved;
    struct PhxPspLayout psp;
};
#if defined(__cplusplus)
static_assert(sizeof(PhxBootMemory) == 128, "Bootstrap memory wire size");
#else
_Static_assert(sizeof(struct PhxBootMemory) == 128, "Bootstrap memory wire size");
#endif
#endif
