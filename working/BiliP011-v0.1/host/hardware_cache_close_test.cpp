// SPDX-License-Identifier: GPL-3.0-or-later
// PC-only protocol/close test. The mock performs no media/network/device work.
#include <algorithm>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iostream>
#include <string>
#include <cassert>
#include <fcntl.h>
#include <unistd.h>
#include <nlohmann/json.hpp>
using J=nlohmann::json;
#ifdef P011_MOCK_CACHE_WORKER
static volatile sig_atomic_t stop_requested=0;
static void stop(int){stop_requested=1;}
static void send(const J&value){std::string text=value.dump()+"\n";assert(write(4,text.data(),text.size())==ssize_t(text.size()));}
int main(){
    signal(SIGTERM,stop);signal(SIGINT,stop);alarm(8);
    std::string line;std::getline(std::cin,line);auto request=J::parse(line);
    send({{"ready",true},{"paused",false}});
    while(!stop_requested)usleep(1000);
    for(unsigned i=0;i<1000;i++)send({{"close_progress",i}});
    send({{"cache_final",true},{"cache_active",request.value("bad_final",false)?uint64_t(1):uint64_t(0)},
          {"cache_fallback_active",uint64_t(0)},{"cache_sync_errors",uint64_t(0)},{"cache_ownership_errors",uint64_t(0)},
          {"cache_registered",uint64_t(20)},{"cache_forgotten",uint64_t(20)},
          {"cache_read_begin",uint64_t(30)},{"cache_read_end",uint64_t(30)},
          {"cache_fallback_registered",uint64_t(10)},{"cache_fallback_forgotten",uint64_t(10)},
          {"cache_fallback_read_begin",uint64_t(40)},{"cache_fallback_read_end",uint64_t(40)},
          {"cache_changed_allocations",request.value("output_cache_mode","")=="cached"?uint64_t(20):uint64_t(0)}});
}
#else
static std::string root;
#ifdef P011_MOCK_CACHE_BUNDLE
#define P011_BUNDLED_OUTPUT_CACHE 1
#else
#define P011_PRIVATE_OMX_PROBE 1
#define P011_OUTPUT_CACHE_PROBE 1
#endif
#include "../client/hardware_client.hpp"
int main(int argc,char**argv){
    (void)argc;root=argv[0];root.resize(root.rfind('/'));alarm(9);
    HardwareBackend hw;
    for(const char*mode:{"cached","uncached"}){
        J request={{"output_cache_mode",mode},{"private_omx_probe",true},{"fused_half_probe",true},
                   {"muted",true},{"limit",20},{"width",1920},{"height",1080}};
        assert(hw.open(request));
        for(unsigned i=0;i<2000&&!hw.got_status;i++){hw.poll(i);usleep(1000);}
        assert(hw.got_status);hw.close();
        assert(hw.cache_final.value("cache_final",false));
        assert(hw.cache_final.value("cache_active",1u)==0);
        assert(hw.cache_final.value("cache_changed_allocations",99u)==(!strcmp(mode,"cached")?20u:0u));
        assert(hw.audit()["last_exit"]==0&&hw.audit()["forced_kills"]==0&&hw.audit()["abnormal_exits"]==0);
    }
    assert(hw.audit()["starts"]==2&&hw.audit()["normal_exits"]==2);
#ifdef P011_MOCK_CACHE_BUNDLE
    assert(hw.audit()["cache_sessions"]==2&&hw.audit()["cache_failures"]==0);
    assert(hw.open({{"bad_final",true}}));
    for(unsigned i=0;i<2000&&!hw.got_status;i++){hw.poll(i);usleep(1000);}
    assert(hw.got_status);hw.close();
    assert(hw.audit()["cache_sessions"]==3&&hw.audit()["cache_failures"]==1&&hw.failed&&hw.error==56);
#endif
    std::cout<<"CACHE_CLOSE_PROTOCOL_PASS"<<std::endl;
}
#endif
