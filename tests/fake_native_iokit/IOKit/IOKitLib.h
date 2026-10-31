#ifndef PHX_TEST_NATIVE_IOKIT_H
#define PHX_TEST_NATIVE_IOKIT_H
#include <CoreFoundation/CoreFoundation.h>
#include <stddef.h>
#include <stdint.h>
using io_object_t = uint32_t;
using io_connect_t = uint32_t;
using io_service_t = uint32_t;
using io_registry_entry_t = uint32_t;
using io_iterator_t = uint32_t;
using mach_port_t = uint32_t;
using mach_vm_address_t = uint64_t;
using mach_vm_size_t = uint64_t;
using kern_return_t = int32_t;
constexpr io_object_t IO_OBJECT_NULL = 0;
constexpr mach_port_t kIOMainPortDefault = 0;
constexpr kern_return_t KERN_SUCCESS = 0;
constexpr unsigned kIOMapAnywhere = 1;
constexpr const char *kIOServicePlane = "IOService";
mach_port_t mach_task_self();
CFMutableDictionaryRef IOServiceMatching(const char *);
kern_return_t IOServiceGetMatchingServices(mach_port_t, CFMutableDictionaryRef, io_iterator_t *);
io_object_t IOIteratorNext(io_iterator_t);
kern_return_t IORegistryEntryGetParentEntry(io_registry_entry_t, const char *, io_registry_entry_t *);
bool IOObjectConformsTo(io_object_t, const char *);
CFTypeRef IORegistryEntryCreateCFProperty(io_registry_entry_t, CFStringRef, CFAllocatorRef, uint32_t);
kern_return_t IOObjectRelease(io_object_t);
kern_return_t IOServiceOpen(io_service_t, mach_port_t, uint32_t, io_connect_t *);
kern_return_t IOServiceClose(io_connect_t);
kern_return_t IOConnectCallMethod(io_connect_t, uint32_t, const uint64_t *, uint32_t,
    const void *, size_t, uint64_t *, uint32_t *, void *, size_t *);
kern_return_t IOConnectMapMemory64(io_connect_t, uint32_t, mach_port_t,
    mach_vm_address_t *, mach_vm_size_t *, unsigned);
kern_return_t IOConnectUnmapMemory64(io_connect_t, uint32_t, mach_port_t, mach_vm_address_t);
#endif
