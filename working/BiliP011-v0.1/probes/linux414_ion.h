/* SPDX-License-Identifier: GPL-2.0-only
 * Linux v4.14 ION userspace ABI subset, Copyright (C) 2011 Google, Inc.
 * https://github.com/torvalds/linux/blob/v4.14/drivers/staging/android/uapi/ion.h
 * Exact public structures; no vendor-private allocator layout is assumed.
 */
#pragma once
#include <linux/ioctl.h>
#include <linux/types.h>
struct ion_allocation_data { __u64 len; __u32 heap_id_mask,flags,fd,unused; };
struct ion_heap_data { char name[32]; __u32 type,heap_id,reserved0,reserved1,reserved2; };
struct ion_heap_query { __u32 cnt,reserved0; __u64 heaps; __u32 reserved1,reserved2; };
#define ION_FLAG_CACHED 1
#define ION_IOC_ALLOC _IOWR('I',0,struct ion_allocation_data)
#define ION_IOC_HEAP_QUERY _IOWR('I',8,struct ion_heap_query)
static_assert(sizeof(ion_allocation_data)==24,"ION allocation ABI");
static_assert(sizeof(ion_heap_query)==24,"ION query ABI");
static_assert(sizeof(ion_heap_data)==52,"ION heap ABI");
static_assert(ION_IOC_ALLOC==0xc0184900UL,"ION allocation ioctl");
static_assert(ION_IOC_HEAP_QUERY==0xc0184908UL,"ION query ioctl");
