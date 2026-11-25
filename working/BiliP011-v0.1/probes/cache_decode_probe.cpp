// SPDX-License-Identifier: LGPL-2.1-or-later
// Finite generated-fixture decode. No network, sound, display, stock UI switch.
#include "omx_cache_bridge.h"
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <regex>
#include <set>
#include <string>
#include <fcntl.h>
#include <dirent.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <unistd.h>
using J=nlohmann::json;
static volatile sig_atomic_t stopped=0;
static void stop(int){stopped=1;}
static bool vsp_open(){
    DIR*dir=opendir("/proc/self/fd");if(!dir)return false;bool found=false;
    while(auto*entry=readdir(dir)){
        char link[256];std::string path="/proc/self/fd/"+std::string(entry->d_name);
        auto n=readlink(path.c_str(),link,sizeof(link)-1);if(n>0){link[n]=0;if(strstr(link,"sprd_vsp"))found=true;}
    }closedir(dir);return found;
}
static bool libraries(const std::string&root){
    std::ifstream maps("/proc/self/maps");std::string line;bool plugin=false,hardware=false;
    while(std::getline(maps,line)){
        if(line.find("/libgstomx.so")!=line.npos){if(line.find(root+"/libgstomx.so")==line.npos)return false;plugin=true;}
        if(line.find("/libomx_avcdec_hw_sprd.so")!=line.npos)hardware=true;
    }return plugin&&hardware;
}
struct Pipeline{
    GstElement*value=nullptr;GstElement*sink=nullptr;GstElement*decoder=nullptr;GstBus*bus=nullptr;
    ~Pipeline(){if(value){gst_element_set_state(value,GST_STATE_NULL);if(bus)gst_object_unref(bus);if(sink)gst_object_unref(sink);if(decoder)gst_object_unref(decoder);gst_object_unref(value);}}
};
int main(int argc,char**argv){
    if(argc!=2)return 2;int parent=atoi(argv[1]);prctl(PR_SET_PDEATHSIG,SIGTERM);
    const char*raw=getenv("P011_CACHE_PROBE_ROOT"),*mode=getenv("P011_CACHE_PROBE_MODE");
    const char*check=getenv("P011_CACHE_PROBE_CHECK");
    if(parent<=1||getppid()!=parent||!raw||!mode||!std::regex_match(raw,std::regex("/mnt/data/p011-toolbox/ion-cache-probe-[a-f0-9]{24}"))||
       (strcmp(mode,"cached")&&strcmp(mode,"uncached"))||!check||
       (strcmp(check,"pixels")&&strcmp(check,"timing")))return 3;
    const bool hash_pixels=!strcmp(check,"pixels");
    rlimit core{0,0},cpu{40,45},files{33554432,33554432};
    if(setrlimit(RLIMIT_CORE,&core)||setrlimit(RLIMIT_CPU,&cpu)||setrlimit(RLIMIT_FSIZE,&files))return 5;
    std::string root=raw;
    int protocol=fcntl(1,F_DUPFD_CLOEXEC,10),nullfd=open("/dev/null",O_WRONLY);
    if(protocol<0||nullfd<0)return 4;dup2(nullfd,1);dup2(nullfd,2);if(nullfd!=protocol)close(nullfd);
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGALRM,stop);alarm(35);
    J result={{"passed",false},{"window_opened",false},{"network_media",false},{"cached",!strcmp(mode,"cached")},
              {"pixels_checked",hash_pixels},{"frames",J::array()}};
    int code=0;bool real_hardware=false,eos=false;
    auto begin=g_get_monotonic_time();
    try{
        setenv("GST_PLUGIN_PATH_1_0",raw,1);setenv("GST_REGISTRY_FORK","no",1);
        setenv("GST_REGISTRY",(root+"/gst-registry.bin").c_str(),1);setenv("GST_DEBUG","0",1);
        gst_init(nullptr,nullptr);
        Pipeline p;GError*error=nullptr;
        std::string description="filesrc location="+root+"/input.mp4 ! qtdemux ! h264parse ! omxh264dec name=decoder ! appsink name=sample sync=false max-buffers=2 drop=false";
        p.value=gst_parse_launch(description.c_str(),&error);if(error){g_error_free(error);throw 10;}if(!p.value)throw 11;
        p.sink=gst_bin_get_by_name(GST_BIN(p.value),"sample");p.decoder=gst_bin_get_by_name(GST_BIN(p.value),"decoder");
        p.bus=gst_element_get_bus(p.value);if(!p.sink||!p.bus||!p.decoder)throw 12;
        if(gst_element_set_state(p.value,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)throw 13;
        uint64_t previous=0;std::set<std::string>unique;gint64 first_sample=0,last_sample=0,hash_us=0;
        while(!stopped&&g_get_monotonic_time()-begin<30000000){
            while(auto*message=gst_bus_pop(p.bus)){
                if(GST_MESSAGE_TYPE(message)==GST_MESSAGE_ERROR){
                    GError*issue=nullptr;gchar*debug=nullptr;gst_message_parse_error(message,&issue,&debug);
                    if(issue){result["gst_error_code"]=issue->code;result["gst_error_message"]=std::string(issue->message).substr(0,512);g_error_free(issue);}
                    if(debug)result["gst_error_debug"]=std::string(debug).substr(0,1024);
                    g_free(debug);gst_message_unref(message);throw 14;
                }
                gst_message_unref(message);
            }
            GstSample*sample=gst_app_sink_try_pull_sample(GST_APP_SINK(p.sink),50000000);
            if(!sample){if(gst_app_sink_is_eos(GST_APP_SINK(p.sink))){eos=true;break;}continue;}
            GstCaps*caps=gst_sample_get_caps(sample);GstBuffer*buffer=gst_sample_get_buffer(sample);GstVideoInfo info;
            gst_video_info_init(&info);GstMapInfo map=GST_MAP_INFO_INIT;
            bool valid=caps&&buffer&&gst_video_info_from_caps(&info,caps)&&info.width==960&&info.height==540&&
                GST_VIDEO_INFO_FORMAT(&info)==GST_VIDEO_FORMAT_NV12&&gst_buffer_get_size(buffer)==777600&&
                GST_VIDEO_INFO_PLANE_STRIDE(&info,0)==960&&GST_VIDEO_INFO_PLANE_STRIDE(&info,1)==960&&
                GST_VIDEO_INFO_PLANE_OFFSET(&info,1)==518400&&gst_buffer_map(buffer,&map,GST_MAP_READ);
            if(!valid){gst_sample_unref(sample);throw 15;}
            uint64_t pts=GST_BUFFER_PTS(buffer);
            last_sample=g_get_monotonic_time();if(!first_sample)first_sample=last_sample;
            char*hash=hash_pixels?g_compute_checksum_for_data(G_CHECKSUM_SHA256,map.data,map.size):nullptr;
            if(hash_pixels)hash_us+=g_get_monotonic_time()-last_sample;
            gst_buffer_unmap(buffer,&map);gst_sample_unref(sample);
            if(hash_pixels&&!hash)throw 16;std::string digest=hash?hash:"";g_free(hash);
            if(!GST_CLOCK_TIME_IS_VALID(pts)||(!result["frames"].empty()&&pts<=previous)||result["frames"].size()>=240)throw 17;
            previous=pts;if(hash_pixels)unique.insert(digest);result["frames"].push_back({{"pts_ns",pts},{"sha256",digest}});
            if(result["frames"].size()==1)real_hardware=libraries(root)&&vsp_open();
        }
        result["unique_frames"]=unique.size();result["eos"]=eos;
        result["hash_ms"]=hash_us/1000.0;result["sample_span_ms"]=(last_sample-first_sample)/1000.0;
        result["unclocked_sample_fps"]=last_sample>first_sample?239000000.0/(last_sample-first_sample):0.0;
        if(stopped||!eos||result["frames"].size()!=240||(hash_pixels&&unique.size()<200)||!real_hardware)throw 18;
        GstStructure*profile=nullptr;g_object_get(p.decoder,"p011-probe-profile",&profile,nullptr);
        if(!profile)throw 20;
        result["profile"]=J::object();bool profile_ok=true;
        for(const char*group:{"loop","acquire","match","fill","copy","allocate","push","release"})
            for(const char*field:{"count","wall_ns","cpu_ns"}){
                std::string key=std::string(group)+"_"+field;guint64 value=0;
                if(!gst_structure_get_uint64(profile,key.c_str(),&value))profile_ok=false;
                else result["profile"][key]=value;
            }
        guint64 errors=0;if(!gst_structure_get_uint64(profile,"clock_errors",&errors)||errors)profile_ok=false;
        gst_structure_free(profile);
        if(!profile_ok||result["profile"].value("copy_count",uint64_t(0))!=240)throw 21;
        if(gst_element_set_state(p.value,GST_STATE_NULL)==GST_STATE_CHANGE_FAILURE)throw 19;
    }catch(int value){code=value;}catch(...){code=99;}
    auto stats=p011_cache_snapshot();
    result["cache"]={{"changed_allocations",stats.changed_allocations},{"control_allocations",stats.control_allocations},
        {"forwarded_allocations",stats.forwarded_allocations},{"registered",stats.registered},{"forgotten",stats.forgotten},
        {"active",stats.active},{"read_begin",stats.read_begin},{"read_end",stats.read_end},{"sync_errors",stats.sync_errors},
        {"ownership_errors",stats.ownership_errors},{"sync_ns",stats.sync_ns}};
    result["hardware_confirmed"]=real_hardware;result["elapsed_ms"]=(g_get_monotonic_time()-begin)/1000;
    result["error"]=code;result["stopped"]=bool(stopped);
    result["passed"]=code==0&&stats.registered>0&&stats.active==0&&stats.registered==stats.forgotten&&stats.read_begin==240&&
        stats.read_end==240&&stats.sync_errors==0&&stats.ownership_errors==0&&
        (!strcmp(mode,"cached")?stats.changed_allocations==stats.registered&&stats.control_allocations==0:
                               stats.control_allocations==stats.registered&&stats.changed_allocations==0);
    std::string output="CACHE_DECODE="+result.dump()+"\n";size_t sent=0;
    while(sent<output.size()){auto n=write(protocol,output.data()+sent,output.size()-sent);if(n>0)sent+=n;else if(errno!=EINTR)break;}
    close(protocol);return result["passed"].get<bool>()?0:1;
}
