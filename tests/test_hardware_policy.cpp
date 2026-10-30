#include "PhxHardwarePolicy.hpp"
#include <cassert>
#include <iostream>
int main() {
    using namespace phx780m;
    assert(allowDevice(25, 0x1002, 0x1900, true));
    assert(!allowDevice(25, 0x1002, 0x1900, false));
    assert(!allowDevice(23, 0x1002, 0x1900, true));
    assert(!allowDevice(26, 0x1002, 0x1900, true));
    assert(!allowDevice(25, 0x10de, 0x1900, true));
    assert(!allowDevice(25, 0x1002, 0x15bf, true));
    for (int c = 0; c <= 1; ++c) for (int g = 0; g <= 1; ++g) {
        assert(queueIndex(false, c, g) == (c ? 0 : -1));
        assert(queueIndex(true, c, g) == (g ? 1 : -1));
    }
    for (unsigned a = 0; a < 4; ++a) for (unsigned b = 0; b < 4; ++b)
        assert(sameEngine(a, b) == (a <= 1 && a == b));
    assert(!sameEngine(UINT32_MAX, UINT32_MAX));
    std::cout << "Hardware policy assertions passed (not a GPU execution test).\n";
}
