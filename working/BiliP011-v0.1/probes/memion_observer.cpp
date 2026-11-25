// SPDX-License-Identifier: GPL-2.0-only
// Read-only argument observer for the pinned P011 libmemion.so mapIonFd ABI.
// Does not change arguments, returned buffers, allocation flags, or vendor code.
// Return type/arguments verified against ARM disassembly at 0xda0..0x11a8.
#include <dlfcn.h>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <unistd.h>

using Map=int(*)(void*,int,unsigned,unsigned,int);
static std::atomic<unsigned> events{0};
static bool enabled(){
    const char*value=getenv("P011_SEEK_PROBE_ROOT");
    const char*prefix="/mnt/data/p011-toolbox/bili-seek-probe-";
    if(!value||strncmp(value,prefix,strlen(prefix)))return false;
    const char*token=value+strlen(prefix);if(strlen(token)!=24)return false;
    for(unsigned i=0;i<24;i++)if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f')))return false;
    return true;
}
static Map original(){
    // A handle lookup finds the real member in its already loaded DSO, even
    // when OMX has loaded that DSO into a local lookup scope. Never reload it.
    void*handle=dlopen("libmemion.so",RTLD_LAZY|RTLD_NOLOAD);
    if(!handle)return nullptr;
    auto function=reinterpret_cast<Map>(dlsym(handle,"_ZN6MemIon8mapIonFdEijji"));
    dlclose(handle);return function;
}
extern "C" int observe_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
extern "C" int observe_map(void*object,int fd,unsigned size,unsigned heapmask,int flags){
    const int saved_errno=errno;
    auto call=original();
    if(!call||call==observe_map){errno=ENOSYS;return -ENOSYS;}
    errno=saved_errno;
    const int result=call(object,fd,size,heapmask,flags);
    const int result_errno=errno;
    if(enabled()){
        unsigned serial=events.fetch_add(1);
        if(serial<64){
            char line[256];int bytes=snprintf(line,sizeof(line),
                "{\"ion_allocation_event\":%u,\"bytes\":%u,\"heapmask\":%u,\"mapping_flags\":%d,\"result\":%d}\n",
                serial,size,heapmask,flags,result);
            // One bounded write below PIPE_BUF; contains no pointers, URLs,
            // file names, decoded pixels, account data, or device identifiers.
            if(bytes>0&&unsigned(bytes)<sizeof(line)){
                ssize_t n;do{n=write(4,line,size_t(bytes));}while(n<0&&errno==EINTR);
            }
        }
    }
    errno=result_errno;return result;
}
