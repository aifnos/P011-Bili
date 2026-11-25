// SPDX-License-Identifier: LGPL-2.1-or-later
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include "../probes/vsp_gap_stats.hpp"
#include "../probes/vsp_cycle_stats.hpp"
#include "../probes/omx_format_stats.hpp"
#include "../probes/omx_format_bridge.h"
static int object=0;static unsigned calls[3]={0};
static int*expected_level=nullptr;static int expected_value=0;static unsigned config_calls=0;
static unsigned readback_calls=0;
extern "C" int VSP_POLL_COMPLETE(void*);
extern "C" int VSP_ACQUIRE_Dev(void*);
extern "C" int VSP_RELEASE_Dev(void*);
extern "C" int VSP_CONFIG_DEV_FREQ(void*,int*);
extern "C" unsigned p011_vsp_mock_checks();
extern "C" unsigned p011_omx_format_mock_checks();
extern "C" void p011_vsp_mock_readback(void*,int);
extern "C" unsigned p011_vsp_mock_readback_checks();
extern "C" int p011_mock_vsp_readback(void*p,int*level){
    if(p!=&object||!level||*level!=-1||errno!=0)return -99;
    const unsigned i=++readback_calls;
    if(i==2)return 0; // vendor swallowed a failed ioctl, output untouched
    *level=i==5?16:i==6?-2:3;
    if(i==3)errno=5;
    return i==4?-1:0;
}
extern "C" int p011_mock_vsp(unsigned role,void*p){
    if(p!=&object||errno!=123)return -99;calls[role]++;errno=124+role;return 7+role;
}
extern "C" int p011_mock_vsp_frequency(void*p,int*level){
    if(p!=&object||level!=expected_level||errno!=123||(level&&*level!=expected_value))return -99;
    config_calls++;errno=126;return level&&*level==4?-1:0;
}
static bool cycle_arithmetic(){
    VspCycleState state;VspCycleStats stats;int other=0;
    vsp_record_cycle(state,stats,1,&object,10,20); // startup is not a gap
    vsp_record_cycle(state,stats,2,&object,30,40);
    vsp_record_cycle(state,stats,0,&object,100,200);
    vsp_record_cycle(state,stats,2,&object,220,260);
    vsp_record_cycle(state,stats,1,&object,300,350);
    vsp_record_cycle(state,stats,0,&object,500,550);
    const uint64_t expected[]={20,40,40,50,150};
    if(stats.count!=1||stats.first!=1||stats.incomplete||stats.gap.wall!=300||stats.gap.max!=300)return false;
    for(unsigned i=0;i<5;i++)if(stats.parts[i].wall!=expected[i]||stats.parts[i].max!=expected[i])return false;
    // A context change, missing release, duplicate release and clock reversal
    // reject the entire pending gap, rather than mislabelling its components.
    vsp_record_cycle(state,stats,2,&other,560,570);
    vsp_record_cycle(state,stats,1,&object,580,590);
    vsp_record_cycle(state,stats,0,&object,600,650);
    vsp_record_cycle(state,stats,1,&object,660,670);
    vsp_record_cycle(state,stats,0,&object,700,750);
    vsp_record_cycle(state,stats,2,&object,760,770);
    vsp_record_cycle(state,stats,2,&object,780,790);
    vsp_record_cycle(state,stats,0,&object,800,850);
    vsp_record_cycle(state,stats,2,&object,849,860);
    vsp_record_cycle(state,stats,0,&object,900,950);
    vsp_record_cycle(state,stats,2,&object,960,959);
    vsp_record_cycle(state,stats,0,&object,1000,1050);
    if(stats.count!=1||stats.incomplete!=5||stats.context_resets!=1||stats.order_resets!=2||stats.clock_errors!=2)return false;
    // Zero-duration intervals are valid, and rejected cycles did not corrupt
    // the previous complete-cycle total. Another state has its own first poll.
    vsp_record_cycle(state,stats,2,&object,1050,1050);
    vsp_record_cycle(state,stats,1,&object,1050,1050);
    vsp_record_cycle(state,stats,0,&object,1050,1050);
    VspCycleState separate;vsp_record_cycle(separate,stats,0,&other,1,2);
    return stats.count==2&&stats.first==2&&stats.gap.wall==300&&stats.gap.max==300;
}
static bool extra_cycle_arithmetic(){
    VspCycleState state;VspCycleStats stats;
    vsp_record_cycle(state,stats,0,&object,100,200);
    vsp_record_cycle(state,stats,2,&object,220,260);
    vsp_record_cycle(state,stats,1,&object,300,350);
    vsp_record_cycle(state,stats,2,&object,400,460);
    vsp_record_cycle(state,stats,1,&object,500,550);
    vsp_record_cycle(state,stats,0,&object,800,850);
    const uint64_t expected[]={20,100,80,100,300};
    if(stats.count!=1||stats.extra_pairs!=1||stats.max_extra_pairs!=1||stats.gap.wall!=600||stats.order_resets)return false;
    for(unsigned i=0;i<5;i++)if(stats.parts[i].wall!=expected[i]||stats.parts[i].max!=expected[i])return false;
    // Multiple extra pairs in a single interval still sum to that exact gap.
    for(unsigned pairs=1;pairs<=6;pairs++){
        const auto begin=state.poll_end;auto at=begin;
        for(unsigned i=0;i<pairs;i++){
            vsp_record_cycle(state,stats,2,&object,at+1,at+3);at+=3;
            vsp_record_cycle(state,stats,1,&object,at+4,at+9);at+=9;
        }
        const auto old=stats.gap.wall;
        vsp_record_cycle(state,stats,0,&object,at+6,at+10);
        if(stats.gap.wall-old!=at+6-begin)return false;
    }
    uint64_t sum=0;for(const auto&part:stats.parts)sum+=part.wall;
    return stats.count==7&&stats.extra_pairs==16&&stats.max_extra_pairs==5&&sum==stats.gap.wall&&
        !stats.incomplete&&!stats.context_resets&&!stats.order_resets&&!stats.clock_errors;
}
static bool sequence_arithmetic(){
    VspSequenceState state;VspSequenceStats stats;int other=0;
    const unsigned roles[]={1,2,1,0,2,1,2,1,0,2};
    for(auto role:roles)vsp_record_sequence(state,stats,role,&object);
    const uint64_t expected[]={0,0,2,2,0,2,0,3,0};
    for(unsigned i=0;i<9;i++)if(stats.edges[i]!=expected[i])return false;
    if(stats.starts[0]||stats.starts[1]!=1||stats.starts[2]||stats.context_resets)return false;
    vsp_record_sequence(state,stats,1,&other);
    return stats.starts[1]==2&&stats.context_resets==1&&stats.edges[7]==3;
}
static bool format_observation(){
    OMX_PARAM_PORTDEFINITIONTYPE def{};
    def.nPortIndex=0;def.format.video.nFrameWidth=1920;def.format.video.nFrameHeight=1080;
    def.format.video.nStride=1920;def.format.video.nSliceHeight=1088;
    def.format.video.xFramerate=60*65536;def.format.video.eCompressionFormat=OMX_VIDEO_CodingAVC;
    def.format.video.eColorFormat=OMX_COLOR_FormatYUV420SemiPlanar;
    def.nBufferCountActual=20;def.nBufferSize=3133440;
    errno=144;p011_omx_format_record(2,&def,60,1,OMX_ErrorNone);
    if(errno!=144||!p011_omx_format_mock_checks())return false;
    OmxFormatStats stats;uint32_t values[14];for(auto&v:values)v=UINT32_MAX;
    values[0]=1;
    for(unsigned i=0;i<25;i++)stats.record(values);
    stats.record(nullptr);values[0]=4;stats.record(values);
    if(stats.count!=24||stats.overflow!=1||stats.invalid!=2||stats.rows[0][0]!=1||stats.rows[23][13]!=UINT32_MAX)return false;
    stats.overflow=stats.invalid=UINT32_MAX;
    char line[4096];const auto n=stats.format(line,sizeof(line));
    if(!n||n>=4096||line[n-1]!='\n'||strncmp(line,"P011_OMX_FORMAT=",16))return false;
    for(size_t size=0;size<=n;size++)if(stats.format(line,size))return false;
    return stats.format(line,n+1)==n;
}
int main(){
    unsetenv("P011_VSP_CLOCK_READBACK");
    if(!cycle_arithmetic()||!extra_cycle_arithmetic()||!sequence_arithmetic()||!format_observation())return 9;
    VspGapState state;VspGapStats stats;int other=0;
    vsp_record_gap(state,stats,&object,100,200);
    const uint64_t intervals[]={0,999999,1000000,1999999,2000000,4999999,5000000,9999999,10000000,19999999,20000000,90000000};
    uint64_t sum=0;
    for(auto gap:intervals){sum+=gap;auto at=state.end+gap;vsp_record_gap(state,stats,&object,at,at+10);}
    if(stats.count!=12||stats.wall!=sum||stats.max!=90000000||stats.first!=1)return 5;
    for(auto count:stats.bins)if(count!=2)return 6;
    vsp_record_gap(state,stats,&other,state.end+1,state.end+2);
    vsp_record_gap(state,stats,&other,state.end-1,state.end+1);
    if(stats.resets!=1||stats.errors!=1||stats.count!=12)return 7;
    const uint64_t edges[]={8000000,12000000,16666667,20000000,25000000,33333334,50000000};
    for(unsigned i=0;i<7;i++)if(vsp_poll_bucket(edges[i]-1)!=i||vsp_poll_bucket(edges[i])!=i+1)return 8;
    for(unsigned i=0;i<100;i++){
        errno=123;if(VSP_ACQUIRE_Dev(&object)!=8||errno!=125)return 2;
        int level=i%5==1?-1:i%5==2?2:i%5==3?4:17;
        expected_level=i%5?&level:nullptr;expected_value=level;
        errno=123;const int result=VSP_CONFIG_DEV_FREQ(&object,expected_level);
        if(result!=(i%5==3?-1:0)||errno!=126||level!=expected_value)return 4;
        errno=123;if(VSP_POLL_COMPLETE(&object)!=7||errno!=124)return 1;
        errno=123;if(VSP_RELEASE_Dev(&object)!=9||errno!=126)return 10;
    }
    if(calls[0]!=100||calls[1]!=100||calls[2]!=100||config_calls!=100||!p011_vsp_mock_checks())return 3;
    // The extra GET is opt-in, requires successful CONFIG status, rate/total bounded,
    // does not replace the original call, and preserves the caller's errno.
    if(readback_calls)return 11;
    setenv("P011_VSP_CLOCK_READBACK","0",1);
    for(unsigned i=0;i<100;i++)p011_vsp_mock_readback(&object,0);
    if(readback_calls)return 12;
    setenv("P011_VSP_CLOCK_READBACK","1",1);
    for(int result:{-1,1,7,8}){errno=155;p011_vsp_mock_readback(&object,result);if(errno!=155)return 13;}
    for(unsigned i=0;i<3200;i++){errno=155;p011_vsp_mock_readback(&object,0);if(errno!=155)return 14;}
    if(readback_calls!=32||!p011_vsp_mock_readback_checks()||config_calls!=100)return 15;
    unsetenv("P011_VSP_CLOCK_READBACK");
    puts("VSP_WAIT_FORWARD_MOCK_PASS");return 0;
}
