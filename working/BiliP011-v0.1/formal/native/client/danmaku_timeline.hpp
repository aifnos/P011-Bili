// SPDX-License-Identifier: GPL-3.0-or-later
// Stable precomputed placement: never reassign a live comment on each frame.
#pragma once
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>
namespace p011_dm {
using Json=nlohmann::json;
struct Item {double time=0,life=8;int mode=1,color=0xffffff,size=25;std::string text;Json advanced;};
struct Placed {Item item;double width=0,scale=1;int lane=0;};
struct Drawing {const Placed*source;double x,y,alpha=1,angle=0,yscale=1;bool outline=true;};
inline std::vector<Item> rows(const Json&data){
    std::vector<Item> out;if(!data.is_array()||data.size()>2000)return out;
    for(const auto&r:data){try{
        Item d;d.time=r.at("time").get<double>();d.text=r.at("text").get<std::string>();
        d.mode=r.value("mode",1);d.color=r.value("color",0xffffff);d.size=r.value("size",25);
        if(!std::isfinite(d.time)||d.time<0||d.time>86400||d.text.empty()||d.text.size()>640||d.color<0||d.color>0xffffff||d.size<1||d.size>100||d.mode<1||d.mode>7)continue;
        if(d.mode==4||d.mode==5)d.life=4;
        if(d.mode==7){d.advanced=r.at("advanced");d.life=d.advanced.at("life").get<double>();
            if(!std::isfinite(d.life)||d.life<.1||d.life>20||!d.advanced.at("path").is_array()||d.advanced["path"].size()<2||d.advanced["path"].size()>64)continue;
        }
        out.push_back(d);
    }catch(const std::exception&){}}
    std::stable_sort(out.begin(),out.end(),[](const Item&a,const Item&b){return a.time<b.time;});return out;
}
class Timeline {
    std::vector<Placed> placed;double width=0,height=0,line_height=28;int lanes=0;
    std::vector<int> last;double size_scale=1,speed_scale=1;
    static double left(const Placed&p,double time,double w){double age=(time-p.item.time)/p.item.life;return p.item.mode==6?-p.width+(w+p.width)*age:w-(w+p.width)*age;}
    bool clear(const Placed&a,const Placed&b)const{
        if(a.item.time+a.item.life<=b.item.time)return true;
        if(a.item.mode>=4&&a.item.mode<=5)return false;
        if((a.item.mode==6)!=(b.item.mode==6))return false;
        // Relative positions are linear. Check separation at BOTH ends of
        // the shared lifetime, preventing fast long comments catching up.
        double end=std::min(a.item.time+a.item.life,b.item.time+b.item.life);
        for(double t:{b.item.time,end}){
            if(b.item.mode==6){if(left(b,t,width)+b.width+12>left(a,t,width))return false;}
            else if(left(a,t,width)+a.width+12>left(b,t,width))return false;
        }return true;
    }
public:
    unsigned dropped=0;
    void begin(double w,double h,double size=1,double speed=1){
        placed.clear();dropped=0;width=w;height=h;size_scale=std::max(.8,std::min(1.4,size));speed_scale=std::max(.75,std::min(1.5,speed));line_height=28*size_scale;lanes=std::max(1,std::min(9,int(h/line_height)));last.assign(lanes,-1);
    }
    void append(const Item&d,const std::function<double(const std::string&,double)>&measure){
            Placed p;p.item=d;if(d.mode!=7)p.item.life/=speed_scale;p.scale=std::max(.5,std::min(.92,d.size/25.*.74))*size_scale;p.width=measure(d.text,p.scale);
            if(d.mode==7){
                int advanced_live=0;for(auto i=placed.rbegin();i!=placed.rend()&&i->item.time>d.time-20;++i)if(i->item.mode==7&&i->item.time+i->item.life>d.time)advanced_live++;
                if(advanced_live<3){p.lane=-1;placed.push_back(p);}else dropped++;return;
            }
            if(d.mode==4||d.mode==5){p.scale*=std::min(1.,(width-16)/std::max(1.,p.width));p.width=measure(d.text,p.scale);}
            // At 25% area there may only be one or two lines. Share those
            // tracks rather than placing a forced five lanes outside the area.
            int begin=d.mode==5?0:d.mode==4?lanes-1:lanes>=3?1:0,end=d.mode==5?1:d.mode==4?lanes:lanes>=3?lanes-1:lanes;bool found=false;
            for(int lane=begin;lane<end;lane++)if(last[lane]<0||clear(placed[last[lane]],p)){
                p.lane=lane;last[lane]=int(placed.size());placed.push_back(p);found=true;break;
            }if(!found)dropped++;
    }
    void build(const std::vector<Item>&source,double w,double h,const std::function<double(const std::string&,double)>&measure,double size=1,double speed=1){
        begin(w,h,size,speed);for(const Item&d:source)append(d,measure);
    }
    size_t size()const{return placed.size();}
    // Live streams append without re-laying out comments already on screen.
    // Only expired prefix rows are erased; lane ownership is re-indexed.
    void prune(double before){
        size_t count=0;while(count<placed.size()&&placed[count].item.time<before)++count;
        if(!count)return;
        placed.erase(placed.begin(),placed.begin()+count);
        for(auto&i:last)i=i<int(count)?-1:i-int(count);
    }
    std::vector<Drawing> at(double time)const{
        std::vector<Drawing> result;if(!std::isfinite(time))return result;
        auto start=std::lower_bound(placed.begin(),placed.end(),time-20,[](const Placed&p,double t){return p.item.time<t;});
        for(auto i=start;i!=placed.end()&&i->item.time<=time;++i){const Placed&p=*i;double age=time-p.item.time;if(age>=p.item.life)continue;
            Drawing d{&p,0,0};d.y=p.item.mode==4?height-6:std::min(height-3,22*line_height/28+p.lane*line_height);
            if(p.item.mode==4||p.item.mode==5)d.x=(width-p.width)/2;
            else if(p.item.mode!=7)d.x=left(p,time,width);
            else{try{
                const Json&a=p.item.advanced;double move=a.value("move",p.item.life),delay=a.value("delay",0.);
                double f=move>0?std::max(0.,std::min(1.,(age-delay)/move)):(age>=delay?1.:0.);
                if(!a.value("linear",true))f=f*f*(3-2*f);
                const auto&path=a.at("path");std::vector<double>lengths;double total=0;
                for(size_t n=1;n<path.size();n++){double dx=path[n][0].get<double>()-path[n-1][0].get<double>(),dy=path[n][1].get<double>()-path[n-1][1].get<double>();total+=std::hypot(dx,dy);lengths.push_back(total);}
                size_t segment=0;while(segment+1<lengths.size()&&lengths[segment]<total*f)segment++;
                double before=segment?lengths[segment-1]:0,span=lengths[segment]-before,part=span>0?(total*f-before)/span:0;
                auto coord=[&](int k){return path[segment][k].get<double>()+(path[segment+1][k].get<double>()-path[segment][k].get<double>())*part;};
                bool rel=a.value("relative",false);d.x=coord(0)*width/(rel?1.:672.);d.y=coord(1)*height/(rel?1.:438.)+22;
                d.alpha=a.value("alpha0",1.)+(a.value("alpha1",1.)-a.value("alpha0",1.))*age/p.item.life;
                d.angle=a.value("rotate_z",0.);d.yscale=std::cos(a.value("rotate_y",0.)*3.141592653589793/180.);d.outline=a.value("outline",true);
            }catch(const std::exception&){continue;}}
            result.push_back(d);
        }return result;
    }
};
// Build on the owning font/UI thread, yielding between rows. Keep the previous
// published timeline intact until the whole new placement is ready. A single
// row may exceed the time budget; its text is bounded to 640 bytes by rows().
class Builder {
    Timeline pending;const std::vector<Item>*source=nullptr;size_t cursor=0;
public:
    static constexpr size_t max_rows=32;static constexpr uint64_t budget_us=3000;
    void start(const std::vector<Item>&items,double w,double h,double size=1,double speed=1){
        source=&items;cursor=0;pending.begin(w,h,size,speed);
    }
    bool busy()const{return source!=nullptr;}
    size_t processed()const{return cursor;}
    bool step(Timeline&published,const std::function<double(const std::string&,double)>&measure,const std::function<uint64_t()>&clock){
        if(!source)return false;uint64_t began=clock();size_t used=0;
        while(cursor<source->size()&&used<max_rows){
            pending.append((*source)[cursor++],measure);used++;
            if(clock()-began>=budget_us)break;
        }
        if(cursor<source->size())return false;
        published=std::move(pending);source=nullptr;return true;
    }
};
}
