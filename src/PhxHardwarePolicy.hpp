// Downstream research policy. No register access, firmware loading, or fake completion.
#ifndef PHX_780M_HARDWARE_POLICY_HPP
#define PHX_780M_HARDWARE_POLICY_HPP
#include <stdint.h>
namespace phx780m {
constexpr bool allowDevice(int darwinMajor, uint16_t vendor, uint16_t device, bool optedIn) {
    return optedIn && darwinMajor == 25 && vendor == 0x1002 && device == 0x1900;
}
constexpr int queueIndex(bool graphics, bool computeReady, bool graphicsReady) {
    return graphics ? (graphicsReady ? 1 : -1) : (computeReady ? 0 : -1);
}
constexpr bool sameEngine(uint32_t first, uint32_t current) {
    return first <= 1 && current == first;
}
constexpr bool rangeWithin(uint64_t offset, uint64_t bytes, uint64_t limit) {
    return offset <= limit && bytes <= limit - offset;
}
}
#endif
