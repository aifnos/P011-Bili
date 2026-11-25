// SPDX-License-Identifier: GPL-2.0-only
// CPU-only, synthetic pixels, owned ION buffers. NEVER opens VSP/display.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <regex>
#include <string>
#include <vector>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <linux/dma-buf.h>
#include <nlohmann/json.hpp>
#include "linux414_ion.h"
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_copy.h"
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h"
using J=nlohmann::json;
static volatile sig_atomic_t stopping=0;
static void stop(int){stopping=1;}
static uint64_t now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static int checked_ioctl(int fd,unsigned long op,void*data){
    for(int i=0;i<8&&!stopping;i++){
        int rc=ioctl(fd,op,data);if(rc==0)return 0;
        if(errno!=EINTR&&errno!=EAGAIN)return -1;
    }
    return -1;
}
struct Fd{int value=-1;~Fd(){if(value>=0)close(value);}};
struct Mapping{void*data=MAP_FAILED;size_t size=0;~Mapping(){if(data!=MAP_FAILED)munmap(data,size);}};
struct Copier{void*worker=nullptr;~Copier(){p011_copy_worker_free(worker);}};
static bool sync(int fd,uint64_t flags){dma_buf_sync s{};s.flags=flags;return checked_ioctl(fd,DMA_BUF_IOCTL_SYNC,&s)==0;}
static J measure(int ion,unsigned heap,unsigned flags,const std::vector<uint8_t>&source,
                 const std::vector<uint8_t>&expected){
    // Allocate ONE owned source mapping at a time; FD and mapping are RAII.
    ion_allocation_data request{};request.len=source.size();request.heap_id_mask=1u<<heap;request.flags=flags;
    if(checked_ioctl(ion,ION_IOC_ALLOC,&request))throw 10;
    Fd fd;fd.value=int(request.fd);if(fd.value<0)throw 11;
    Mapping memory;memory.size=source.size();memory.data=mmap(nullptr,memory.size,PROT_READ|PROT_WRITE,MAP_SHARED,fd.value,0);
    if(memory.data==MAP_FAILED)throw 12;
    if(!sync(fd.value,DMA_BUF_SYNC_START|DMA_BUF_SYNC_RW))throw 13;
    memcpy(memory.data,source.data(),source.size());
    if(!sync(fd.value,DMA_BUF_SYNC_END|DMA_BUF_SYNC_RW))throw 14;
    std::vector<uint8_t>output(expected.size());Copier copier;uint64_t copy_ns=0,sync_ns=0,max_ns=0;
    unsigned matched=0;const auto*src=static_cast<const uint8_t*>(memory.data);
    P011CopyPlane planes[]={
        {output.data(),src,960,540,960,3840,1},
        {output.data()+960*540,src+1920*1088,960,270,960,3840,2}};
    for(unsigned i=0;i<18&&!stopping;i++){
        auto begin=now();if(!sync(fd.value,DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ))throw 15;
        auto copy_begin=now();p011_copy_planes(&copier.worker,planes,2);auto copy_end=now();
        if(!sync(fd.value,DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ))throw 16;
        auto end=now();
        if(output!=expected)throw 17;
        if(i>=2){copy_ns+=copy_end-copy_begin;sync_ns+=(copy_begin-begin)+(end-copy_end);max_ns=std::max(max_ns,copy_end-copy_begin);matched++;}
    }
    if(stopping||matched!=16)throw 18;
    return J{{"flags",flags},{"samples",matched},{"copy_ns",copy_ns},{"max_copy_ns",max_ns},
             {"sync_ns",sync_ns},{"pixel_bytes_checked",uint64_t(expected.size())*18},
             {"all_pixels_match",true},{"source_bytes",source.size()}};
}
int main(int argc,char**argv){
    if(argc!=2)return 2;int parent=atoi(argv[1]);prctl(PR_SET_PDEATHSIG,SIGTERM);
    const char*root=getenv("P011_ION_COPY_ROOT");
    if(parent<=1||getppid()!=parent||!root||!std::regex_match(root,std::regex("/mnt/data/p011-toolbox/ion-copy-probe-[a-f0-9]{24}")))return 3;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGALRM,stop);alarm(25);
    J result={{"passed",false},{"window_opened",false},{"video_decoded",false},{"vendor_library_modified",false},{"samples",J::array()}};
    int code=0;
    try{
        auto checks=p011_omx_half_selftest();result["half_checks"]=checks;if(checks!=2016)throw 4;
        Fd ion;ion.value=open("/dev/ion",O_RDONLY|O_CLOEXEC|O_SYNC);if(ion.value<0)throw 5;
        ion_heap_query query{};if(checked_ioctl(ion.value,ION_IOC_HEAP_QUERY,&query)||query.cnt==0||query.cnt>32)throw 6;
        std::vector<ion_heap_data>heaps(query.cnt);unsigned count=query.cnt;query.heaps=reinterpret_cast<uintptr_t>(heaps.data());
        if(checked_ioctl(ion.value,ION_IOC_HEAP_QUERY,&query)||query.cnt>count)throw 7;
        unsigned selected=32,found=0;for(unsigned i=0;i<query.cnt;i++)if(heaps[i].type==0&&heaps[i].heap_id<32){selected=heaps[i].heap_id;found++;}
        if(found!=1)throw 8;result["heap_id"]=selected;
        std::vector<uint8_t>source(1920*1088*3/2),expected(960*540*3/2);
        for(size_t i=0;i<source.size();i++)source[i]=(i*67+i/19+13)&255;
        for(unsigned plane=0;plane<2;plane++){
            unsigned rows=plane?270:540,step=plane?2:1;size_t input=plane?1920*1088:0,output=plane?960*540:0;
            for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<960;x++){
                const uint8_t*s=source.data()+input+y*3840+(x/step)*2*step+x%step;
                expected[output+y*960+x]=((unsigned)s[0]+s[step]+s[1920]+s[1920+step]+2)/4;
            }
        }
        for(unsigned flags:{0u,unsigned(ION_FLAG_CACHED),0u})result["samples"].push_back(measure(ion.value,selected,flags,source,expected));
        result["passed"]=!stopping;
    }catch(int c){code=c;result["error"]=c;result["errno"]=errno;}catch(...){code=99;result["error"]=99;}
    result["stopped"]=bool(stopping);printf("ION_COPY=%s\n",result.dump().c_str());return code;
}
