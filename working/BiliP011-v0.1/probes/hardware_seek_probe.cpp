// SPDX-License-Identifier: GPL-3.0-or-later
// Drive the exact production worker without creating a display/GL context.
// URLs arrive only on stdin; emitted evidence contains numbers/booleans only.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <regex>
#include <signal.h>
#include <string>
#include <sys/prctl.h>
#include <unistd.h>
#include <nlohmann/json.hpp>
using J=nlohmann::json;
static std::string root;
#include "../client/hardware_client.hpp"
static volatile sig_atomic_t stopping=0;
static void stop(int){stopping=1;}
static uint32_t ticks(){return uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());}
int main(int argc,char**argv){
    if(argc!=2)return 2;
    pid_t parent=atoi(argv[1]);prctl(PR_SET_PDEATHSIG,SIGTERM);
    if(parent<=1||getppid()!=parent)return 90;
    const char*directory=getenv("P011_SEEK_PROBE_ROOT");if(!directory)return 2;root=directory;
    if(!std::regex_match(root,std::regex("/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}")))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGALRM,stop);signal(SIGPIPE,SIG_IGN);alarm(48);
    J report={{"passed",false},{"window_opened",false},{"audible_audio_requested",false},{"physical_acceptance",false}};
    HardwareBackend hw;
    try{
        std::string line;char ch;while(read(0,&ch,1)==1&&ch!='\n'){if(line.size()>=32768)throw 1;line+=ch;}
        J request=J::parse(line);line.clear();
        const bool rate_probe=request.value("rate_probe",false);request.erase("rate_probe");
        const bool private_omx=request.value("private_omx_probe",false);
        const bool throughput_probe=request.value("throughput_probe",false);
        if(throughput_probe&&(!rate_probe||!private_omx||request.value("nonref_probe",false)))throw 3;
        report["unsynchronized_throughput_probe"]=throughput_probe;
        request["muted"]=true;request["paused"]=false;request["start"]=0;request["volume"]=100;request["loop"]=false;request["limit"]=40;
        if(!hw.open(request))throw 2;request.clear();
        const uint32_t began=ticks();int stage=0;unsigned consumed=0,frames_at_seek=0;double target=0,last_frame=0;
        uint32_t rate_begin=0,previous_status=0;unsigned rate_frames=0,rate_samples=0;double rate_position=0,rate_cpu=0;
        unsigned queue_samples=0,queue_nonempty=0,network_nonempty=0;uint64_t queue_total=0;
        J rate_start=J::object();
        while(!stopping&&ticks()-began<35000){
            hw.poll(ticks());if(hw.failed||hw.eof)break;
            if(auto*f=hw.frame()){last_frame=f->pts;consumed++;hw.release(f);}
            const auto&s=hw.status;double pos=s.value("position",0.),duration=s.value("duration",0.);bool paused=s.value("paused",false);
            if(rate_probe){
                if(!rate_begin&&s.value("ready",false)&&pos>=6){
                    rate_begin=ticks();rate_frames=consumed;rate_position=pos;rate_start=s;previous_status=hw.received_at;stage=1;
                }
                if(rate_begin&&hw.received_at!=previous_status){
                    previous_status=hw.received_at;rate_cpu+=s.value("cpu_percent",0.);rate_samples++;
                    if(s.contains("video_queued_buffers")&&s.contains("video_network_bytes")){
                        queue_samples++;auto q=s.value("video_queued_buffers",0u);queue_nonempty+=q>0;queue_total+=q;
                        network_nonempty+=s.value("video_network_bytes",0u)>0;
                    }
                }
                if(rate_begin&&ticks()-rate_begin>=12000){
                    const double elapsed=(ticks()-rate_begin)/1000.;
                    J rate={{"elapsed_seconds",elapsed},{"consumed_frames",consumed-rate_frames},
                            {"consumed_fps",(consumed-rate_frames)/elapsed},{"position_advance",pos-rate_position},
                            {"source_fps",s.value("source_fps",0.)},{"status_samples",rate_samples},
                            {"mean_reported_worker_cpu_percent",rate_samples?rate_cpu/rate_samples:0.}};
                    rate.update({{"queue_samples",queue_samples},{"queue_nonempty_samples",queue_nonempty},
                                 {"network_nonempty_samples",network_nonempty},{"mean_video_queued_buffers",queue_samples?double(queue_total)/queue_samples:0.}});
                    for(const char*key:{"decoded","encoded","delivered","drops","decoder_drops","copy_us","map_us","pull_us"})
                        rate[key]=s.value(key,0ULL)-rate_start.value(key,0ULL);
                    for(auto it=s.begin();it!=s.end();++it)
                        if((it.key().rfind("omx_profile_",0)==0||it.key().rfind("encoded_",0)==0)&&it.value().is_number_unsigned())
                            rate[it.key()]=it.value().get<uint64_t>()-rate_start.value(it.key(),0ULL);
                    report["rate"]=rate;report["passed"]=!paused&&pos-rate_position>=10&&consumed-rate_frames>=30&&
                        s.value("hardware_library",false)&&s.value("vsp_open",false);stage=4;break;
                }
            }
            else if(stage==0&&s.value("ready",false)&&pos>=6&&duration>0){hw.command({{"op","pause"},{"value",true}});stage=1;}
            else if(stage==1&&paused){target=duration*.25;frames_at_seek=consumed;hw.command({{"op","seek"},{"value",target}});stage=2;}
            else if(stage==2&&paused&&std::abs(pos-target)<2&&std::abs(last_frame-target)<2&&consumed>frames_at_seek){
                report["paused_position"]=pos;report["paused_frame_pts"]=last_frame;
                hw.command({{"op","pause"},{"value",false}});stage=3;
            }else if(stage==3&&!paused&&pos>=target+1.5&&last_frame>=target+1.&&consumed>=frames_at_seek+15){
                report["passed"]=s.value("hardware_library",false)&&s.value("vsp_open",false);stage=4;break;
            }
            usleep(5000);
        }
        report["stage"]=stage;report["target"]=target;report["consumed_frames"]=consumed;report["frames_at_seek"]=frames_at_seek;
        report["last_frame_pts"]=last_frame;report["elapsed_ms"]=ticks()-began;report["worker_failed"]=hw.failed;report["worker_error"]=hw.error;
        report["worker_status"]=J::object();for(auto it=hw.status.begin();it!=hw.status.end();++it)
            if(it.value().is_number()||it.value().is_boolean())report["worker_status"][it.key()]=it.value();
        report["seek"]=hw.seek_detail;report["error"]=hw.error_detail;
        if(throughput_probe&&(!hw.status.value("unsynchronized_throughput_probe",false)||
            hw.status.value("encoded_nonref_skipped",0u)!=0))report["passed"]=false;
        if(private_omx){report["private_plugin_loaded"]=hw.private_plugin_loaded();if(!hw.private_plugin_loaded())report["passed"]=false;}
    }catch(int code){report["probe_error"]=code;}catch(...){report["probe_error"]=99;}
    hw.close();report["lifecycle"]=hw.audit();
#ifdef P011_OUTPUT_CACHE_PROBE
    report["cache_final"]=hw.cache_final;
    auto final=hw.cache_final;bool enabled=report.value("worker_status",J::object()).value("output_cache_enabled",false);
    uint64_t allocated=final.value("cache_registered",uint64_t(0)),reads=final.value("cache_read_begin",uint64_t(0));
    if(!final.value("cache_final",false)||!allocated||!reads||final.value("cache_active",uint64_t(1))||
       final.value("cache_sync_errors",uint64_t(1))||final.value("cache_ownership_errors",uint64_t(1))||
       final.value("cache_forgotten",uint64_t(0))!=allocated||final.value("cache_read_end",uint64_t(0))!=reads||
       final.value("cache_changed_allocations",uint64_t(0))!=(enabled?allocated:0)||
       final.value("cache_control_allocations",uint64_t(0))!=(enabled?0:allocated))report["passed"]=false;
#endif
    report["ion_observations"]=hw.ion_observations;
    if(hw.audit().value("forced_kills",1u)||hw.audit().value("abnormal_exits",1u)||hw.audit().value("last_exit",-1)!=0)report["passed"]=false;
    std::cout<<"PROBE="<<report.dump()<<std::endl;
    return report.value("passed",false)?0:1;
}
