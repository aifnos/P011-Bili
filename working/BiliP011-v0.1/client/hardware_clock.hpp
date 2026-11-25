// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace p011_hw {
// Worker and UI use the same kernel CLOCK_MONOTONIC epoch. Only advance an
// explicitly playing sample; retain raw position/age separately for audits.
inline double current_position(double position,double duration,bool playing,uint64_t sampled_us,uint64_t now_us,double rate=1.){
    if(!std::isfinite(position)||position<0)return 0;
    if(!playing||!sampled_us||now_us<sampled_us)return position;
    if(!std::isfinite(rate)||rate<.5||rate>2)rate=1;
    double value=position+double(std::min<uint64_t>(now_us-sampled_us,250000))/1000000.*rate;
    return std::isfinite(duration)&&duration>0?std::min(value,duration):value;
}
}
