// Host-side acceptance checks shared by the real Metal probe and CPU tests.
#ifndef PHX_780M_COMPUTE_PROBE_H
#define PHX_780M_COMPUTE_PROBE_H
#include <stddef.h>
#include <stdint.h>

#define PHX_PROBE_GUARD_WORDS 64u
#define PHX_PROBE_GUARD_VALUE 0xA5A5F00Du

static inline int phxProbeTarget(uint32_t vendor, uint32_t device) {
    return vendor == 0x1002u && device == 0x1900u;
}

static inline uint32_t phxProbeInput(uint32_t index, uint32_t pass) {
    return index ^ (0x12345678u + pass);
}

static inline uint32_t phxProbeExpected(uint32_t index, uint32_t pass) {
    return (phxProbeInput(index, pass) * 1664525u + 1013904223u) ^ (index * 2654435761u);
}

enum PhxProbeError { PhxProbeOK, PhxProbeInvalidSize, PhxProbeInputChanged, PhxProbeResultMismatch, PhxProbeGuardChanged };
struct PhxProbeCheck { enum PhxProbeError error; size_t index; uint32_t expected; uint32_t actual; };

static inline struct PhxProbeCheck phxProbeCheck(const uint32_t *input, size_t inputWords,
                                                const uint32_t *output, size_t outputWords,
                                                uint32_t n, uint32_t pass, size_t prefix) {
    struct PhxProbeCheck result = {PhxProbeOK, 0, 0, 0};
    if (!input || !output || !n || inputWords < n || prefix > outputWords ||
        (size_t)n > outputWords - prefix || outputWords - prefix - n < PHX_PROBE_GUARD_WORDS) {
        result.error = PhxProbeInvalidSize; return result;
    }
    for (uint32_t i = 0; i < n; ++i) {
        uint32_t expected = phxProbeInput(i, pass);
        if (input[i] != expected) {
            result.error = PhxProbeInputChanged; result.index = i;
            result.expected = expected; result.actual = input[i]; return result;
        }
        expected = phxProbeExpected(i, pass);
        if (output[prefix + i] != expected) {
            result.error = PhxProbeResultMismatch; result.index = i;
            result.expected = expected; result.actual = output[prefix + i]; return result;
        }
    }
    for (size_t i = 0; i < outputWords; ++i) {
        if (i >= prefix && i - prefix < n) continue;
        if (output[i] != PHX_PROBE_GUARD_VALUE) {
            result.error = PhxProbeGuardChanged; result.index = i;
            result.expected = PHX_PROBE_GUARD_VALUE; result.actual = output[i]; return result;
        }
    }
    return result;
}
#endif
