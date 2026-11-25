// SPDX-License-Identifier: LGPL-2.1-or-later
// Numeric-only diagnostic accounting. Pointer values are compared, never read
// or exported. A cycle spans consecutive POLL calls, with one or more paired
// RELEASE / ACQUIRE calls in between. It is not a video-frame identity,
// hardware busy interval, or CPU-only timing. Extra pairs are counted, not
// silently discarded. Every accepted interval is partitioned exactly once.
#pragma once
#include <cstdint>

struct VspCyclePart {uint64_t wall=0,max=0;};
struct VspCycleStats {
    uint64_t count=0,first=0,incomplete=0,context_resets=0,order_resets=0,clock_errors=0;
    uint64_t extra_pairs=0,max_extra_pairs=0;
    VspCyclePart parts[5],gap;
};
struct VspCycleState {
    const void*object=nullptr;
    uint64_t poll_end=0,last_end=0,pending[5]={0},extra_pairs=0;
    // 0: no initial poll, 1: poll, 2: release, 3: acquire, 4: invalid cycle.
    unsigned stage=0;
};
struct VspSequenceStats {uint64_t starts[3]={0},edges[9]={0},context_resets=0;};
struct VspSequenceState {const void*object=nullptr;unsigned role=0;bool valid=false;};
inline void vsp_record_sequence(VspSequenceState&state,VspSequenceStats&stats,unsigned role,const void*object){
    if(role>2)return;
    if(!state.valid||state.object!=object){
        stats.starts[role]++;
        if(state.valid)stats.context_resets++;
    }else stats.edges[state.role*3+role]++;
    state.object=object;state.role=role;state.valid=true;
}
inline void vsp_cycle_add(VspCyclePart&part,uint64_t ns){
    part.wall+=ns;if(ns>part.max)part.max=ns;
}
inline void vsp_record_cycle(VspCycleState&state,VspCycleStats&stats,unsigned role,
                             const void*object,uint64_t start,uint64_t end){
    if(role>2||end<start){stats.clock_errors++;state.stage=4;return;}
    if(role==0){
        if(state.stage==0)stats.first++;
        else if(state.stage==3&&state.object==object&&start>=state.last_end){
            state.pending[4]+=start-state.last_end;
            stats.count++;
            for(unsigned i=0;i<5;i++)vsp_cycle_add(stats.parts[i],state.pending[i]);
            vsp_cycle_add(stats.gap,start-state.poll_end);
            stats.extra_pairs+=state.extra_pairs;
            if(state.extra_pairs>stats.max_extra_pairs)stats.max_extra_pairs=state.extra_pairs;
        }else{
            stats.incomplete++;
            if(state.stage!=4){
                if(state.object!=object)stats.context_resets++;
                else if(state.stage==3)stats.clock_errors++;
                else stats.order_resets++;
            }
        }
        state.object=object;state.poll_end=end;state.last_end=end;state.stage=1;state.extra_pairs=0;
        for(auto&part:state.pending)part=0;
        return;
    }
    // Startup before the first poll and a previously rejected cycle do not
    // produce invented intervals. Resume only at an actual next poll.
    if(state.stage==0||state.stage==4)return;
    if(state.object!=object){stats.context_resets++;state.stage=4;return;}
    if((role==2&&state.stage!=1&&state.stage!=3)||(role==1&&state.stage!=2)){
        stats.order_resets++;state.stage=4;return;
    }
    if(start<state.last_end){
        stats.clock_errors++;state.stage=4;return;
    }
    if(role==2){
        state.pending[state.stage==1?0:4]+=start-state.last_end;
        if(state.stage==3)state.extra_pairs++;
        state.pending[1]+=end-start;state.stage=2;
    }else{
        state.pending[2]+=start-state.last_end;state.pending[3]+=end-start;state.stage=3;
    }
    state.last_end=end;
}
