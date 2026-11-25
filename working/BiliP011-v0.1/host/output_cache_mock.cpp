// SPDX-License-Identifier: LGPL-2.1-or-later
// Exercise the identical bridge with explicitly tracked uncached fallbacks.
#include "../probes/omx_cache_bridge.h"
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#include <linux/dma-buf.h>
struct Fake {void*base;int fd;unsigned mask;};
extern "C" int call_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
static unsigned sync_calls=0;
extern "C" int p011_cache_mock_sync(int fd,uint64_t flags){
    assert(fd>=0);sync_calls++;
    assert(flags==(sync_calls%2?DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ:DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ));return 0;
}
int main(int argc,char**){
    bool verified=argc==1;
    void*library=dlopen("libmemion.so",RTLD_LAZY|RTLD_GLOBAL);assert(library);
    assert(p011_cache_configure_bundle(verified));assert(bool(p011_cache_enabled())==verified);
    char pixels[8];Fake value{pixels,open("/dev/null",O_RDONLY),0};assert(value.fd>=0);
    // Equal allocation length does not make portrait or unusual stride eligible.
    for(unsigned i=0;i<3;i++){
        bool eligible=i==2&&verified;
        unsigned bytes=i==0?1382400:3133440;
        assert(p011_cache_output_begin(bytes,eligible));
        assert(call_map(&value,234,bytes,1,512)==0&&errno==E2BIG);
        assert(value.mask==(eligible?0x80000001u:1u));
        assert(p011_cache_allocate_end(pixels,bytes,1));
        assert(p011_cache_read_begin(pixels,bytes));
        assert(p011_cache_read_end(pixels));
        assert(p011_cache_can_forget(pixels));assert(p011_cache_forget(pixels));
    }
    auto stats=p011_cache_snapshot();unsigned managed=verified?1:0,fallback=3-managed;
    assert(stats.changed_allocations==managed&&stats.control_allocations==0);
    assert(stats.forwarded_allocations==fallback&&sync_calls==2*managed);
    assert(stats.registered==managed&&stats.forgotten==managed&&stats.active==0);
    assert(stats.read_begin==managed&&stats.read_end==managed);
    assert(stats.fallback_registered==fallback&&stats.fallback_forgotten==fallback&&stats.fallback_active==0);
    assert(stats.fallback_read_begin==fallback&&stats.fallback_read_end==fallback);
    assert(stats.sync_errors==0&&stats.ownership_errors==0);
    // Unknown or already freed memory is never silently treated as fallback.
    assert(!p011_cache_read_begin(pixels,3133440));
    assert(!p011_cache_configure_bundle(verified));
    assert(p011_cache_snapshot().ownership_errors==2);
    close(value.fd);dlclose(library);puts("OUTPUT_CACHE_FALLBACK_MOCK_PASS");
}
