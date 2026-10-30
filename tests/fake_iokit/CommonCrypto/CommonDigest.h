/* Host fault-test declaration only. Native builds use Apple's real CommonCrypto. */
#ifndef PHX_FAKE_COMMON_DIGEST_H
#define PHX_FAKE_COMMON_DIGEST_H
#include <stdint.h>
typedef uint32_t CC_LONG;
#define CC_SHA256_DIGEST_LENGTH 32
unsigned char *CC_SHA256(const void *, CC_LONG, unsigned char *);
#endif
