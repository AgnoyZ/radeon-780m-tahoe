/* Test-only IOKit declarations. Never use this include path in a native tool build. */
#ifndef PHX_TEST_IOKIT_H
#define PHX_TEST_IOKIT_H
#include <stdint.h>
#include <stddef.h>
typedef uint32_t io_connect_t;
typedef uint32_t io_service_t;
typedef uint32_t mach_port_t;
typedef int32_t kern_return_t;
#define KERN_SUCCESS 0
#define kIOMainPortDefault 0
void *IOServiceMatching(const char *name);
io_service_t IOServiceGetMatchingService(mach_port_t port, void *matching);
kern_return_t IOServiceOpen(io_service_t service, mach_port_t task, uint32_t type, io_connect_t *connection);
kern_return_t IOServiceClose(io_connect_t connection);
kern_return_t IOObjectRelease(io_service_t service);
mach_port_t mach_task_self(void);
kern_return_t IOConnectCallScalarMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, uint64_t *output, uint32_t *output_count);
kern_return_t IOConnectCallMethod(io_connect_t connection, uint32_t selector,
    const uint64_t *input, uint32_t input_count, const void *input_data, size_t input_size,
    uint64_t *output, uint32_t *output_count, void *output_data, size_t *output_size);
#endif
