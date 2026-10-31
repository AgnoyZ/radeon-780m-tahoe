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
static inline int phxMesArenaLayoutValid(const struct PhxMesQueueLayout *queue,
    const struct PhxGartLayout *gart, const struct PhxBootMemory *memory, uint64_t arenaBytes) {
    if (!phxMesQueueInputsValid(queue) || !phxGartLayoutValid(gart, memory)) return 0;
    if (arenaBytes < PHX_MES_QUEUE_ARENA_BYTES || (arenaBytes & 4095) ||
        !phxPspSpanFits(queue->arenaOffset, arenaBytes, 0x100000000ull) ||
        !phxPspSpanFits(queue->arenaOffset, arenaBytes, gart->mappedBytes) ||
        !phxPspSpanFits(queue->arenaOffset, arenaBytes, memory->apertureBytes)) return 0;
    const uint64_t offsets[] = {gart->tableOffset, gart->defaultPageOffset,
        memory->psp.ringOffset, memory->psp.tmrOffset, memory->psp.stagingOffset};
    const uint64_t lengths[] = {phxGartTableBytes(gart), 4096,
        PHX_PSP_LAYOUT_RING_BYTES, memory->psp.tmrCapacity, memory->psp.stagingCapacity};
    for (unsigned i = 0; i < 5; ++i)
        if (!phxPspDisjoint(queue->arenaOffset, arenaBytes, offsets[i], lengths[i])) return 0;
    return 1;
}
static inline int phxMesQueueLayoutValid(const struct PhxMesQueueLayout *queue,
    const struct PhxGartLayout *gart, const struct PhxBootMemory *memory) {
    return phxMesArenaLayoutValid(queue, gart, memory, PHX_MES_QUEUE_ARENA_BYTES);
}
#define PHX_COMPUTE_PROBE_ARENA_BYTES 0x5000ull
static inline int phxComputeProbeLayoutValid(const struct PhxMesQueueLayout *scheduler,
    const struct PhxMesQueueLayout *compute, const struct PhxGartLayout *gart, const struct PhxBootMemory *memory) {
    return phxMesQueueLayoutValid(scheduler, gart, memory) &&
        phxMesArenaLayoutValid(compute, gart, memory, PHX_COMPUTE_PROBE_ARENA_BYTES) &&
        scheduler->doorbellIndex != compute->doorbellIndex &&
        phxPspDisjoint(scheduler->arenaOffset, PHX_MES_QUEUE_ARENA_BYTES,
                      compute->arenaOffset, PHX_COMPUTE_PROBE_ARENA_BYTES);
}
#endif
