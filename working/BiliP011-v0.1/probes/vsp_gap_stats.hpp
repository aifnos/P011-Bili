// SPDX-License-Identifier: LGPL-2.1-or-later
// Diagnostic-only wall-time arithmetic. Never dereference/export a context.
#pragma once
#include <cstdint>

struct VspGapState {const void*object=nullptr;uint64_t end=0;bool valid=false;};
struct VspGapStats {
    uint64_t count=0,wall=0,max=0,first=0,resets=0,errors=0,bins[6]={0};
};
inline unsigned vsp_poll_bucket(uint64_t ns){
    return ns<8000000?0:ns<12000000?1:ns<16666667?2:ns<20000000?3:
           ns<25000000?4:ns<33333334?5:ns<50000000?6:7;
}
inline void vsp_record_gap(VspGapState&state,VspGapStats&stats,const void*object,uint64_t start,uint64_t end){
    if(end<start){stats.errors++;state.valid=false;return;}
    if(!state.valid)stats.first++;
    else if(state.object!=object)stats.resets++;
    else if(start<state.end)stats.errors++;
    else{
        const uint64_t gap=start-state.end;
        stats.count++;stats.wall+=gap;if(gap>stats.max)stats.max=gap;
        stats.bins[gap<1000000?0:gap<2000000?1:gap<5000000?2:gap<10000000?3:gap<20000000?4:5]++;
    }
    state.object=object;state.end=end;state.valid=true;
}
