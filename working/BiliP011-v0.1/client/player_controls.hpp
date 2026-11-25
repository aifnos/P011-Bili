// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "player_geometry.hpp"
#include "player_settings.hpp"
#include <algorithm>
#include <string>
#include <vector>
namespace p011_player {
struct Rect {float x,y,w,h;bool contains(Point p)const{return p.x>=x&&p.x<x+w&&p.y>=y&&p.y<y+h;}};
struct Button {std::string action,label;Rect box;int value=0;};
// Releasing during a hardware re-preroll must queue restoration, not leave 2x
// active merely because the ordinary rate control is temporarily unavailable.
struct HoldRate {
    bool active=false,restore_pending=false;
    double original=1.;
    bool begin(double rate){if(active||restore_pending||!std::isfinite(rate)||rate<.5||rate>2.)return false;original=rate;active=true;return true;}
    bool release(){if(!active)return false;active=false;restore_pending=true;return true;}
    void restored(){restore_pending=false;}
};
inline Rect video_box(const Layout &layout,bool story=false){return layout.portrait()?(story?Rect{0,0,268,800}:Rect{0,66,268,590}):Rect{150,0,500,268};}
// The entire time/progress strip is a touch target, not just the 4 px line.
inline Rect progress_box(const Layout &layout,bool story=false){return layout.portrait()?(story?Rect{6,754,256,40}:Rect{6,622,256,40}):Rect{154,226,492,42};}
inline double progress_ratio(const Layout &layout,Point p,bool story=false){
    Rect b=progress_box(layout,story);if(!std::isfinite(p.x))return 0;
    return std::max(0.,std::min(1.,(p.x-b.x-6)/(b.w-12)));
}
inline std::string quality_label(int q){switch(q){case 0:return "自动";case 6:return "240P";case 16:return "360P";case 32:return "480P";case 64:return "720P";case 74:return "720P60";case 80:return "1080P";case 112:return "1080P+";case 116:return "1080P60";case 120:return "4K";case 125:return "HDR";case 126:return "杜比视界";case 127:return "8K";default:return "画质 "+std::to_string(q);}}
inline std::string codec_label(int c){return c==7?"AVC":c==12?"HEVC":c==13?"AV1":"自动";}
inline std::vector<Button> buttons(const Layout &l,bool overlay,bool paused,bool dm,int menu,const std::vector<int>&qualities,int page=0,const std::vector<int>&codecs={0,7},bool story=false,const Settings&s={}){
    std::vector<Button>b;auto add=[&](const char*a,std::string label,Rect r,int v=0){b.push_back({a,label,r,v});};
    if(l.portrait()&&story){
        add("back","返回",{6,6,80,54});add("more","设置",{182,6,80,54});
        if(overlay&&!menu)add("pause",paused?"继续":"暂停",{94,6,80,54});
    }else if(l.portrait()){
        add("back","返回",{6,4,80,58});add("rotate","横屏",{94,4,80,58});add("more","更多",{182,4,80,58});
        add("feature-comments","评论",{6,668,80,58});add("danmaku",dm?"弹幕开":"弹幕关",{94,668,80,58});add("rate-menu","倍速",{182,668,80,58});
        add("previous","上一条",{6,734,80,60});add("pause",paused?"继续":"暂停",{94,734,80,60});add("next","下一条",{182,734,80,60});
    }else{
        add("back","返回",{8,6,132,78});add("feature-comments","评论",{8,92,132,78});add("volume-","音量 −",{8,178,132,78});
        add("pause",paused?"继续":"暂停",{660,6,132,78});add("rate-menu","倍速",{660,92,132,78});add("volume+","音量 ＋",{660,178,132,78});
        if(overlay&&!menu){add("quality-menu","画质",{156,6,116,44});add("danmaku",dm?"弹幕开":"弹幕关",{280,6,116,44});add("rotate","竖屏",{404,6,116,44});add("more","更多",{528,6,116,44});}
    }
    if(menu==1||menu==3){
        const auto&rows=menu==1?qualities:codecs;int count=l.portrait()?5:6;
        int pages=std::max(1,(int(rows.size())+count-1)/count);page=std::max(0,std::min(pages-1,page));
        for(int i=0;i<count&&page*count+i<int(rows.size());i++){
            int value=rows[page*count+i];add(menu==1?"quality":"codec",menu==1?quality_label(value):codec_label(value),
                l.portrait()?Rect{10.f,192.f+i*60.f,248,52}:Rect{158.f+(i%3)*162,58.f+(i/3)*74,154,66},value);
        }
        float y=l.portrait()?536:218;float x=l.portrait()?8:158;float bw=l.portrait()?80:154;
        add("menu-prev","‹",{x,y,bw,44});add("close","关闭",{x+bw+6,y,bw,44});add("menu-next","›",{x+2*(bw+6),y,bw,44});
    }else if(menu==2){
        const char* actions[]={"quality-menu","codec-menu","aspect-menu","dm-menu","dm-layout","stats-menu","volume-","volume+","previous","next","rotate","close","feature-comments","feature-account","listen","feature-subtitles","feature-chapters","rate-menu"};
        std::string labels[]={"画质","编码","画面比例","弹幕类型","弹幕设置","播放信息","音量 −","音量 ＋","上一条","下一条",l.portrait()?"横屏":"旋转观看","关闭","评论区","点赞 / 收藏","听视频","CC 字幕","视频章节","播放倍速"};
        page=std::max(0,std::min(2,page));
        for(int i=0;i<6;i++)add(actions[i+page*6],labels[i+page*6],l.portrait()?Rect{10.f+(i%2)*128.f,214.f+(i/2)*80.f,120,68}:Rect{158.f+(i%3)*162.f,58.f+(i/3)*74.f,154,66});
        float y=l.portrait()?536:218,x=l.portrait()?8:158,bw=l.portrait()?80:154;
        add("menu-prev","‹",{x,y,bw,44});add("close","关闭",{x+bw+6,y,bw,44});add("menu-next","›",{x+2*(bw+6),y,bw,44});
    }else if(menu==4){
        const char*labels[]={"总开关","滚动","顶部","底部","彩色","高级"};
        for(int i=0;i<6;i++)add("dm-filter",labels[i],l.portrait()?Rect{10.f+(i%2)*128.f,214.f+(i/2)*80.f,120,68}:Rect{158.f+(i%3)*162.f,64.f+(i/3)*72.f,154,60},i);
        add("close","关闭",l.portrait()?Rect{10,530,248,52}:Rect{158,218,478,44});
    }else if(menu==5||menu==6){
        const char*actions[]={"dm-opacity","dm-area","dm-size","dm-speed","dm-reset","close"};
        std::string labels[]={"不透明度 "+std::to_string(s.opacity)+"%","显示区域 "+std::to_string(s.area)+"%","字号 "+std::to_string(s.size)+"%","速度 "+std::to_string(s.speed)+"%","恢复默认","关闭"};
        for(int i=0;i<6;i++)add(menu==5?actions[i]:i==5?"close":"aspect",menu==5?labels[i]:i==5?"关闭":aspect_label(i),l.portrait()?Rect{10.f+(i%2)*128.f,214.f+(i/2)*80.f,120,68}:Rect{158.f+(i%3)*162.f,64.f+(i/3)*72.f,154,60},i);
        add("settings-back","返回设置",l.portrait()?Rect{10,530,248,52}:Rect{158,218,478,44});
    }else if(menu==9){
        const int rates[]={50,75,100,125,150,200};const char*labels[]={"0.5×","0.75×","1.0×","1.25×","1.5×","2.0×"};
        for(int i=0;i<6;i++)add("rate",labels[i],l.portrait()?Rect{10.f+(i%2)*128.f,214.f+(i/2)*80.f,120,68}:Rect{158.f+(i%3)*162.f,64.f+(i/3)*72.f,154,60},rates[i]);
        add("close","关闭",l.portrait()?Rect{10,530,248,52}:Rect{158,218,478,44});
    }else if(menu==7){add("close","关闭",l.portrait()?Rect{10,530,248,52}:Rect{158,218,478,44});}
    return b;
}
}
