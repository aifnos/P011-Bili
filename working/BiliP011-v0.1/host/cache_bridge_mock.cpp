// SPDX-License-Identifier: LGPL-2.1-or-later
#include <cerrno>
#include <cstdint>
struct Fake {void*base;int fd;unsigned mask;};
#ifdef P011_MOCK_LIBRARY
extern "C" int mock_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
extern "C" void*mock_base(const void*) asm("_ZNK6MemIon7getBaseEv");
extern "C" int mock_heap(const void*) asm("_ZNK6MemIon9getHeapIDEv");
extern "C" int mock_map(void*object,int fd,unsigned size,unsigned mask,int flags){
    if(fd!=234||flags!=512||(size!=3133440&&size!=1382400))return -5;
    static_cast<Fake*>(object)->mask=mask;errno=E2BIG;return 0;
}
#ifndef P011_MOCK_NO_GETTERS
extern "C" void*mock_base(const void*object){return static_cast<const Fake*>(object)->base;}
extern "C" int mock_heap(const void*object){return static_cast<const Fake*>(object)->fd;}
#endif
#else
#include "../probes/omx_cache_bridge.h"
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <initializer_list>
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#include <linux/dma-buf.h>
extern "C" int call_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
static unsigned sync_calls=0;
extern "C" int p011_cache_mock_sync(int fd,uint64_t flags){
    assert(fd>=0);sync_calls++;
    if(sync_calls==1){errno=EINTR;return -1;}
    assert(flags==(sync_calls%2==0?DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ:DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ));return 0;
}
int main(){
    void*library=dlopen("libmemion.so",RTLD_LAZY|RTLD_GLOBAL);assert(library);
    char pixels[8];Fake value{pixels,open("/dev/null",O_RDONLY),0};assert(value.fd>=0);
    setenv("P011_CACHE_PROBE_ROOT","/mnt/data/p011-toolbox/ion-cache-probe-000000000000000000000000",1);
    setenv("P011_CACHE_PROBE_MODE","cached",1);
    assert(call_map(&value,234,3133440,1,512)==0&&value.mask==1&&errno==E2BIG);
    for(const char*mode:{"cached","uncached"}){
        setenv("P011_CACHE_PROBE_MODE",mode,1);
        assert(p011_cache_allocate_begin(3133440));
        assert(call_map(&value,234,3133440,1,512)==0&&errno==E2BIG);
        assert(value.mask==(mode[0]=='c'?0x80000001u:1u));
        assert(p011_cache_allocate_end(pixels,3133440,1));
        assert(p011_cache_read_begin(pixels,3133440));
        assert(p011_cache_read_end(pixels));
        assert(p011_cache_can_forget(pixels));assert(p011_cache_forget(pixels));
    }
    auto stats=p011_cache_snapshot();
    assert(stats.changed_allocations==1&&stats.control_allocations==1&&stats.forwarded_allocations==1);
    assert(stats.registered==2&&stats.forgotten==2&&stats.active==0);
    assert(stats.read_begin==2&&stats.read_end==2&&stats.sync_errors==0&&stats.ownership_errors==0&&sync_calls==5);
    assert(!p011_cache_read_begin(pixels,3133440));
    setenv("P011_CACHE_PROBE_MODE","invalid",1);assert(!p011_cache_allocate_begin(3133440));
    setenv("P011_CACHE_PROBE_MODE","cached",1);assert(!p011_cache_allocate_begin(12));
    assert(p011_cache_snapshot().ownership_errors==3);
    close(value.fd);dlclose(library);puts("CACHE_BRIDGE_MOCK_PASS");
}
#endif
