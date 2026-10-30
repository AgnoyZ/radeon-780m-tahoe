/* Host-only ICD loading/negative-enumeration test. Never submit GPU work. */
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: radv-no-device /absolute/path/libvulkan_radeon.dylib\n");
        return 2;
    }
    const char *services[] = {"PhxBringup", "NMXAccel", "Navi48Bringup", "Navi48Accelerator"};
    for (unsigned i = 0; i < sizeof(services) / sizeof(services[0]); ++i) {
        io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching(services[i]));
        if (service) {
            IOObjectRelease(service);
            fprintf(stderr, "Refusing no-device test: %s is present; no connection opened.\n", services[i]);
            return 77;
        }
    }
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        fprintf(stderr, "ICD load failed: %s\n", dlerror());
        return 3;
    }
    PFN_vkGetInstanceProcAddr get_proc = (PFN_vkGetInstanceProcAddr)dlsym(library, "vk_icdGetInstanceProcAddr");
    int (*set_service)(const char *) = (int (*)(const char *))dlsym(library, "radv_darwin_set_service_class");
    if (!get_proc || !set_service || set_service("PhxBringup") != 0 ||
        set_service("Navi48Bringup") != -EINVAL || set_service("Navi48Accelerator") != -EINVAL) {
        fprintf(stderr, "Missing ICD exports or incorrect Phoenix service policy\n");
        return 4;
    }
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)get_proc(VK_NULL_HANDLE, "vkCreateInstance");
    if (!create)
        return 5;
    const VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                                  .pApplicationName = "780M-negative-test", .apiVersion = VK_API_VERSION_1_3};
    const VkInstanceCreateInfo info = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VkInstance instance = VK_NULL_HANDLE;
    VkResult result = create(&info, NULL, &instance);
    if (result != VK_SUCCESS || !instance) {
        fprintf(stderr, "vkCreateInstance failed: %d\n", result);
        return 6;
    }
    PFN_vkEnumeratePhysicalDevices enumerate = (PFN_vkEnumeratePhysicalDevices)get_proc(instance, "vkEnumeratePhysicalDevices");
    PFN_vkDestroyInstance destroy = (PFN_vkDestroyInstance)get_proc(instance, "vkDestroyInstance");
    if (!enumerate || !destroy)
        return 7;
    uint32_t count = 0;
    result = enumerate(instance, &count, NULL);
    destroy(instance, NULL);
    dlclose(library);
    if (result != VK_SUCCESS || count != 0) {
        fprintf(stderr, "Expected successful empty enumeration, got result=%d count=%u\n", result, count);
        return 8;
    }
    puts("{\"runtime_loaded\":true,\"physical_devices\":0,\"gpu_submitted\":false}");
    return 0;
}
