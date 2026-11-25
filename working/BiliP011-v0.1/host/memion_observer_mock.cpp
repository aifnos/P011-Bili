// SPDX-License-Identifier: GPL-2.0-only
#include <cerrno>
#include <cstdint>
#ifdef P011_MOCK_LIBRARY
extern "C" int mock_map(void*,int,unsigned,unsigned,int) asm("_ZN6MemIon8mapIonFdEijji");
extern "C" int mock_map(void*object,int fd,unsigned size,unsigned heapmask,int flags){
    if(object!=reinterpret_cast<void*>(uintptr_t(123))||fd!=234||size!=3133440||heapmask!=0x80000001u||flags!=512)return -3;
    errno=EDOM;return 17;
}
#else
#include <dlfcn.h>
#include <cstdio>
#include <unistd.h>
int main(){
    using Function=int(*)(void*,int,unsigned,unsigned,int);
    void*handle=dlopen("libmemion.so",RTLD_LAZY|RTLD_GLOBAL);if(!handle)return 2;
    auto function=reinterpret_cast<Function>(dlsym(RTLD_DEFAULT,"_ZN6MemIon8mapIonFdEijji"));
    if(!function)return 3;int saved=dup(1);if(saved<0||dup2(saved,4)<0)return 4;if(saved!=4)close(saved);
    errno=0;int result=function(reinterpret_cast<void*>(uintptr_t(123)),234,3133440,0x80000001u,512);
    bool ok=result==17&&errno==EDOM;dlclose(handle);return ok?0:5;
}
#endif
