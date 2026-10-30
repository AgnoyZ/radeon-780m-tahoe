#include <metal_stdlib>
using namespace metal;

#ifndef ADD_VALUE
#define ADD_VALUE 17
#endif

kernel void increment(device uint *output [[buffer(0)]], uint index [[thread_position_in_grid]])
{
    output[index] = index + ADD_VALUE;
}
