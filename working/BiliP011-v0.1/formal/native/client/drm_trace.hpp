// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Private diagnostic build only. Linux ioctl ABI pass-through, not a driver
// replacement: each call reaches the kernel exactly once with unchanged args.
// Inspect only numeric CREATE_DUMB fields, never buffers, handles or addresses.
// ABI: Linux v4.14 include/uapi/drm/{drm.h,drm_mode.h} (0xB2, 32 bytes).
#ifdef P011_DRM_TRACE
#include <sys/syscall.h>
#include <unistd.h>
#include <cerrno>
#include <cstdint>
#include <mutex>
#include <algorithm>
namespace p011_drm_trace {
struct DumbRequest {uint32_t height,width,bpp,flags,handle,pitch;uint64_t size;};
static_assert(sizeof(DumbRequest)==32,"DRM ABI size");
constexpr unsigned long create_dumb=0xc02064b2UL;
struct Row {uint32_t height,width,bpp,flags,pitch;uint64_t size;int result,error;};
static Row rows[128]{};static unsigned count=0;static std::mutex lock;
static void record(unsigned long request,unsigned long arg,int result,int error){
    if(request!=create_dumb||!arg||(result<0&&error==EFAULT))return;
    const auto&v=*reinterpret_cast<const DumbRequest*>(arg);
    std::lock_guard<std::mutex>guard(lock);
    rows[count++%128]={v.height,v.width,v.bpp,v.flags,v.pitch,v.size,result,result<0?error:0};
}
static J snapshot(){
    J entries=J::array();std::lock_guard<std::mutex>guard(lock);
    for(unsigned i=count>128?count-128:0;i<count;i++){const auto&r=rows[i%128];entries.push_back({{"width",r.width},{"height",r.height},{"bpp",r.bpp},{"flags",r.flags},{"pitch",r.pitch},{"size",r.size},{"result",r.result},{"errno",r.error}});}
    return {{"diagnostic_only",true},{"requests_modified",false},{"create_dumb_calls",count},{"last_requests",entries}};
}
}
#ifndef P011_IOCTL_CALL
#define P011_IOCTL_CALL(fd,request,arg) ::syscall(SYS_ioctl,fd,request,arg)
#endif
// Fixed register ABI avoids dereferencing unknown variadic ioctl arguments.
// On ARM EABI, unused r2 is passed through but ignored by zero-argument ioctls.
extern "C" int p011_ioctl_forward(int,unsigned long,unsigned long) noexcept asm("ioctl");
extern "C" int p011_ioctl_forward(int fd,unsigned long request,unsigned long arg) noexcept {
    int result=int(P011_IOCTL_CALL(fd,request,arg));int error=errno;
    p011_drm_trace::record(request,arg,result,error);errno=error;return result;
}
#endif
