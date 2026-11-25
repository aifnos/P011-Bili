// SPDX-License-Identifier: LGPL-2.1-or-later
// Diagnostic executable only. Forward the exact pinned vendor call and errno.
// The three opaque-pointer ABIs and config int-pointer ABI were verified in the
// two pinned ARM DSOs. Observe that one input int only; never inspect a context,
// change an argument, or issue any additional frequency-setting request.
// An explicit diagnostic-only flag permits a bounded GET_DEV_FREQ query after
// a successful existing CONFIG_DEV_FREQ. Never infer success from POLL bits.
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "vsp_gap_stats.hpp"
#include "vsp_cycle_stats.hpp"
#include "omx_format_stats.hpp"

namespace {
using Call=int(*)(void*);
using FrequencyCall=int(*)(void*,int*);
static_assert(sizeof(int)==4,"Pinned vendor frequency argument is 32-bit");
struct Counter {uint64_t count=0,wall=0,cpu=0,max=0,bins[5]={0};};
Counter counters[3];uint64_t failures=0,clock_failures=0,origins[2]={0},release_failed=0;
VspGapStats gaps;uint64_t detailed_poll[8]={0};
thread_local VspGapState previous_poll;
VspCycleStats cycles;
thread_local VspCycleState current_cycle;
VspSequenceStats sequence;
thread_local VspSequenceState current_sequence;
struct FrequencyCounter {uint64_t calls=0,success=0,failed=0,null_arg=0,other=0,levels[16]={0},origins[2]={0};};
FrequencyCounter frequency;
struct ReadbackCounter {
    uint64_t eligible=0,skipped=0,calls=0,accepted=0,missing=0,failed=0,bad_errno=0,invalid=0,clock_errors=0;
    uint64_t wall=0,max=0,levels[16]={0};
};
ReadbackCounter readback;
uint64_t poll_results[5]={0},poll_other_min=UINT32_MAX,poll_other_max=0;
OmxFormatStats formats;
pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static bool enabled(){
#ifdef P011_VSP_PROFILE_MOCK
    return true;
#else
    static const bool value=[](){
        const char*flag=getenv("P011_VSP_WAIT_PROFILE"),*root=getenv("P011_SEEK_PROBE_ROOT");
        const char*prefix="/mnt/data/p011-toolbox/bili-seek-probe-";
        if(!flag||strcmp(flag,"1")||!root||strncmp(root,prefix,strlen(prefix)))return false;
        const char*token=root+strlen(prefix);if(strlen(token)!=24)return false;
        for(unsigned i=0;i<24;i++)if(!((token[i]>='a'&&token[i]<='f')||(token[i]>='0'&&token[i]<='9')))return false;
        char path[256];auto n=readlink("/proc/self/exe",path,sizeof(path)-1);
        if(n<=0||n>=ssize_t(sizeof(path)-1))return false;path[n]=0;
        const size_t size=strlen(root);return !strncmp(path,root,size)&&!strcmp(path+size,"/bili-hw");
    }();
    return value;
#endif
}
static bool stamp(clockid_t id,uint64_t&value){
    timespec ts{};if(clock_gettime(id,&ts))return false;
    value=uint64_t(ts.tv_sec)*1000000000+ts.tv_nsec;return true;
}
#ifdef P011_VSP_PROFILE_MOCK
extern "C" int p011_mock_vsp(unsigned,void*);
extern "C" int p011_mock_vsp_frequency(void*,int*);
extern "C" int p011_mock_vsp_readback(void*,int*);
#endif
#ifndef P011_VSP_PROFILE_MOCK
template<class T> static T original_symbol(const char*name,void*caller,unsigned&origin){
    // Resolve on the actual caller's already loaded DSO, not RTLD_NEXT:
    // both pinned vendor DSOs export the same symbol in local OMX scopes.
    static const char*paths[2]={"/usr/lib/libstagefright_sprd_h264dec.so","/usr/lib/libomx_avcdec_hw_sprd.so"};
    Dl_info info{};if(!dladdr(caller,&info)||!info.dli_fname)return nullptr;
    for(origin=0;origin<2;origin++)if(!strcmp(info.dli_fname,paths[origin]))break;
    if(origin>=2)return nullptr;
    void*handle=dlopen(paths[origin],RTLD_LAZY|RTLD_NOLOAD);if(!handle)return nullptr;
    auto result=reinterpret_cast<T>(dlsym(handle,name));
    dlclose(handle);return result;
}
#endif
static bool readback_enabled(){
    const char*flag=getenv("P011_VSP_CLOCK_READBACK");
    return enabled()&&flag&&!strcmp(flag,"1");
}
static void observe_readback(void*object,void*caller,int configuration_result){
    // Both pinned GET wrappers accept (the same opaque VSP context, int*).
    // They discard ioctl's return value: sentinel, errno AND wrapper result
    // must all be checked. No context dereference or direct ioctl is used here.
    if(!readback_enabled())return;
    const int saved=errno;
    pthread_mutex_lock(&lock);
    if(configuration_result!=0){readback.skipped++;pthread_mutex_unlock(&lock);errno=saved;return;}
    const uint64_t ordinal=readback.eligible++;
    if(ordinal%64||readback.calls>=32){pthread_mutex_unlock(&lock);errno=saved;return;}
    readback.calls++;pthread_mutex_unlock(&lock);
    unsigned origin=0;
#ifdef P011_VSP_PROFILE_MOCK
    FrequencyCall call=p011_mock_vsp_readback;
#else
    FrequencyCall call=original_symbol<FrequencyCall>("VSP_GET_DEV_FREQ",caller,origin);
#endif
    int level=-1,result=-1,error=0;uint64_t begin=0,end=0;
    bool clock_good=stamp(CLOCK_MONOTONIC,begin);
    if(call){errno=0;result=call(object,&level);error=errno;}
    clock_good=clock_good&&stamp(CLOCK_MONOTONIC,end)&&end>=begin;
    pthread_mutex_lock(&lock);
    if(!call)readback.missing++;
    else{
        if(result!=0)readback.failed++;
        if(error)readback.bad_errno++;
        if(level<0||level>=16)readback.invalid++;
        if(result==0&&!error&&level>=0&&level<16){readback.accepted++;readback.levels[level]++;}
    }
    if(clock_good){const auto elapsed=end-begin;readback.wall+=elapsed;if(elapsed>readback.max)readback.max=elapsed;}
    else readback.clock_errors++;
    pthread_mutex_unlock(&lock);errno=saved;
}
static Call original(unsigned role,void*caller,unsigned&origin){
#ifdef P011_VSP_PROFILE_MOCK
    origin=1;
    if(role==2)return +[](void*p){return p011_mock_vsp(2,p);};
    return role?+[](void*p){return p011_mock_vsp(1,p);}: +[](void*p){return p011_mock_vsp(0,p);};
#else
    return original_symbol<Call>(role==2?"VSP_RELEASE_Dev":role==1?"VSP_ACQUIRE_Dev":"VSP_POLL_COMPLETE",caller,origin);
#endif
}
static int observe(unsigned role,void*object,void*caller,Call self){
    const int before_errno=errno;unsigned origin=0;Call call=original(role,caller,origin);
    if(!call||call==self){pthread_mutex_lock(&lock);failures++;pthread_mutex_unlock(&lock);errno=ENOSYS;return -1;}
    const bool active=enabled();uint64_t wall0=0,cpu0=0,wall1=0,cpu1=0;
    bool good=!active||(stamp(CLOCK_MONOTONIC,wall0)&&stamp(CLOCK_THREAD_CPUTIME_ID,cpu0));
    errno=before_errno;const int result=call(object);const int result_errno=errno;
    if(active){
        good=good&&stamp(CLOCK_THREAD_CPUTIME_ID,cpu1)&&stamp(CLOCK_MONOTONIC,wall1)&&wall1>=wall0&&cpu1>=cpu0;
        pthread_mutex_lock(&lock);
        origins[origin]++;
        if(role==0){
            const unsigned bucket=result==0?0:result==2?1:result==4?2:result<0?3:4;
            poll_results[bucket]++;
            if(bucket==4){const auto value=uint32_t(result);if(value<poll_other_min)poll_other_min=value;if(value>poll_other_max)poll_other_max=value;}
        }
        if(role==2&&result<0)release_failed++;
        if(good){
            auto&c=counters[role];const auto elapsed=wall1-wall0;
            c.count++;c.wall+=elapsed;c.cpu+=cpu1-cpu0;if(elapsed>c.max)c.max=elapsed;
            c.bins[elapsed<5000000?0:elapsed<10000000?1:elapsed<20000000?2:elapsed<50000000?3:4]++;
            if(role==0){
                detailed_poll[vsp_poll_bucket(elapsed)]++;
                vsp_record_gap(previous_poll,gaps,object,wall0,wall1);
            }
            vsp_record_sequence(current_sequence,sequence,role,object);
            vsp_record_cycle(current_cycle,cycles,role,object,wall0,wall1);
        }else{clock_failures++;if(role==0)previous_poll.valid=false;cycles.clock_errors++;current_cycle.stage=4;current_sequence.valid=false;}
        pthread_mutex_unlock(&lock);
    }
    errno=result_errno;return result;
}
static int observe_frequency(void*object,int*level,void*caller,FrequencyCall self){
    const int before_errno=errno;unsigned origin=0;
#ifdef P011_VSP_PROFILE_MOCK
    origin=1;FrequencyCall call=p011_mock_vsp_frequency;
#else
    FrequencyCall call=original_symbol<FrequencyCall>("VSP_CONFIG_DEV_FREQ",caller,origin);
#endif
    if(!call||call==self){pthread_mutex_lock(&lock);failures++;pthread_mutex_unlock(&lock);errno=ENOSYS;return -1;}
    const bool active=enabled();const int requested=active&&level?*level:0;
    errno=before_errno;const int result=call(object,level);const int result_errno=errno;
    if(active){
        pthread_mutex_lock(&lock);frequency.calls++;frequency.origins[origin]++;
        if(result==0)frequency.success++;else frequency.failed++;
        if(!level)frequency.null_arg++;else if(requested>=0&&requested<16)frequency.levels[requested]++;else frequency.other++;
        pthread_mutex_unlock(&lock);
    }
    observe_readback(object,caller,(level&&requested>=0&&requested<16)?result:-1);
    errno=result_errno;return result;
}
}
extern "C" __attribute__((noinline)) int VSP_POLL_COMPLETE(void*p){return observe(0,p,__builtin_return_address(0),VSP_POLL_COMPLETE);}
extern "C" __attribute__((noinline)) int VSP_ACQUIRE_Dev(void*p){return observe(1,p,__builtin_return_address(0),VSP_ACQUIRE_Dev);}
extern "C" __attribute__((noinline)) int VSP_RELEASE_Dev(void*p){return observe(2,p,__builtin_return_address(0),VSP_RELEASE_Dev);}
extern "C" __attribute__((noinline)) int VSP_CONFIG_DEV_FREQ(void*p,int*level){return observe_frequency(p,level,__builtin_return_address(0),VSP_CONFIG_DEV_FREQ);}
extern "C" void p011_omx_format_observe(const uint32_t*values){
    const int saved=errno;
    if(enabled()){pthread_mutex_lock(&lock);formats.record(values);pthread_mutex_unlock(&lock);}
    errno=saved;
}

#ifndef P011_VSP_PROFILE_MOCK
// The ordinary worker deliberately discards vendor stdout/stderr in main().
// Keep only an owned CLOEXEC duplicate of the controller's PIPE, before main;
// never redirect vendor logs back to it. This descriptor carries numeric
// observer output only and is closed at process teardown.
static int evidence_fd=-1;
__attribute__((constructor)) static void capture_channel(){
    if(!enabled())return;struct stat info{};
    if(fstat(2,&info)||!S_ISFIFO(info.st_mode))return;
    evidence_fd=fcntl(2,F_DUPFD_CLOEXEC,10);
}
__attribute__((destructor)) static void report(){
    if(evidence_fd<0)return;
    char line[4096];auto&p=counters[0];auto&a=counters[1];
    int n=snprintf(line,sizeof(line),"P011_VSP_PROFILE={\"poll_count\":%llu,\"poll_wall_ns\":%llu,\"poll_cpu_ns\":%llu,\"poll_max_ns\":%llu,"
        "\"poll_lt5ms\":%llu,\"poll_5to10ms\":%llu,\"poll_10to20ms\":%llu,\"poll_20to50ms\":%llu,\"poll_ge50ms\":%llu,"
        "\"acquire_count\":%llu,\"acquire_wall_ns\":%llu,\"acquire_cpu_ns\":%llu,\"acquire_max_ns\":%llu,"
        "\"stagefright_calls\":%llu,\"codec_calls\":%llu,\"forward_errors\":%llu,\"clock_errors\":%llu",
        (unsigned long long)p.count,(unsigned long long)p.wall,(unsigned long long)p.cpu,(unsigned long long)p.max,
        (unsigned long long)p.bins[0],(unsigned long long)p.bins[1],(unsigned long long)p.bins[2],(unsigned long long)p.bins[3],(unsigned long long)p.bins[4],
        (unsigned long long)a.count,(unsigned long long)a.wall,(unsigned long long)a.cpu,(unsigned long long)a.max,
        (unsigned long long)origins[0],(unsigned long long)origins[1],(unsigned long long)failures,(unsigned long long)clock_failures);
    auto add=[&](const char*key,uint64_t value){
        if(n>0&&n<int(sizeof(line)))n+=snprintf(line+n,sizeof(line)-size_t(n),",\"%s\":%llu",key,(unsigned long long)value);
    };
    add("freq_config_calls",frequency.calls);add("freq_config_success",frequency.success);add("freq_config_failed",frequency.failed);
    add("freq_null",frequency.null_arg);add("freq_other",frequency.other);
    add("freq_stagefright_calls",frequency.origins[0]);add("freq_codec_calls",frequency.origins[1]);
    static const char*result_names[]={"poll_result_0","poll_result_2","poll_result_4","poll_result_negative","poll_result_other"};
    for(unsigned i=0;i<5;i++)add(result_names[i],poll_results[i]);
    add("poll_result_other_min_u32",poll_results[4]?poll_other_min:0);add("poll_result_other_max_u32",poll_other_max);
    for(unsigned i=0;i<16;i++){char key[32];snprintf(key,sizeof(key),"freq_level%u",i);add(key,frequency.levels[i]);}
    add("timing_schema",1);add("gap_count",gaps.count);add("gap_wall_ns",gaps.wall);add("gap_max_ns",gaps.max);
    add("gap_first_calls",gaps.first);add("gap_context_resets",gaps.resets);add("gap_clock_errors",gaps.errors);
    static const char*gap_names[]={"gap_lt1ms","gap_1to2ms","gap_2to5ms","gap_5to10ms","gap_10to20ms","gap_ge20ms"};
    static const char*poll_names[]={"poll_detail_lt8ms","poll_detail_8to12ms","poll_detail_12to16_667ms","poll_detail_16_667to20ms",
        "poll_detail_20to25ms","poll_detail_25to33_333ms","poll_detail_33_333to50ms","poll_detail_ge50ms"};
    for(unsigned i=0;i<6;i++)add(gap_names[i],gaps.bins[i]);
    for(unsigned i=0;i<8;i++)add(poll_names[i],detailed_poll[i]);
    auto&r=counters[2];
    add("cycle_schema",2);add("release_count",r.count);add("release_wall_ns",r.wall);
    add("release_cpu_ns",r.cpu);add("release_max_ns",r.max);add("release_failed",release_failed);
    add("cycle_count",cycles.count);add("cycle_first_polls",cycles.first);add("cycle_incomplete_polls",cycles.incomplete);
    add("cycle_context_resets",cycles.context_resets);add("cycle_order_resets",cycles.order_resets);add("cycle_clock_errors",cycles.clock_errors);
    add("cycle_gap_wall_ns",cycles.gap.wall);add("cycle_gap_max_ns",cycles.gap.max);
    static const char*cycle_names[]={"postpoll","release","outer","acquire","prepare"};
    for(unsigned i=0;i<5;i++){
        char key[48];snprintf(key,sizeof(key),"cycle_%s_wall_ns",cycle_names[i]);add(key,cycles.parts[i].wall);
        snprintf(key,sizeof(key),"cycle_%s_max_ns",cycle_names[i]);add(key,cycles.parts[i].max);
    }
    add("cycle_extra_pairs",cycles.extra_pairs);add("cycle_max_extra_pairs",cycles.max_extra_pairs);
    add("seq_contexts",sequence.context_resets);
    for(unsigned i=0;i<3;i++){
        char key[24];snprintf(key,sizeof(key),"seq_start%u",i);add(key,sequence.starts[i]);
        for(unsigned j=0;j<3;j++){snprintf(key,sizeof(key),"seq_e%u%u",i,j);add(key,sequence.edges[i*3+j]);}
    }
    if(n>0&&n<int(sizeof(line))-2){line[n++]='}';line[n++]='\n';ssize_t written;do{written=write(evidence_fd,line,size_t(n));}while(written<0&&errno==EINTR);}
    const size_t format_size=formats.format(line,sizeof(line));
    if(format_size){ssize_t written;do{written=write(evidence_fd,line,format_size);}while(written<0&&errno==EINTR);}
    if(readback_enabled()){
        n=snprintf(line,sizeof(line),"P011_VSP_READBACK={\"schema\":2,\"stride\":64,\"limit\":32");
        add("eligible_configurations",readback.eligible);add("skipped_configurations",readback.skipped);
        add("calls",readback.calls);add("accepted",readback.accepted);add("getter_missing",readback.missing);
        add("return_failed",readback.failed);add("errno_failed",readback.bad_errno);add("invalid_level",readback.invalid);
        add("clock_errors",readback.clock_errors);add("wall_ns",readback.wall);add("max_ns",readback.max);
        for(unsigned i=0;i<16;i++){char key[32];snprintf(key,sizeof(key),"level%u",i);add(key,readback.levels[i]);}
        if(n>0&&n<int(sizeof(line))-2){line[n++]='}';line[n++]='\n';ssize_t written;do{written=write(evidence_fd,line,size_t(n));}while(written<0&&errno==EINTR);}
    }
    close(evidence_fd);evidence_fd=-1;
}
#else
extern "C" void p011_vsp_mock_readback(void*p,int result){observe_readback(p,nullptr,result);}
extern "C" unsigned p011_vsp_mock_readback_checks(){
    return readback.eligible==3200&&readback.skipped==4&&readback.calls==32&&readback.accepted==27&&
        !readback.missing&&readback.failed==1&&readback.bad_errno==1&&readback.invalid==3&&
        !readback.clock_errors&&readback.levels[3]==27;
}
extern "C" unsigned p011_omx_format_mock_checks(){
    return formats.count==1&&!formats.overflow&&!formats.invalid&&formats.rows[0][0]==2&&
        formats.rows[0][1]==0&&formats.rows[0][2]==1920&&formats.rows[0][3]==1080&&
        formats.rows[0][4]==1920&&formats.rows[0][5]==1088&&formats.rows[0][6]==3932160&&
        formats.rows[0][7]==60&&formats.rows[0][8]==1&&formats.rows[0][9]==7&&
        formats.rows[0][10]==21&&formats.rows[0][11]==20&&formats.rows[0][12]==3133440&&formats.rows[0][13]==0;
}
extern "C" unsigned p011_vsp_mock_checks(){
    return counters[0].count==100&&counters[1].count==100&&counters[2].count==100&&origins[1]==300&&failures==0&&clock_failures==0&&release_failed==0&&
        counters[0].wall>=counters[0].cpu&&counters[1].wall>=counters[1].cpu&&counters[2].wall>=counters[2].cpu&&
        gaps.count==99&&gaps.first==1&&gaps.resets==0&&gaps.errors==0&&
        gaps.bins[0]+gaps.bins[1]+gaps.bins[2]+gaps.bins[3]+gaps.bins[4]+gaps.bins[5]==99&&
        cycles.count==99&&cycles.first==1&&cycles.incomplete==0&&cycles.context_resets==0&&cycles.order_resets==0&&cycles.clock_errors==0&&
        cycles.extra_pairs==0&&cycles.max_extra_pairs==0&&
        sequence.starts[0]==0&&sequence.starts[1]==1&&sequence.starts[2]==0&&sequence.context_resets==0&&
        sequence.edges[0]==0&&sequence.edges[1]==0&&sequence.edges[2]==100&&sequence.edges[3]==100&&sequence.edges[4]==0&&
        sequence.edges[5]==0&&sequence.edges[6]==0&&sequence.edges[7]==99&&sequence.edges[8]==0&&
        cycles.gap.wall==gaps.wall&&cycles.gap.max==gaps.max&&
        cycles.parts[0].wall+cycles.parts[1].wall+cycles.parts[2].wall+cycles.parts[3].wall+cycles.parts[4].wall==gaps.wall&&
        frequency.calls==100&&frequency.success==80&&frequency.failed==20&&frequency.null_arg==20&&frequency.other==40&&
        frequency.levels[2]==20&&frequency.levels[4]==20&&frequency.origins[1]==100;
}
#endif
