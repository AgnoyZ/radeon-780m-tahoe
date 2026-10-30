/* Numeric PSP layout contract. Valid ranges do not establish memory ownership. */
#ifndef PHX_780M_PSP_LAYOUT_H
#define PHX_780M_PSP_LAYOUT_H
#include <stdint.h>

#define PHX_PSP_LAYOUT_VERSION 1ull
#define PHX_PSP_LAYOUT_RING_BYTES 0x9000ull
#define PHX_PSP_STAGING_MAX_BYTES 0x1000000ull
#define PHX_PSP_LAYOUT_SELECTOR 114u

struct PhxPspLayout {
    uint64_t version;
    uint64_t ringOffset;
    uint64_t tmrOffset;
    uint64_t tmrCapacity;
    uint64_t stagingOffset;
    uint64_t stagingCapacity;
    uint64_t reserved[2];
};

static inline int phxPspSpanFits(uint64_t offset, uint64_t bytes, uint64_t limit) {
    return bytes && offset <= limit && bytes <= limit - offset;
}

static inline int phxPspDisjoint(uint64_t a, uint64_t aBytes, uint64_t b, uint64_t bBytes) {
    return a <= b ? aBytes <= b - a : bBytes <= a - b;
}

static inline int phxPspLayoutValid(const struct PhxPspLayout *layout, uint64_t mcBase,
                                  uint64_t physicalBase, uint64_t vramBytes, uint64_t apertureBytes) {
    if (!layout || layout->version != PHX_PSP_LAYOUT_VERSION || layout->reserved[0] || layout->reserved[1] ||
        !mcBase || !physicalBase || !vramBytes || !apertureBytes ||
        (mcBase & 0xfffull) || (physicalBase & 0xfffull) ||
        vramBytes - 1 > UINT64_MAX - mcBase || vramBytes - 1 > UINT64_MAX - physicalBase)
        return 0;
    if ((layout->ringOffset | layout->tmrOffset | layout->tmrCapacity |
         layout->stagingOffset | layout->stagingCapacity) & 0xfffull)
        return 0;
    if (layout->tmrCapacity > UINT32_MAX || layout->stagingCapacity > PHX_PSP_STAGING_MAX_BYTES)
        return 0;
    const uint64_t limit = vramBytes < apertureBytes ? vramBytes : apertureBytes;
    if (!phxPspSpanFits(layout->ringOffset, PHX_PSP_LAYOUT_RING_BYTES, limit) ||
        !phxPspSpanFits(layout->tmrOffset, layout->tmrCapacity, limit) ||
        !phxPspSpanFits(layout->stagingOffset, layout->stagingCapacity, limit))
        return 0;
    return phxPspDisjoint(layout->ringOffset, PHX_PSP_LAYOUT_RING_BYTES, layout->tmrOffset, layout->tmrCapacity) &&
           phxPspDisjoint(layout->ringOffset, PHX_PSP_LAYOUT_RING_BYTES, layout->stagingOffset, layout->stagingCapacity) &&
           phxPspDisjoint(layout->tmrOffset, layout->tmrCapacity, layout->stagingOffset, layout->stagingCapacity);
}
#endif
