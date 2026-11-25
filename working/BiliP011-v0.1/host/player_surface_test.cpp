// SPDX-License-Identifier: GPL-3.0-or-later
// Pure PC geometry; no GL, ADB, input or device operations.
#include "../client/player_surface.hpp"
#include "../client/player_controls.hpp"
#include <iostream>
using namespace p011_player;
int main(){
    unsigned checks=0;auto check=[&](bool v){if(!v)throw checks;++checks;};
    auto same=[](Point a,Point b){return std::abs(a.x-b.x)<1e-7&&std::abs(a.y-b.y)<1e-7;};
    try{
        for(bool strip:{false,true}){
            Surface s{strip};check(s.height()==(strip?268:480));
            check(same(s.ndc(s.panel({0,0})),{-1,1}));
            check(same(s.ndc(s.panel({800,s.height()})),{1,-1}));
            for(auto orientation:{Orientation::Landscape,Orientation::PortraitClockwise}){
                Layout l{orientation};
                for(int x=0;x<=20;x++)for(int y=0;y<=20;y++){
                    Point p{l.width()*x/20,l.height()*y/20},panel=l.physical(p),local=s.local(panel),out;
                    check(same(s.panel(local),panel));
                    check(l.logical(s.from_normalized({local.x/s.width(),local.y/s.height()}),out));
                    check(same(out,p));
                }
                for(bool story:{false,true}){
                    auto box=video_box(l,story);auto a=l.physical({box.x,box.y}),b=l.physical({box.x+box.w,box.y+box.h});
                    auto c=s.clip(a,b,int(s.width()),int(s.height()));
                    check(c.x>=0&&c.y>=0&&c.x+c.w<=s.width()&&c.y+c.h<=s.height());
                    check(c.w*c.h==int(box.w*box.h));
                    for(const auto&button:buttons(l,true,false,true,0,{16,32,64})){
                        Point p{button.box.x+button.box.w/2,button.box.y+button.box.h/2},out;
                        auto local=s.local(l.physical(p));
                        check(l.logical(s.from_normalized({local.x/s.width(),local.y/s.height()}),out));
                        check(button.box.contains(out));
                    }
                }
            }
            auto c=s.clip({-100,-100},{900,600},800,int(s.height()));
            check(c.x==0&&c.y==0&&c.w==800&&c.h==int(s.height()));
        }
        std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"device_tested\":false}\n";
        return 0;
    }catch(unsigned at){std::cout<<"{\"passed\":false,\"failed_check\":"<<at<<"}\n";return 1;}
}
