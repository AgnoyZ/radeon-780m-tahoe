/* Scheduler bootstrap geometry only; the caller must establish region ownership. */
#ifndef PHX_MES_QUEUE_LAYOUT_H
#define PHX_MES_QUEUE_LAYOUT_H
#include "PhxGartLayout.h"
#define PHX_MES_QUEUE_VERSION 1ull
#define PHX_MES_QUEUE_ARENA_BYTES 0x4000ull
struct PhxMesQueueLayout {
    uint64_t version, arenaOffset, doorbellIndex;
};
static inline int phxMesQueueInputsValid(const struct PhxMesQueueLayout *queue) {
    return queue && queue->version == PHX_MES_QUEUE_VERSION && !(queue->arenaOffset & 4095) &&
        !(queue->doorbellIndex & 1) && queue->doorbellIndex <= 0x3fffffeull &&
        phxPspSpanFits(queue->arenaOffset, PHX_MES_QUEUE_ARENA_BYTES, 0x100000000ull);
}
static inline int phxMesQueueLayoutValid(const struct PhxMesQueueLayout *queue,
    const struct PhxGartLayout *gart, const struct PhxBootMemory *memory) {
    if (!phxMesQueueInputsValid(queue) || !phxGartLayoutValid(gart, memory)) return 0;
    if (!phxPspSpanFits(queue->arenaOffset, PHX_MES_QUEUE_ARENA_BYTES, gart->mappedBytes) ||
        !phxPspSpanFits(queue->arenaOffset, PHX_MES_QUEUE_ARENA_BYTES, memory->apertureBytes)) return 0;
    const uint64_t offsets[] = {gart->tableOffset, gart->defaultPageOffset,
        memory->psp.ringOffset, memory->psp.tmrOffset, memory->psp.stagingOffset};
    const uint64_t lengths[] = {phxGartTableBytes(gart), 4096,
        PHX_PSP_LAYOUT_RING_BYTES, memory->psp.tmrCapacity, memory->psp.stagingCapacity};
    for (unsigned i = 0; i < 5; ++i)
        if (!phxPspDisjoint(queue->arenaOffset, PHX_MES_QUEUE_ARENA_BYTES, offsets[i], lengths[i])) return 0;
    return 1;
}
#endif
