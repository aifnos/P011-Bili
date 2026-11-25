// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "player_geometry.hpp"
#include <algorithm>
#include <cstdint>
namespace p011_player {
// A locked axis cannot turn into a tap, seek or feed switch mid-gesture.
struct VideoGesture {
    enum Axis { Pending, Horizontal, Vertical, Rejected } axis=Pending;
    Point start{0,0};double base=0,target=0,delta=0,duration=0,width=500;
    bool vertical=false;unsigned began=0;
    void begin(Point p,unsigned now,double position,double length,double w,bool story){
        axis=Pending;start=p;base=target=position;delta=0;duration=length;width=w;vertical=story;began=now;
    }
    void move(Point p){
        if(!std::isfinite(p.x)||!std::isfinite(p.y))return;
        double dx=p.x-start.x,dy=p.y-start.y;
        if(axis==Pending&&std::max(std::abs(dx),std::abs(dy))>=14){
            if(std::abs(dx)>1.3*std::abs(dy))axis=duration>0?Horizontal:Rejected;
            else if(std::abs(dy)>1.3*std::abs(dx))axis=vertical?Vertical:Rejected;
        }
        if(axis==Horizontal)target=std::max(0.,std::min(std::max(0.,duration-.05),base+dx/std::max(1.,width)*std::min(180.,std::max(30.,duration))));
        if(axis==Vertical)delta=std::max(-720.,std::min(720.,dy));
    }
    bool commit(unsigned now)const{
        unsigned elapsed=now-began;
        return axis==Vertical&&(std::abs(delta)>=120||(std::abs(delta)>=72&&elapsed>0&&double(std::abs(delta))/elapsed>=.55));
    }
};
struct FeedSlide {
    double offset=0,from=0,to=0;unsigned began=0,span=0;int direction=0;
    bool waiting=false,moving=false;
    double sample(unsigned now){
        if(!moving)return offset;double t=std::min(1.,double(unsigned(now-began))/std::max(1u,span));
        double ease=1-std::pow(1-t,3);offset=from+(to-from)*ease;if(t>=1)moving=false;return offset;
    }
    void animate(double dest,unsigned now,unsigned ms=210){from=offset;to=dest;began=now;span=ms;moving=true;}
    void drag(double d){offset=d;moving=false;}
    void release(bool commit,unsigned now){direction=offset<0?1:-1;waiting=commit;animate(commit?-800.*direction:0,now);}
    void ready(unsigned now){if(waiting){waiting=false;offset=800.*direction;animate(0,now,240);}}
    void cancel(unsigned now){waiting=false;animate(0,now);}
    bool active()const{return moving||waiting||std::abs(offset)>.1;}
};
}
