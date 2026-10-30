// Resolve only the RADV library adjacent to the loaded plugin image.
#ifndef PHX_780M_RUNTIME_PATH_H
#define PHX_780M_RUNTIME_PATH_H
#include <stddef.h>
#include <string.h>

static inline int phxRuntimeLibraryPath(const char *image, char *output, size_t capacity) {
    static const char library[] = "libvulkan_radeon.dylib";
    if (!output || !capacity) return 0;
    output[0] = '\0';
    if (!image || image[0] != '/') return 0;
    const char *slash = strrchr(image, '/');
    if (!slash || !slash[1]) return 0;
    size_t directory = (size_t)(slash - image) + 1;
    if (directory >= capacity || sizeof(library) > capacity - directory) return 0;
    memcpy(output, image, directory);
    memcpy(output + directory, library, sizeof(library));
    return 1;
}
#endif
