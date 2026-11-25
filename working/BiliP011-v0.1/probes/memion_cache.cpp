// SPDX-License-Identifier: LGPL-2.1-or-later
// Explicit output-allocation scope supplied by the private gst-omx overlay.
// No system modifications, second mappings, private struct layouts or fd dupes.
#include "omx_cache_bridge.h"
#include <dlfcn.h>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <mutex>
#include <sys/ioctl.h>
#include <linux/dma-buf.h>
#ifdef P011_CACHE_MOCK
extern "C" int p011_cache_mock_sync(int,uint64_t);
#endif

namespace {
constexpr unsigned frame_bytes=1920*1088*3/2;
struct Record {void*base=nullptr;int fd=-1;unsigned size=0;bool reading=false,managed=true;};
struct Scope {bool active=false,managed=true;unsigned calls=0;Record record;};
thread_local Scope allocation;
Record records[64];std::mutex mutex;P011CacheStats stats{};
using Map=int(*)(void*,int,unsigned,unsigned,int);
using Base=void*(*)(const void*);
using Heap=int(*)(const void*);
#ifdef P011_BUNDLED_OUTPUT_CACHE
static bool bundle_initialized=false,bundle_cached=false;
#endif
static bool configured(bool&cached){
#ifdef P011_BUNDLED_OUTPUT_CACHE
    cached=bundle_cached;return bundle_initialized;
#else
    const char*root=getenv("P011_CACHE_PROBE_ROOT");
#ifdef P011_CACHE_WORKER
    const char*prefix="/mnt/data/p011-toolbox/bili-seek-probe-";
    const char*owner=getenv("P011_SEEK_PROBE_ROOT");
    if(!root||!owner||strcmp(root,owner))return false;
#else
    const char*prefix="/mnt/data/p011-toolbox/ion-cache-probe-";
#endif
    if(!root||strncmp(root,prefix,strlen(prefix)))return false;
    const char*token=root+strlen(prefix);if(strlen(token)!=24)return false;
    for(unsigned i=0;i<24;i++)if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f')))return false;
    const char*mode=getenv("P011_CACHE_PROBE_MODE");
    if(!mode||(strcmp(mode,"cached")&&strcmp(mode,"uncached")))return false;
    cached=!strcmp(mode,"cached");return true;
#endif
}
static Record*lookup(void*base){for(auto&r:records)if(r.base&&r.base==base)return &r;return nullptr;}
static uint64_t clock_ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static bool synchronize(int fd,uint64_t flags){
    auto begin=clock_ns();bool ok=false;
    for(int attempt=0;attempt<8;attempt++){
#ifdef P011_CACHE_MOCK
        int result=p011_cache_mock_sync(fd,flags);
#else
        dma_buf_sync request{};request.flags=flags;
        int result=ioctl(fd,DMA_BUF_IOCTL_SYNC,&request);
#endif
        if(result==0){ok=true;break;}
        if(errno!=EINTR&&errno!=EAGAIN)break;
    }
    stats.sync_ns+=clock_ns()-begin;if(!ok)stats.sync_errors++;return ok;
}
}

extern "C" int cache_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
extern "C" int cache_map(void*object,int fd,unsigned size,unsigned heapmask,int flags){
    int saved_errno=errno;
    void*handle=dlopen("libmemion.so",RTLD_LAZY|RTLD_NOLOAD);
    if(!handle){errno=ENOSYS;return -ENOSYS;}
    auto call=reinterpret_cast<Map>(dlsym(handle,"_ZN6MemIon8mapIonFdEijji"));
    if(!call||call==cache_map){dlclose(handle);errno=ENOSYS;return -ENOSYS;}
    Base base=nullptr;Heap heap=nullptr;
    bool cached=false,scoped=allocation.active;
    scoped=scoped&&allocation.managed;
    if(scoped){
        base=reinterpret_cast<Base>(dlsym(handle,"_ZNK6MemIon7getBaseEv"));
        heap=reinterpret_cast<Heap>(dlsym(handle,"_ZNK6MemIon9getHeapIDEv"));
        // A single known output allocation per OMX_AllocateBuffer. Never
        // change codec input/reference/working allocations outside that call.
        if(!base||!heap||!configured(cached)||allocation.calls++||size!=frame_bytes||heapmask!=1||flags!=512){
            std::lock_guard<std::mutex>lock(mutex);stats.ownership_errors++;
            dlclose(handle);errno=EINVAL;return -EINVAL;
        }
        if(cached)heapmask=0x80000001u;
    }
    errno=saved_errno;int result=call(object,fd,size,heapmask,flags);int result_errno=errno;
    if(scoped&&result==0){
        allocation.record.base=base(object);allocation.record.fd=heap(object);allocation.record.size=size;
        if(!allocation.record.base||allocation.record.base==reinterpret_cast<void*>(intptr_t(-1))||
            allocation.record.fd<0||fcntl(allocation.record.fd,F_GETFD)<0)allocation.record=Record{};
    }
    {std::lock_guard<std::mutex>lock(mutex);
     if(!scoped)stats.forwarded_allocations++;
     else if(cached)stats.changed_allocations++;else stats.control_allocations++;}
    dlclose(handle);errno=result_errno;return result;
}

extern "C" int p011_cache_configure_bundle(int vendor_verified){
#ifdef P011_BUNDLED_OUTPUT_CACHE
    std::lock_guard<std::mutex>lock(mutex);
    if(bundle_initialized){stats.ownership_errors++;return 0;}
    bundle_initialized=true;bundle_cached=vendor_verified!=0;return 1;
#else
    (void)vendor_verified;return 0;
#endif
}
extern "C" int p011_cache_enabled(){bool cached=false;return configured(cached)&&cached;}
extern "C" int p011_cache_output_begin(unsigned size,int eligible){
#ifdef P011_BUNDLED_OUTPUT_CACHE
    bool cached=false;
    if(!configured(cached)||!size||allocation.active||(eligible&&(!cached||size!=frame_bytes))){
        std::lock_guard<std::mutex>lock(mutex);stats.ownership_errors++;return 0;
    }
    allocation=Scope{};allocation.active=true;allocation.managed=eligible!=0;return 1;
#else
    (void)size;(void)eligible;return 0;
#endif
}
extern "C" int p011_cache_allocate_begin(unsigned size){
    bool cached=false;
    if(!configured(cached)||size!=frame_bytes||allocation.active){
        std::lock_guard<std::mutex>lock(mutex);stats.ownership_errors++;return 0;
    }
    allocation=Scope{};allocation.active=true;return 1;
}
extern "C" int p011_cache_allocate_end(void*buffer,unsigned size,int success){
    Scope pending=allocation;allocation=Scope{};
    std::lock_guard<std::mutex>lock(mutex);
    if(!success)return 1;
    if(!pending.active||!buffer||!size||lookup(buffer)||(pending.managed&&
       (pending.calls!=1||pending.record.base!=buffer||pending.record.size!=size))){stats.ownership_errors++;return 0;}
    if(!pending.managed){pending.record=Record{};pending.record.base=buffer;pending.record.size=size;pending.record.managed=false;}
    for(auto&r:records)if(!r.base){
        r=pending.record;
        if(r.managed){stats.registered++;stats.active++;}
        else{stats.fallback_registered++;stats.fallback_active++;}
        return 1;
    }
    stats.ownership_errors++;return 0;
}
extern "C" int p011_cache_forget(void*buffer){
    std::lock_guard<std::mutex>lock(mutex);auto*record=lookup(buffer);
    if(!record)return 1; // input port or failed allocation, never CPU-mapped here
    if(record->reading){stats.ownership_errors++;return 0;}
    if(record->managed){stats.forgotten++;stats.active--;}
    else{stats.fallback_forgotten++;stats.fallback_active--;}
    *record=Record{};return 1;
}
extern "C" int p011_cache_can_forget(void*buffer){
    std::lock_guard<std::mutex>lock(mutex);auto*record=lookup(buffer);
    if(record&&record->reading){stats.ownership_errors++;return 0;}return 1;
}
extern "C" int p011_cache_read_begin(void*buffer,unsigned size){
    std::lock_guard<std::mutex>lock(mutex);auto*record=lookup(buffer);
    if(!record||record->reading||record->size!=size){stats.ownership_errors++;return 0;}
    if(record->managed&&!synchronize(record->fd,DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ))return 0;
    record->reading=true;
    if(record->managed)stats.read_begin++;else stats.fallback_read_begin++;
    return 1;
}
extern "C" int p011_cache_read_end(void*buffer){
    std::lock_guard<std::mutex>lock(mutex);auto*record=lookup(buffer);
    if(!record||!record->reading){stats.ownership_errors++;return 0;}
    bool ok=!record->managed||synchronize(record->fd,DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ);
    record->reading=false;
    if(ok){if(record->managed)stats.read_end++;else stats.fallback_read_end++;}
    return ok;
}
extern "C" P011CacheStats p011_cache_snapshot(){std::lock_guard<std::mutex>lock(mutex);return stats;}
