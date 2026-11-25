#pragma once
#include <stddef.h>
typedef unsigned char guchar; struct GChecksum; enum {G_CHECKSUM_SHA256=2};
extern GChecksum*g_checksum_new(int);
extern void g_checksum_update(GChecksum*,const guchar*,size_t);
extern const char*g_checksum_get_string(GChecksum*);
extern void g_checksum_free(GChecksum*);
