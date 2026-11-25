// Host-only accounting test, not evidence of target frame timing.
#include "../client/player_phase.hpp"
#include <cassert>
#include <cstdio>
int main(){
    unsigned checks=0;
    p011_profile::Phases all;
    for(auto&p:all.rows){
        p.record(1000000,5000,false);assert(p.count==0&&p.max_us==0);checks++;
        p.record(33000,6000,true);assert(p.count==1&&p.over_33ms==0);checks++;
        p.record(33001,7000,true);assert(p.over_33ms==1&&p.last_slow_position_ms==7000&&p.over_100ms==0);checks++;
        p.record(100000,8000,true);assert(p.over_100ms==0);checks++;
        p.record(100001,9000,true);assert(p.count==4&&p.total_us==266002&&p.max_us==100001&&p.over_33ms==3&&p.over_100ms==1);checks++;
        p.record(5,10000,true);assert(p.last_slow_position_ms==9000);checks++;
        p.record(2000000,11000,false);assert(p.max_us==100001);checks++;
    }
    auto max=std::numeric_limits<uint64_t>::max();auto&p=all.rows[0];p.count=max;p.total_us=max-1;p.over_33ms=max;p.over_100ms=max;
    p.record(100001,12345,true);assert(p.count==max&&p.total_us==max&&p.over_33ms==max&&p.over_100ms==max);checks++;
    for(uint64_t x=0;x<1000000;x+=997){p011_profile::Phase v;v.record(x,x/1000,true);assert(v.count==1&&v.total_us==x&&v.max_us==x&&v.over_33ms==(x>33000)&&v.over_100ms==(x>100000));checks++;}
    std::printf("PHASE_CHECKS=%u\n",checks);
}
