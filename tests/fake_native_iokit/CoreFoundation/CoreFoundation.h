#ifndef PHX_TEST_NATIVE_CF_H
#define PHX_TEST_NATIVE_CF_H
#include <stddef.h>
#include <stdint.h>
struct FakeCF;
using CFTypeRef = const FakeCF *;
using CFDataRef = const FakeCF *;
using CFNumberRef = const FakeCF *;
using CFStringRef = const char *;
using CFMutableDictionaryRef = void *;
using CFAllocatorRef = const void *;
using CFTypeID = unsigned long;
using CFIndex = long;
using UInt8 = uint8_t;
constexpr CFAllocatorRef kCFAllocatorDefault = nullptr;
constexpr int kCFNumberSInt64Type = 4;
#define CFSTR(value) (value)
CFTypeID CFGetTypeID(CFTypeRef);
CFTypeID CFDataGetTypeID();
CFTypeID CFNumberGetTypeID();
CFIndex CFDataGetLength(CFDataRef);
const UInt8 *CFDataGetBytePtr(CFDataRef);
bool CFNumberGetValue(CFNumberRef, int, void *);
void CFRelease(CFTypeRef);
#endif
