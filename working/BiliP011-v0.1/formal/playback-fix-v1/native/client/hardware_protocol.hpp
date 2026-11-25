// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstddef>

namespace p011_hw {
// Anonymous shared memory: pixels only, no URL, cookie, filename or account.
// States are 32-bit lock-free atomics shared by two native ARM processes.
// A reader owns a slot throughout texture upload, so the decoder can never
// overwrite the displayed buffer halfway through an upload.
constexpr uint32_t magic=0x50303131, version=2;
constexpr unsigned edge=1920,slots=3,capacity=1920*1080*3/2;
enum State:uint32_t {Free,Writing,Ready,Reading};
struct Frame {
    uint32_t state,serial,width,height,bytes;
    uint32_t format,matrix,full_range;
    double pts;
    alignas(64) unsigned char pixels[capacity];
};
struct Shared {uint32_t signature,revision;Frame frames[slots];};
inline uint32_t read(const uint32_t&v){return __atomic_load_n(&v,__ATOMIC_ACQUIRE);}
inline void set(uint32_t&v,uint32_t n){__atomic_store_n(&v,n,__ATOMIC_RELEASE);}
inline bool take(uint32_t&v,uint32_t expected,uint32_t next){return __atomic_compare_exchange_n(&v,&expected,next,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);}
inline bool supported(int codec,int w,int h,bool dash){return codec==7&&dash&&w>0&&h>0&&w<=1920&&h<=1920&&(w<=1080||h<=1080);}
inline bool valid(unsigned w,unsigned h,unsigned bytes){return w>0&&h>0&&w%2==0&&h%2==0&&w<=edge&&h<=edge&&(w<=1080||h<=1080)&&bytes==w*h*3/2&&bytes<=capacity;}
static_assert(__atomic_always_lock_free(4,nullptr),"Shared state needs native 32-bit atomics");
}
