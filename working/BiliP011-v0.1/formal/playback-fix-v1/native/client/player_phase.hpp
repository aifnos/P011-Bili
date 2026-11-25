// SPDX-License-Identifier: GPL-3.0-or-later
// Pure bounded counters. Caller supplies monotonic elapsed microseconds;
// no strings, media data, allocation, I/O, or timing-policy changes here.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
namespace p011_profile {
inline uint64_t add(uint64_t a,uint64_t b){return b>std::numeric_limits<uint64_t>::max()-a?std::numeric_limits<uint64_t>::max():a+b;}
struct Phase {
    uint64_t count=0,total_us=0,max_us=0,over_33ms=0,over_100ms=0,last_slow_position_ms=0;
    void record(uint64_t elapsed,uint64_t position_ms,bool playing){
        if(!playing)return;
        count=add(count,1);total_us=add(total_us,elapsed);max_us=std::max(max_us,elapsed);
        if(elapsed>33000){over_33ms=add(over_33ms,1);last_slow_position_ms=position_ms;}
        if(elapsed>100000)over_100ms=add(over_100ms,1);
    }
};
enum Id { Input,Status,Layout,Pacer,Upload,Overlay,Swap,Count };
struct Phases {std::array<Phase,Count> rows;};
}
