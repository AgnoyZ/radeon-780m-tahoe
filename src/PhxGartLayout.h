/* Bootstrap GART arithmetic contract; no allocation or target compatibility claim. */
#ifndef PHX_GART_LAYOUT_H
#define PHX_GART_LAYOUT_H
#include "PhxBootMemory.h"
#define PHX_GART_LAYOUT_VERSION 1ull
#define PHX_GART_MAX_MAPPED_BYTES 0x8000000ull
#define PHX_GART_ADDRESS_LIMIT 0x1000000000000ull
struct PhxGartLayout {
    uint64_t version, virtualBase, mappedBytes, tableOffset, defaultPageOffset;
};
static inline uint64_t phxGartTableBytes(const struct PhxGartLayout *layout) {
    return (((layout->mappedBytes >> 12) * 8) + 4095) & ~4095ull;
}
static inline int phxGartInputsValid(const struct PhxGartLayout *layout) {
    return layout && layout->version == PHX_GART_LAYOUT_VERSION &&
        !((layout->virtualBase | layout->mappedBytes | layout->tableOffset | layout->defaultPageOffset) & 4095) &&
        layout->mappedBytes <= PHX_GART_MAX_MAPPED_BYTES &&
        phxPspSpanFits(layout->virtualBase, layout->mappedBytes, PHX_GART_ADDRESS_LIMIT);
}
static inline int phxGartLayoutValid(const struct PhxGartLayout *layout, const struct PhxBootMemory *memory) {
    if (!phxGartInputsValid(layout) || !memory ||
        memory->version != PHX_BOOT_MEMORY_VERSION || memory->reserved ||
        ((memory->mcBase | memory->vramBytes) & 0x3ffffull) ||
        memory->flags != (PHX_BOOT_LAYOUT_CONFIGURED | PHX_BOOT_RING_ACTIVE | PHX_BOOT_TMR_ACTIVE) ||
        !memory->tmrBytes || memory->tmrBytes > UINT32_MAX ||
        !phxPspLayoutValid(&memory->psp, memory->mcBase, memory->physicalBase, memory->vramBytes, memory->apertureBytes) ||
        !phxPspTmrFits(&memory->psp, memory->mcBase, memory->physicalBase, (uint32_t)memory->tmrBytes)) return 0;
    if (((layout->virtualBase | layout->mappedBytes | layout->tableOffset | layout->defaultPageOffset) & 4095) ||
        layout->mappedBytes > PHX_GART_MAX_MAPPED_BYTES || layout->mappedBytes > memory->vramBytes ||
        !phxPspSpanFits(layout->virtualBase, layout->mappedBytes, PHX_GART_ADDRESS_LIMIT) ||
        !phxPspSpanFits(memory->mcBase, memory->vramBytes, PHX_GART_ADDRESS_LIMIT) ||
        !phxPspSpanFits(memory->physicalBase, memory->vramBytes, PHX_GART_ADDRESS_LIMIT) ||
        !phxPspDisjoint(layout->virtualBase, layout->mappedBytes, memory->mcBase, memory->vramBytes)) return 0;
    uint64_t limit = memory->vramBytes < memory->apertureBytes ? memory->vramBytes : memory->apertureBytes;
    if (limit > 0x100000000ull) limit = 0x100000000ull; /* Existing dword write selector uses 32-bit offsets. */
    const uint64_t tableBytes = phxGartTableBytes(layout);
    if (!phxPspSpanFits(layout->tableOffset, tableBytes, limit) ||
        !phxPspSpanFits(layout->defaultPageOffset, 4096, limit) ||
        !phxPspDisjoint(layout->tableOffset, tableBytes, layout->defaultPageOffset, 4096)) return 0;
    const uint64_t reservedOffsets[3] = {memory->psp.ringOffset, memory->psp.tmrOffset, memory->psp.stagingOffset};
    const uint64_t reservedBytes[3] = {PHX_PSP_LAYOUT_RING_BYTES, memory->psp.tmrCapacity, memory->psp.stagingCapacity};
    for (unsigned i = 0; i < 3; ++i)
        if (!phxPspDisjoint(layout->tableOffset, tableBytes, reservedOffsets[i], reservedBytes[i]) ||
            !phxPspDisjoint(layout->defaultPageOffset, 4096, reservedOffsets[i], reservedBytes[i])) return 0;
    return 1;
}
#endif
