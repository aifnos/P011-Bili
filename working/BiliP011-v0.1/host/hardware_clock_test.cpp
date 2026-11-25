// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <iostream>
#include <limits>
#include "../client/hardware_clock.hpp"
int main(){
    using p011_hw::current_position;unsigned checks=0;
    for(unsigned age=0;age<=500000;age+=1000){
        assert(std::abs(current_position(10,100,true,1000000,1000000+age)-(10+std::min(age,250000u)/1e6))<1e-9);checks++;
        assert(current_position(10,100,false,1000000,1000000+age)==10);checks++;
    }
    assert(current_position(10,100,true,0,1000000)==10);checks++;
    assert(current_position(10,100,true,1000000,1200000,1.5)==10.3);checks++;
    assert(current_position(10,100,false,1000000,1200000,2)==10);checks++;
    assert(current_position(10,100,true,2000000,1000000)==10);checks++;
    assert(current_position(10,10.05,true,1000000,1200000)==10.05);checks++;
    assert(current_position(-1,100,true,1,2)==0);checks++;
    assert(current_position(std::numeric_limits<double>::quiet_NaN(),100,true,1,2)==0);checks++;
    std::cout<<"CLOCK_CHECKS="<<checks<<"\n";
}
