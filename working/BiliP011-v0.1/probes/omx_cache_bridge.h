/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef P011_OMX_CACHE_BRIDGE_H
#define P011_OMX_CACHE_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
  uint64_t changed_allocations, control_allocations, forwarded_allocations;
  uint64_t registered, forgotten, active, read_begin, read_end;
  uint64_t sync_errors, ownership_errors, sync_ns;
  uint64_t fallback_registered, fallback_forgotten, fallback_active;
  uint64_t fallback_read_begin, fallback_read_end;
} P011CacheStats;
/* Bundle initialization happens once, before any decoder allocation. A false
 * vendor gate disables caching but preserves the original allocation path. */
int p011_cache_configure_bundle(int vendor_verified);
int p011_cache_enabled(void);
int p011_cache_output_begin(unsigned size,int eligible);
int p011_cache_allocate_begin(unsigned size);
int p011_cache_allocate_end(void *buffer,unsigned size,int success);
int p011_cache_can_forget(void *buffer);
int p011_cache_forget(void *buffer);
int p011_cache_read_begin(void *buffer,unsigned size);
int p011_cache_read_end(void *buffer);
P011CacheStats p011_cache_snapshot(void);
#ifdef __cplusplus
}
#endif
#endif
