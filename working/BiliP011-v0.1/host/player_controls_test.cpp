// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/player_controls.hpp"
#include "../client/player_gestures.hpp"
#include "../client/cached_media.hpp"
#include "../client/stream_transaction.hpp"
#include "../client/player_features.hpp"
#include <fcntl.h>
#include "../client/frame_telemetry.hpp"
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace p011_player;
int main(){int checks=0;auto check=[&](bool ok){if(!ok)throw std::runtime_error(std::to_string(checks));checks++;};
try{
 Features f;f.serial=3;f.page="comments";auto request=f.comments(0,10);check(f.busy&&request["op"]=="comments");
 check(!f.accept({{"op","feature"},{"seq",request["seq"]},{"serial",2},{"ok",true}}));
 check(f.accept({{"op","feature"},{"seq",request["seq"]},{"serial",3},{"feature","comments"},{"ok",true},{"data",{{"items",nlohmann::json::array({{{"id","1"},{"text","内容"}}})},{"next",2},{"more",true}}}}));
 check(!f.busy&&f.rows.size()==1&&f.more&&f.comment_reads==1);f.close();check(!f.accept({{"seq",1},{"serial",3}}));
 f.request("relation",{},10);f.reset(4);check(!f.pending&&f.nonce.empty()&&f.serial==4);
 auto lines=feature_lines("abcde",2.f,[](const std::string&s){return float(s.size());});check(lines.size()==3&&lines[0]=="ab"&&lines[2]=="e");
 for(auto orientation:{Orientation::Landscape,Orientation::PortraitClockwise}){Layout l;l.orientation=orientation;for(const char*page:{"comments","interaction","favorites"}){f.page=page;for(const auto&b:f.buttons(l))check(b.box.w>=72&&b.box.h>=44&&b.box.x>=0&&b.box.y>=0&&b.box.x+b.box.w<=l.width()&&b.box.y+b.box.h<=l.height());}}
 StreamTransaction tx(nlohmann::json{{"video","old"}});check(!tx.begin(0,{},0,false,0));
 check(tx.begin(1,{{"video","new"}},37,true,10));check(tx.current["video"]=="old"&&tx.position==37&&tx.paused);
 check(!tx.begin(2,{},0,false,11)&&!tx.expired(20010)&&tx.expired(20011));
 check(tx.recover(20012)&&!tx.recover(20013));tx.ready();check(tx.current["video"]=="old"&&!tx.seq&&!tx.restoring);
 check(tx.begin(3,{{"video","new"}},42,false,30000));tx.ready();check(tx.current["video"]=="new"&&!tx.seq);
 check(tx.begin(4,{},0,false,0xfffffff0));check(!tx.expired(20)&&tx.expired(21000));
 FrameReload replay;check(!replay.begin(false,false,0)&&!replay.begin(true,true,0));
 check(replay.begin(true,false,10)&&!replay.begin(true,false,11));
 check(!replay.expired(20010)&&replay.expired(20011));replay.frame();replay.frame();
 check(!replay.pending&&replay.requested==1&&replay.completed==1&&!replay.failures);
 check(replay.begin(true,false,0xfffffff0));check(!replay.expired(20)&&replay.expired(21000));
 replay.fail();replay.fail();check(!replay.pending&&replay.failures==1&&replay.completed==1);
 check(replay.begin(true,false,10));replay.cancel();replay.frame();check(!replay.pending&&replay.completed==1);
 char scratch[]="/tmp/p011-cache-test-XXXXXX";check(mkdtemp(scratch)!=nullptr);setenv("P011_CLIENT_ROOT",scratch,1);
 std::string dir=std::string(scratch)+"/preload",file=dir+"/0123456789abcdef-v.m4s",uri="file://"+file;
 check(mkdir(dir.c_str(),0700)==0);int fd=open(file.c_str(),O_CREAT|O_EXCL|O_RDWR,0600);check(fd>=0);
 check(p011_media::cached_path(uri).empty());check(write(fd,"test",4)==4);check(p011_media::cached_path(uri)==file);
 check(p011_media::cached_path("file:///etc/passwd").empty());check(p011_media::cached_path("file://"+dir+"/../0123456789abcdef-v.m4s").empty());
 check(chmod(file.c_str(),0644)==0&&p011_media::cached_path(uri).empty());check(chmod(file.c_str(),0600)==0);
 check(ftruncate(fd,8*1024*1024+1)==0&&p011_media::cached_path(uri).empty());close(fd);check(unlink(file.c_str())==0);
 check(symlink("/etc/passwd",file.c_str())==0&&p011_media::cached_path(uri).empty());check(unlink(file.c_str())==0);check(rmdir(dir.c_str())==0);check(rmdir(scratch)==0);unsetenv("P011_CLIENT_ROOT");
 HoldRate hold;check(!hold.release());check(!hold.begin(0));check(hold.begin(1.25));check(hold.active&&!hold.begin(1));check(hold.release());check(hold.restore_pending&&hold.original==1.25&&!hold.active);check(!hold.begin(1));hold.restored();check(hold.begin(2)&&hold.release());hold.restored();check(!hold.active&&!hold.restore_pending);
 VideoGesture g;g.begin({100,200},100,20,120,500,true);g.move({180,204});check(g.axis==VideoGesture::Horizontal&&g.target>20);g.move({180,0});check(g.axis==VideoGesture::Horizontal&&!g.commit(250));
 g.begin({100,400},100,20,120,268,true);g.move({105,320});check(g.axis==VideoGesture::Vertical&&g.commit(220));check(!g.commit(600));
 g.begin({100,400},100,20,120,268,true);g.move({102,200});check(g.commit(1500));
 g.begin({100,400},100,20,120,500,false);g.move({100,200});check(g.axis==VideoGesture::Rejected);
 g.begin({100,400},100,20,120,500,true);g.move({110,390});check(g.axis==VideoGesture::Pending);g.move({-500,400});check(g.target==0);g.move({1000,400});check(g.target<120);
 FeedSlide slide;slide.drag(-200);slide.release(true,100);check(slide.waiting);check(slide.sample(200)<-200&&slide.sample(400)==-800);slide.ready(500);check(slide.offset==800&&!slide.waiting);check(slide.sample(740)==0&&!slide.active());
 slide.drag(90);slide.release(false,800);check(!slide.waiting&&slide.sample(1100)==0);slide.drag(-200);slide.release(true,1200);slide.cancel(1210);check(!slide.waiting&&slide.sample(1500)==0);
 for(auto direction:{Orientation::Landscape,Orientation::PortraitClockwise})for(int menu=0;menu<8;menu++)for(bool visible:{false,true})for(bool story:{false,true})for(int page:{0,1,2}){
  Layout l{direction};auto all=buttons(l,visible,false,true,menu,{0,6,16,32,64,74,80,112,116,120},page,{0,7,12,13},story);
  for(const auto&b:all){check(b.box.x>=0&&b.box.y>=0&&b.box.x+b.box.w<=l.width()&&b.box.y+b.box.h<=l.height());check(b.box.w>=80&&b.box.h>=42);
   check(b.action!="seek-"&&b.action!="seek+");
   Point center={b.box.x+b.box.w/2,b.box.y+b.box.h/2},decoded{};check(l.logical(l.physical(center),decoded)&&b.box.contains(decoded));
  }
  auto v=video_box(l,story);check(v.x>=0&&v.y>=0&&v.x+v.w<=l.width()&&v.y+v.h<=l.height());
  auto p=progress_box(l,story);check(p.h>=40&&p.x>=0&&p.y>=0&&p.x+p.w<=l.width()&&p.y+p.h<=l.height());
  check(progress_ratio(l,{p.x-10,p.y},story)==0);check(progress_ratio(l,{p.x+p.w+10,p.y},story)==1);
  for(double ratio:{0.,.25,.5,.75,1.}){Point logical={p.x+6+(p.w-12)*ratio,p.y+p.h/2},decoded{};check(l.logical(l.physical(logical),decoded));check(std::abs(progress_ratio(l,decoded,story)-ratio)<.0001);}
  if(!menu)for(const auto&b:all)check(!(b.box.contains({p.x,p.y})||b.box.contains({p.x+p.w-1,p.y+p.h-1})));
  // Within a settings panel, every visible control must have its own hit area.
  if(menu)for(size_t i=0;i<all.size();i++)for(size_t j=i+1;j<all.size();j++){
   auto a=all[i].box,b=all[j].box;check(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
  }
 }
 for(auto direction:{Orientation::Landscape,Orientation::PortraitClockwise}){
  auto rows=buttons(Layout{direction},false,false,true,0,{},0,{},false);
  check(std::count_if(rows.begin(),rows.end(),[](const Button&b){return b.action=="feature-comments";})==1);
  check(std::count_if(rows.begin(),rows.end(),[](const Button&b){return b.action=="rate-menu";})==1);
 }
 std::string endpoint="http://127.0.0.1:1234/"+std::string(48,'a')+"/";setenv("P011_MEDIA_RELAY",endpoint.c_str(),1);
 check(p011_media::relay_url(endpoint+"0123456789abcdef-v"));
 for(const auto&s:{endpoint+"../secret",endpoint+"0123456789abcdef-v?url=x",std::string("http://127.0.0.1:12/0123456789abcdef-v"),std::string("https://example.com/")})check(!p011_media::relay_url(s));
 unsetenv("P011_MEDIA_RELAY");check(!p011_media::relay_url(endpoint+"0123456789abcdef-v"));
 auto s=Settings::from({{"aspect",999},{"dm_area",50},{"dm_opacity",true},{"dm_size",120},{"dm_speed",125}});
 check(s.aspect==0&&s.area==50&&s.opacity==100&&s.size==120&&s.speed==125);
 for(const char*a:{"dm-area","dm-opacity","dm-size","dm-speed"}){auto before=s.json();for(int n=0;n<4;n++)check(s.change(a));check(s.json()==before);}
 check(s.change("dm-reset")&&s.area==100&&s.opacity==100&&s.size==100&&s.speed==100);
 check(quality_label(333)!="自动"&&quality_label(127)=="8K");
 FrameTelemetry fps;for(int i=0;i<60;i++)fps.swap(1);for(int i=0;i<30;i++)fps.swap(3);for(int i=0;i<20;i++)fps.swap(5);fps.swap(0);fps.sample(1000);
 check(fps.submitted==60&&fps.redrawn==30&&fps.repeated==20&&fps.submitted_fps==60);fps.sample(2000);check(fps.submitted_fps==0);
 for(bool loaded:{false,true})for(bool paused:{false,true})for(bool active:{false,true})for(bool switching:{false,true})
  for(double rate:{0.,3.,29.71,46.23,60.,-1.,10001.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()}){
   auto state=frame_rate_state(loaded,paused,active,switching,rate);
   auto expected=!loaded||switching?FrameRateState::Loading:paused?FrameRateState::Paused:!active?FrameRateState::Waiting:
       !std::isfinite(rate)||rate<0||rate>10000?FrameRateState::Unavailable:FrameRateState::Measured;
   check(state==expected);
   auto text=frame_rate_text(state,rate);
   check(!text.empty());check((text.find("fps")!=std::string::npos)==(state==FrameRateState::Measured));
  }
 check(frame_rate_text(FrameRateState::Paused,3.)=="已暂停 · 帧率不适用");
 check(frame_rate_text(FrameRateState::Measured,46.23)=="实测提交 46fps · 非屏幕刷新率");
 check(frame_rate_text(FrameRateState::Measured,std::numeric_limits<double>::quiet_NaN())=="帧率采样暂不可用");
 check(fps.submitted==60&&fps.redrawn==30&&fps.repeated==20&&fps.submitted_fps==0);
 PlaybackHealth health;check(!health.observe(1000,true,60,20,.3));check(!health.observe(4999,true,60,20,.3));check(health.observe(5000,true,60,20,.3));check(health.limited&&health.warned);check(!health.observe(9000,true,60,20,.3));
 check(!health.observe(9500,false,60,0,2)&&!health.limited);
 health={};check(!health.observe(1000,true,30,30,.01));check(!health.observe(10000,true,30,30,.01)&&!health.warned);
 check(!health.observe(11000,true,60,20,.3));check(!health.observe(12000,false,60,20,.3));check(!health.observe(16000,true,60,20,.3));check(!health.warned);
 health={};check(!health.observe(1000,true,30,20,.02));check(health.observe(5000,true,30,20,.02));check(health.limited);
 health={};check(!health.observe(1000,true,30,30,.3));check(health.observe(5000,true,30,30,.3));check(health.limited);
 check(!health.observe(6000,true,30,30,.02)&&!health.limited);
 std::cout<<"{\"checks\":"<<checks<<",\"passed\":true,\"device_tested\":false}\n";return 0;
}catch(const std::exception&e){std::cout<<"{\"passed\":false,\"failed_check\":"<<e.what()<<"}\n";return 1;}}
