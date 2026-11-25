// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
namespace p011_hw {
// A scaled plugin must advertise both original coded geometry and the exact
// public geometry. Reject missing/partial markers and accidental double scale.
inline bool fused_output_valid(int width,int height,int fw,int fh,int scale,int cw,int ch){
    if(width<4||height<4||width>1920||height>1920||width*height>1920*1080||
       (width&1)||(height&1))return false;
    if(std::max(width,height)<=960)return scale==0&&cw==0&&ch==0&&fw==width&&fh==height;
    return scale==2&&cw==width&&ch==height&&fw==width/4*2&&fh==height/4*2;
}
}
