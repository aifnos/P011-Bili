// SPDX-License-Identifier: GPL-3.0-or-later
// PC-only tests of the future portrait player's shared pure geometry.
#include "../client/player_geometry.hpp"
#include <iostream>
#include <limits>
using namespace p011_player;
int main() {
    unsigned checks=0;
    auto check=[&](bool value) { if(!value)throw checks; ++checks; };
    auto same=[](Point a,Point b) {return std::abs(a.x-b.x)<1e-8&&std::abs(a.y-b.y)<1e-8;};
    try {
        for (auto orientation:{Orientation::Landscape,Orientation::PortraitClockwise}) {
            Layout l{orientation};
            for (double u:{0.,.01,.25,.5,.75,.99,1.})
                for(double v:{0.,.01,.25,.5,.75,.99,1.}) {
                    Point source{l.width()*u,l.height()*v}, decoded{};
                    check(l.logical(l.physical(source),decoded));check(same(source,decoded));
                }
            Point decoded{};
            for(Point outside: {Point{-1,106},Point{801,106},Point{0,105},Point{0,375},
                Point{std::numeric_limits<double>::quiet_NaN(),200},
                Point{200,std::numeric_limits<double>::infinity()}})check(!l.logical(outside,decoded));
        }
        Layout p{Orientation::PortraitClockwise}, landscape;
        check(p.width()==268 && p.height()==800);
        check(same(p.physical({0,0}),{800,106}));
        check(same(p.physical({268,800}),{0,374}));
        check(p.swipe({134,450},{134,300},300,false)==Swipe::Next);
        check(p.swipe({134,300},{134,450},300,false)==Swipe::Previous);
        check(p.swipe({134,450},{134,379},300,false)==Swipe::None);
        check(p.swipe({20,450},{200,300},300,false)==Swipe::None);
        check(p.swipe({134,450},{134,300},300,true)==Swipe::None);
        check(p.swipe({134,450},{134,300},1600,false)==Swipe::None);
        check(p.swipe({134,450},{134,300},0,false)==Swipe::None);
        check(p.swipe({134,450},{134,-1},300,false)==Swipe::None);
        check(landscape.swipe({134,240},{134,100},300,false)==Swipe::None);
        Point start{},end{};
        check(p.logical({350,240},start)&&p.logical({500,240},end));
        check(p.swipe(start,end,300,false)==Swipe::Next);
        std::cout<<"{\"checks\":"<<checks<<",\"passed\":true,\"device_tested\":false,\"layer\":\"pure geometry\"}\n";
        return 0;
    } catch(unsigned at) {
        std::cout<<"{\"failed_check\":"<<at<<",\"passed\":false,\"device_tested\":false}\n";
        return 1;
    }
}
