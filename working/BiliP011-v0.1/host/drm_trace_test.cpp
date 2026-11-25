// SPDX-License-Identifier: GPL-3.0-or-later
#include <nlohmann/json.hpp>
#include <cerrno>
#include <cassert>
#include <iostream>
using J=nlohmann::json;
static int calls=0,last_fd;static unsigned long last_request,last_arg;
static long fake_ioctl(int fd,unsigned long request,unsigned long arg){calls++;last_fd=fd;last_request=request;last_arg=arg;errno=ENOMEM;return -1;}
#define P011_DRM_TRACE 1
#define P011_IOCTL_CALL(fd,request,arg) fake_ioctl(fd,request,arg)
#include "../client/drm_trace.hpp"
int main(){
    using namespace p011_drm_trace;
    DumbRequest input{480,800,32,0,42,3200,1536000};
    auto arg=reinterpret_cast<unsigned long>(&input);
    assert(p011_ioctl_forward(27,create_dumb,arg)==-1&&errno==ENOMEM);
    assert(calls==1&&last_fd==27&&last_request==create_dumb&&last_arg==arg);
    assert(input.handle==42&&input.size==1536000);
    auto s=snapshot();assert(s["create_dumb_calls"]==1&&s["last_requests"][0]["errno"]==ENOMEM);
    assert(!s["last_requests"][0].contains("handle"));
    record(123,1,-1,EINVAL);record(create_dumb,1,-1,EFAULT);
    assert(snapshot()["create_dumb_calls"]==1);
    for(int i=0;i<200;i++)record(create_dumb,arg,0,0);
    s=snapshot();assert(s["create_dumb_calls"]==201&&s["last_requests"].size()==128);
    std::cout<<"DRM pass-through, errno, invalid-pointer exclusion, privacy and bounded-ring checks passed\n";
}
