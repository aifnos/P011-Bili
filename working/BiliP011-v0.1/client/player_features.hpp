// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "player_controls.hpp"
#include <nlohmann/json.hpp>
namespace p011_player {
// Read/write UI state is separate from playback state. Results must match both
// the current video serial and the exact outstanding request; no optimistic likes.
struct Features {
    using Json=nlohmann::json;
    std::string page,error,confirm,nonce,root;Json rows=Json::array(),relation=Json::object();
    Json saved_comments;std::vector<Json> history;int at=0,scroll=0,next=0,mode=3;bool more=false,busy=false;
    std::string cached_body;float cached_width=0;std::vector<std::string> cached_lines;
    unsigned seq=0,pending=0;uint32_t began=0;int serial=1,opened=0,comment_reads=0;
    bool enabled=false;
    Json tracks=Json::array(),chapters=Json::array(),cues=Json::array();
    bool subtitle_on=false;double subtitle_scale=.76,subtitle_offset=0;
    std::string subtitle_track,subtitle_text;std::vector<std::string> subtitle_lines;
    float subtitle_width=0;double subtitle_cached_scale=0;
    void close(){page.clear();pending=0;busy=false;confirm.clear();}
    void reset(int s){close();serial=s;nonce.clear();rows=Json::array();history.clear();root.clear();tracks=Json::array();chapters=Json::array();cues=Json::array();subtitle_track.clear();subtitle_text.clear();subtitle_lines.clear();subtitle_on=false;subtitle_offset=0;}
    Json request(const char*op,Json args,uint32_t now){busy=true;error.clear();pending=++seq;began=now;return {{"action","feature"},{"op",op},{"seq",pending},{"args",args}};}
    Json comments(int cursor,uint32_t now){return request("comments",{{"next",cursor},{"mode",mode},{"root",root}},now);}
    Json snapshot(){return {{"items",rows},{"at",at},{"scroll",scroll},{"next",next},{"more",more},{"root",root}};}
    void restore(const Json&s){rows=s.value("items",Json::array());at=s.value("at",0);scroll=s.value("scroll",0);next=s.value("next",0);more=s.value("more",false);root=s.value("root","");}
    static std::string message(const std::string&e){
        if(e=="LOGIN_REQUIRED")return "请先返回“我的”登录";
        if(e=="ACTION_DISABLED")return "自动测试中禁止账号操作";
        if(e=="ACTION_UNCONFIRMED")return "结果未确认，请刷新状态，勿重复投币";
        if(e=="ACTION_EXPIRED")return "操作已过期，请刷新后重试";
        if(e=="API_VERIFICATION_REQUIRED")return "B 站要求安全验证，请在官方端完成";
        if(e=="BUSY")return "上一请求未结束，请稍后刷新";
        return "请求未成功，请刷新重试";
    }
    bool accept(const Json&p){
        if(!pending||p.value("seq",0u)!=pending||p.value("serial",0)!=serial)return false;
        pending=0;busy=false;if(!p.value("ok",false)){error=message(p.value("error",""));return true;}
        auto d=p.value("data",Json::object());auto kind=p.value("feature","");
        if(kind=="comments"){rows=d.value("items",Json::array());at=0;scroll=0;next=d.value("next",0);more=d.value("more",false);comment_reads++;}
        if(kind=="relation"){relation=d;nonce=d.value("intent","");}
        if(kind=="favorites"){rows=d.value("items",Json::array());at=0;scroll=0;}
        if(kind=="player_metadata"){tracks=d.value("tracks",Json::array());chapters=d.value("chapters",Json::array());rows=page=="chapters"?chapters:tracks;at=0;scroll=0;}
        if(kind=="player_subtitle"){cues=d.value("cues",Json::array());subtitle_track=d.value("track","");subtitle_on=true;error="字幕已开启";}
        if(kind=="interaction"){
            nonce.clear();confirm.clear();page="interaction";
            if(d.value("state_available",false))relation=d.value("relation",Json::object());
            error="B 站已确认提交，请刷新状态";
            if(d.contains("triple")){auto t=d["triple"];error=std::string("三连结果：")+(t.value("like",false)?"赞成功 ":"赞未完成 ")+(t.value("coin",false)?"币成功 ":"币未完成 ")+(t.value("favorite",false)?"藏成功":"藏未完成");}
        }
        return true;
    }
    Rect box(const Layout&l)const{return l.portrait()?Rect{4,112,260,544}:Rect{150,0,500,268};}
    std::vector<Button> buttons(const Layout&l)const{
        std::vector<Button>b;auto r=box(l);auto add=[&](const char*a,std::string title,int col,int row,int value=0){float w=(r.w-24)/3;float y=l.portrait()?r.y+286+row*62:r.y+146+row*58;b.push_back({a,title,{r.x+6+col*(w+6),y,w,52},value});};
        if(page=="comments"){
            add("feature-up","上移",0,0);add("feature-down","下移",1,0);add("feature-replies",root.empty()?"查看回复":"返回主评",2,0);
            add("feature-prev","上一条",0,1);add("feature-next","下一条",1,1);add("feature-close","关闭",2,1);
        }else if(page=="interaction"){
            add("feature-like",relation.value("like",false)?"已赞 · 长按三连":"点赞 · 长按三连",0,0);
            add("feature-coin1",confirm=="coin1"?"确认投 1 币":"投 1 币",1,0);
            add("feature-coin2",confirm=="coin2"?"确认投 2 币":"投 2 币",2,0);
            add("feature-favorites","收藏夹",0,1);add("feature-refresh","刷新状态",1,1);add("feature-close","关闭",2,1);
        }else if(page=="favorites"){
            add("feature-folder",confirm=="favorite"?"确认更改":"切换收藏",0,0);add("feature-refresh","刷新状态",1,0);add("feature-close","关闭",2,0);
            add("feature-prev","上一夹",0,1);add("feature-next","下一夹",1,1);add("feature-account","返回互动",2,1);
        }else if(page=="subtitles"||page=="chapters"){
            add("feature-prev","上一项",0,0);add("feature-next","下一项",1,0);add("feature-select",page=="chapters"?"跳转章节":"选用字幕",2,0);
            if(page=="subtitles"){add("feature-sub-toggle",subtitle_on?"关闭字幕":"开启字幕",0,1);add("feature-sub-settings","字幕设置",1,1);}
            else {add("feature-refresh","刷新章节",0,1);}
            add("feature-close","关闭",2,1);
        }else if(page=="subtitle-settings"){
            add("feature-sub-size-","字号 −",0,0);add("feature-sub-size+","字号 +",1,0);add("feature-sub-reset","恢复默认",2,0);
            add("feature-sub-delay-","提前 0.5 秒",0,1);add("feature-sub-delay+","延后 0.5 秒",1,1);add("feature-close","关闭",2,1);
        }
        return b;
    }
    std::string subtitle(double position)const{
        if(!subtitle_on||cues.empty())return "";double time=position-subtitle_offset;
        auto it=std::upper_bound(cues.begin(),cues.end(),time,[](double t,const Json&r){return t<r.value("start",0.);});
        std::string text;int remaining=8;
        while(it!=cues.begin()&&remaining--){--it;if(time>=it->value("start",0.)&&time<it->value("end",0.)){auto line=it->value("text","");text=line+(text.empty()?"":"\n"+text);}}
        return text;
    }
};
// Bounded UTF-8 line wrapping; no HTML interpretation or text-as-command path.
template<class Measure> static std::vector<std::string> feature_lines(const std::string&text,float width,Measure measure){
    std::vector<std::string> rows;std::string line;size_t used=0;
    while(used<text.size()&&rows.size()<240){unsigned char c=text[used];size_t n=c<128?1:c<224?2:c<240?3:4;n=std::min(n,text.size()-used);std::string ch=text.substr(used,n);used+=n;
        if(ch=="\n"){rows.push_back(line);line.clear();continue;}
        if(!line.empty()&&measure(line+ch)>width){rows.push_back(line);line.clear();}line+=ch;
    }
    if(!line.empty())rows.push_back(line);return rows;
}
}
