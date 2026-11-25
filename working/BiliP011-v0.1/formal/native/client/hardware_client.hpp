// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "hardware_protocol.hpp"
#include "hardware_clock.hpp"
#include <time.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <poll.h>
#include <cerrno>
#include <chrono>
#include <vector>
#ifdef P011_PRIVATE_OMX_PROBE
#include <fstream>
#endif
extern char**environ;

class HardwareBackend {
    pid_t pid=-1;int input=-1,output=-1,mem=-1;std::string buffer;
    p011_hw::Shared*shared=nullptr;
    unsigned starts=0,normal_exits=0,abnormal_exits=0,forced_kills=0,max_close_ms=0;
    int last_exit=-1,last_signal=0;
    void reaped(int result){last_exit=WIFEXITED(result)?WEXITSTATUS(result):-1;last_signal=WIFSIGNALED(result)?WTERMSIG(result):0;if(WIFEXITED(result))normal_exits++;else abnormal_exits++;}
public:
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
    J cache_final=J::object();
#endif
#ifdef P011_BUNDLED_OUTPUT_CACHE
    unsigned cache_sessions=0,cache_failures=0;bool cache_pending=false;
#endif
    bool active=false,failed=false,eof=false,got_status=false;
    int error=0;J status=J::object(),error_detail=J::object(),seek_detail=J::object();uint32_t received_at=0;uint64_t ui_drops=0;double displayed_pts=0;
    ~HardwareBackend(){close();}
    J audit()const{
        J result={{"starts",starts},{"normal_exits",normal_exits},{"abnormal_exits",abnormal_exits},{"forced_kills",forced_kills},{"max_close_ms",max_close_ms},{"last_exit",last_exit},{"last_signal",last_signal}};
#ifdef P011_BUNDLED_OUTPUT_CACHE
        result["cache_sessions"]=cache_sessions;result["cache_failures"]=cache_failures;result["cache_last"]=cache_final;
#endif
        return result;
    }
    bool verified()const{
        bool ok=active&&status.value("hardware_library",false)&&status.value("vsp_open",false);
#ifdef P011_BUNDLED_OMX
        ok=ok&&status.value("omx_private_plugin",false);
#endif
#ifdef P011_BUNDLED_OUTPUT_CACHE
        ok=ok&&status.value("output_cache_feature",false)&&!status.value("cache_sync_errors",uint64_t(1))&&
            !status.value("cache_ownership_errors",uint64_t(1));
#endif
        return ok;
    }
    uint64_t sample_age_us()const{
        auto sampled=status.value("position_sample_us",uint64_t(0));struct timespec ts{};
        if(!sampled||clock_gettime(CLOCK_MONOTONIC,&ts))return 0;
        uint64_t now=uint64_t(ts.tv_sec)*1000000+ts.tv_nsec/1000;
        return now>=sampled?now-sampled:0;
    }
    double position()const{
        auto sampled=status.value("position_sample_us",uint64_t(0));
        bool playing=active&&status.value("ready",false)&&!status.value("paused",true)&&!status.value("seeking",false)&&!failed&&!eof;
        return p011_hw::current_position(status.value("position",0.),status.value("duration",0.),playing,sampled,sampled+sample_age_us(),status.value("rate",1.));
    }
#ifdef P011_PRIVATE_OMX_PROBE
    J ion_observations=J::object();
    bool private_plugin_loaded()const{
        if(pid<=0)return false;std::ifstream file("/proc/"+std::to_string(pid)+"/maps");std::string line;bool found=false;
        while(std::getline(file,line))if(line.find("/libgstomx.so")!=line.npos){
            if(line.find(root+"/libgstomx.so")==line.npos)return false;
            found=true;
        }
        return found;
    }
#endif
    void close(){
        auto began=std::chrono::steady_clock::now();
        if(input>=0){::close(input);input=-1;}
        if(pid>0){
            int result=0;kill(pid,SIGTERM);
            // souphttpsrc may still be inside its bounded 8s startup. Allow
            // NULL-state teardown to release VSP/ION; service/guardian use
            // longer enclosing deadlines. Forced exit remains a failed gate.
            for(int i=0;i<1000;i++){
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
                drain_events(0);
#endif
                auto n=waitpid(pid,&result,WNOHANG);if(n==pid){reaped(result);pid=-1;break;}if(n<0&&errno==ECHILD){abnormal_exits++;pid=-1;break;}usleep(10000);}
            if(pid>0){forced_kills++;kill(pid,SIGKILL);pid_t n;do{n=waitpid(pid,&result,0);}while(n<0&&errno==EINTR);if(n==pid)reaped(result);else abnormal_exits++;pid=-1;}
        }
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
        drain_events(0);
#endif
#ifdef P011_BUNDLED_OUTPUT_CACHE
        if(cache_pending){
            cache_pending=false;cache_sessions++;bool valid=!failed&&cache_final.value("cache_final",false)&&last_exit==0;
            for(const char*key:{"cache_active","cache_fallback_active","cache_sync_errors","cache_ownership_errors"})
                valid=valid&&cache_final.value(key,uint64_t(1))==0;
            for(auto pair:{std::make_pair("cache_registered","cache_forgotten"),std::make_pair("cache_read_begin","cache_read_end"),
                           std::make_pair("cache_fallback_registered","cache_fallback_forgotten"),std::make_pair("cache_fallback_read_begin","cache_fallback_read_end")})
                valid=valid&&cache_final.value(pair.first,uint64_t(0))==cache_final.value(pair.second,uint64_t(1));
            if(!valid){cache_failures++;failed=true;error=56;}
        }
#endif
        if(output>=0){::close(output);output=-1;}
        if(shared){munmap(shared,sizeof(*shared));shared=nullptr;}
        if(mem>=0){::close(mem);mem=-1;}active=false;buffer.clear();
        max_close_ms=std::max(max_close_ms,unsigned(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count()));
    }
    bool command(const J&value){
        if(input<0)return false;std::string data=value.dump()+"\n";if(data.size()>32768)return false;
        // After the initial private packet all commands fit PIPE_BUF and
        // use a nonblocking pipe. A stuck worker must not freeze touch input.
        if(active&&data.size()>4096)return false;
        size_t at=0;while(at<data.size()){ssize_t n=write(input,data.data()+at,data.size()-at);if(n>0)at+=n;else if(n<0&&errno==EINTR)continue;else{failed=true;error=55;return false;}}return true;
    }
    bool open(const J&request){
        close();status=J::object();error_detail=J::object();seek_detail=J::object();failed=false;eof=false;error=0;got_status=false;ui_drops=0;displayed_pts=0;
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
        cache_final=J::object();
#endif
#ifdef P011_OUTPUT_CACHE_PROBE
        const std::string cache_mode=request.value("output_cache_mode","");
        if((cache_mode!="cached"&&cache_mode!="uncached")||!request.value("private_omx_probe",false)||
           !request.value("fused_half_probe",false)||!request.value("muted",false)||request.value("limit",0)>40||
           request.value("limit",0)<10||request.value("width",0)!=1920||request.value("height",0)!=1080||
           request.value("ion_observe",false)||request.value("nonref_probe",false)||request.value("high_fps_compat",false))return false;
#endif
        char exe[4096];ssize_t len=readlink("/proc/self/exe",exe,sizeof(exe)-1);if(len<=0)return false;exe[len]=0;std::string path=exe;path=path.substr(0,path.rfind('/'))+"/bili-hw";
#ifdef P011_BUNDLED_OMX
        // Fixed sibling of this verified immutable media bundle, not a path
        // from the playback request or the caller's environment.
        std::string plugin_dir=path.substr(0,path.rfind('/'));plugin_dir=plugin_dir.substr(0,plugin_dir.rfind('/'))+"/lib/gst";
        struct stat plugin_info{};
        if(lstat((plugin_dir+"/libgstomx.so").c_str(),&plugin_info)||!S_ISREG(plugin_info.st_mode)||plugin_info.st_uid!=getuid())return false;
#endif
#ifdef P011_PRIVATE_OMX_PROBE
        if(request.value("ion_observe",false)){
            struct stat observed{};
            if(!request.value("private_omx_probe",false)||!request.value("muted",false)||request.value("limit",0)<=0||request.value("limit",0)>40||
               lstat((root+"/libmemion-observer.so").c_str(),&observed)||!S_ISREG(observed.st_mode)||observed.st_uid!=getuid())return false;
        }
#endif
        mem=int(syscall(SYS_memfd_create,"p011-video",1));if(mem<0||ftruncate(mem,sizeof(p011_hw::Shared))){close();return false;}
        shared=static_cast<p011_hw::Shared*>(mmap(nullptr,sizeof(*shared),PROT_READ|PROT_WRITE,MAP_SHARED,mem,0));if(shared==MAP_FAILED){shared=nullptr;close();return false;}
        memset(shared,0,sizeof(*shared));shared->signature=p011_hw::magic;shared->revision=p011_hw::version;
        int commands[2],events[2];if(pipe2(commands,O_CLOEXEC)){close();return false;}if(pipe2(events,O_CLOEXEC)){::close(commands[0]);::close(commands[1]);close();return false;}
        std::string parent=std::to_string(getpid());char*args[]={const_cast<char*>(path.c_str()),const_cast<char*>(parent.c_str()),nullptr};
        std::vector<std::string>env;for(char**entry=environ;*entry;entry++){std::string s=*entry;if(s.rfind("LD_",0)!=0&&s.rfind("GST_",0)!=0)env.push_back(s);}
        env.push_back("GST_DEBUG=0");env.push_back("GST_REGISTRY="+root+"/gst-hw-registry.bin");env.push_back("GST_REGISTRY_FORK=no");
#ifdef P011_BUNDLED_OMX
        env.push_back("GST_PLUGIN_PATH_1_0="+plugin_dir);
#endif
#ifdef P011_PRIVATE_OMX_PROBE
        // Compiled only into the finite no-window diagnostic driver.
        if(request.value("private_omx_probe",false))env.push_back("GST_PLUGIN_PATH_1_0="+root);
        if(request.value("ion_observe",false)){
            env.push_back("LD_PRELOAD="+root+"/libmemion-observer.so");ion_observations=J::object();
        }
#ifdef P011_OUTPUT_CACHE_PROBE
        env.erase(std::remove_if(env.begin(),env.end(),[](const std::string&value){return value.rfind("P011_CACHE_",0)==0;}),env.end());
        env.push_back("P011_CACHE_PROBE_ROOT="+root);env.push_back("P011_CACHE_PROBE_MODE="+cache_mode);
#endif
#endif
        std::vector<char*>envp;for(auto&s:env)envp.push_back(&s[0]);envp.push_back(nullptr);
        // Duplicate above protocol descriptors before fork, avoiding dup2
        // collisions; child only uses async-signal-safe descriptor/exec calls.
        int cmd=fcntl(commands[0],F_DUPFD_CLOEXEC,10),frame=fcntl(mem,F_DUPFD_CLOEXEC,10),event=fcntl(events[1],F_DUPFD_CLOEXEC,10);
        struct rlimit limit{};getrlimit(RLIMIT_NOFILE,&limit);int maxfd=std::min<rlim_t>(limit.rlim_cur,65536);
        pid=fork();if(pid==0){
            if(cmd<0||frame<0||event<0)_exit(90);
            dup2(cmd,0);dup2(frame,3);dup2(event,4);
            for(int fd=5;fd<maxfd;fd++)::close(fd);
            execve(path.c_str(),args,envp.data());_exit(91);
        }
        for(int fd:{cmd,frame,event,commands[0],events[1]})if(fd>=0)::close(fd);
        input=commands[1];output=events[0];fcntl(output,F_SETFL,fcntl(output,F_GETFL)|O_NONBLOCK);
        if(pid>0){starts++;
#ifdef P011_BUNDLED_OUTPUT_CACHE
            cache_pending=true;
#endif
        }
        if(pid<0||!command(request)){close();return false;}
        fcntl(input,F_SETFL,fcntl(input,F_GETFL)|O_NONBLOCK);active=true;return true;
    }
    void drain_events(uint32_t now){
        if(output<0)return;char bytes[4096];ssize_t n;
        while((n=read(output,bytes,sizeof(bytes)))>0){buffer.append(bytes,n);if(buffer.size()>32768){failed=true;error=51;return;}}
        size_t line;while((line=buffer.find('\n'))!=buffer.npos){J v=J::parse(buffer.substr(0,line),nullptr,false);buffer.erase(0,line+1);if(!v.is_object()){failed=true;error=52;return;}
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
            if(v.value("cache_final",false)){
                bool numerical=true;for(auto it=v.begin();it!=v.end();++it)numerical&=it.value().is_number_unsigned()||it.value().is_boolean();
                if(!numerical||!cache_final.empty()){failed=true;error=52;return;}cache_final=v;
            }
#endif
#ifdef P011_PRIVATE_OMX_PROBE
            if(v.contains("ion_allocation_event")&&ion_observations.size()<64){
                bool numeric=v.size()==5;for(const char*key:{"ion_allocation_event","bytes","heapmask","mapping_flags","result"})numeric&=v.contains(key)&&v[key].is_number_integer();
                if(!numeric){failed=true;error=52;return;}
                ion_observations[std::to_string(v["ion_allocation_event"].get<unsigned>())]=v;
            }
#endif
            if(v.contains("error")){
                failed=true;error=v.value("error",50);error_detail["error"]=error;
                for(const char*key:{"gst_code","gst_domain_kind","gst_source_role","gst_phase"})
                    if(v.contains(key)&&v[key].is_number_integer())error_detail[key]=v[key];
                for(const char*key:{"gst_not_linked","gst_not_negotiated","gst_range","gst_seek","gst_timeout","gst_stream_error"})
                    if(v.contains(key)&&v[key].is_boolean())error_detail[key]=v[key];
            }
            if(v.value("eof",false))eof=true;
            if(v.contains("seek_event")){
                if(v.value("seek_event",0)==1)seek_detail=J::object();
                for(const char*key:{"seek_event","seek_requests","seek_target","seek_paused","seek_accepted","seek_call_us","seek_async_done",
                        "seek_seq","seek_before_video_buffers","seek_before_audio_buffers","seek_async_seq","seek_async_from_pipeline",
                        "seek_pipeline_state","seek_pipeline_pending","seek_state_result","seek_pipeline_position","seek_sample_pts",
                        "seek_video_pull_mode","seek_audio_pull_mode","seek_network_ring_bytes",
                        "seek_video_position","seek_audio_position","seek_video_segments","seek_video_flush_start","seek_video_flush_stop",
                        "seek_video_buffers","seek_video_segment_seq","seek_video_segment_start","seek_video_segment_time","seek_video_buffer_pts",
                        "seek_audio_segments","seek_audio_flush_start","seek_audio_flush_stop","seek_audio_buffers","seek_audio_segment_seq",
                        "seek_audio_segment_start","seek_audio_segment_time","seek_audio_buffer_pts"})
                    if(v.contains(key)&&(v[key].is_number()||v[key].is_boolean()))seek_detail[key]=v[key];
            }
            if(v.contains("ready")){status=v;got_status=true;received_at=now;}
        }
    }
    void poll(uint32_t now){
        if(!active)return;drain_events(now);
        int result=0;if(pid>0&&waitpid(pid,&result,WNOHANG)==pid){reaped(result);pid=-1;if(!eof){failed=true;error=WIFEXITED(result)?WEXITSTATUS(result):53;}}
    }
    p011_hw::Frame*frame(){
        if(!shared)return nullptr;p011_hw::Frame*best=nullptr;
        for(auto&f:shared->frames)if(p011_hw::read(f.state)==p011_hw::Ready&&(!best||f.serial>best->serial))best=&f;
        if(!best||!p011_hw::take(best->state,p011_hw::Ready,p011_hw::Reading))return nullptr;
        for(auto&f:shared->frames)if(&f!=best&&p011_hw::take(f.state,p011_hw::Ready,p011_hw::Free))ui_drops++;
        if(!p011_hw::valid(best->width,best->height,best->bytes)){p011_hw::set(best->state,p011_hw::Free);failed=true;error=54;return nullptr;}return best;
    }
    void release(p011_hw::Frame*frame){if(frame){displayed_pts=frame->pts;p011_hw::set(frame->state,p011_hw::Free);}}
};
