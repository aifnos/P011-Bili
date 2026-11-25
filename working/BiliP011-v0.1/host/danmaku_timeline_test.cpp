// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/danmaku_timeline.hpp"
#include <iostream>
#include <stdexcept>
using namespace p011_dm;
int main(){int checks=0;auto check=[&](bool b){checks++;if(!b)throw std::runtime_error(std::to_string(checks));};
 try{
  std::vector<Item>rows;for(int mode=1;mode<=6;mode++){Item d;d.mode=mode;d.time=1;d.text="type"+std::to_string(mode);d.life=mode==4||mode==5?4:8;rows.push_back(d);}
  Timeline t;t.build(rows,500,268,[](const std::string&s,double scale){return s.size()*15*scale;});
  auto a=t.at(2),b=t.at(2.01);check(a.size()==6);check(a.size()==b.size());
  for(size_t i=0;i<a.size();i++){check(a[i].source==b[i].source);check(a[i].y==b[i].y);int mode=a[i].source->item.mode;
   if(mode<=3)check(a[i].x>b[i].x);if(mode==6)check(a[i].x<b[i].x);if(mode==4||mode==5)check(a[i].x==b[i].x);
  }
  check(a[3].y>a[4].y);check(t.at(0).empty());check(t.at(99).empty());
  // Thousands of ticks and backward seeks must produce exactly the same
  // placement. A departing comment cannot make another switch tracks/blink.
  for(double now=1;now<8;now+=.01){auto frame=t.at(now);for(auto&d:frame){auto same=t.at(now);bool found=false;for(auto&e:same)if(e.source==d.source){found=true;check(d.x==e.x&&d.y==e.y);}check(found);}}
  auto again=t.at(2);for(size_t i=0;i<a.size();i++)check(a[i].x==again[i].x&&a[i].y==again[i].y);
  for(int n=0;n<300;n++){Item d;d.time=n*.07;d.text=std::string(n%50+1,'x');rows.push_back(d);}
  std::stable_sort(rows.begin(),rows.end(),[](const Item&a,const Item&b){return a.time<b.time;});
  t.build(rows,500,268,[](const std::string&s,double scale){return s.size()*15*scale;});check(t.dropped>0);
  for(double now=0;now<35;now+=.05){auto frame=t.at(now);for(size_t i=0;i<frame.size();i++)for(size_t j=i+1;j<frame.size();j++){
   const auto&a=frame[i],&b=frame[j];if(a.y==b.y)check(a.x+a.source->width<=b.x||b.x+b.source->width<=a.x);
  }}
  for(double area:{.25,.5,.75,1.})for(double size:{.8,1.,1.2,1.4})for(double speed:{.75,1.,1.25,1.5}){
   double height=174*area;t.build(rows,500,height,[](const std::string&s,double k){return s.size()*15*k;},size,speed);
   for(double now=0;now<25;now+=.25)for(auto&d:t.at(now)){check(d.y>=0&&d.y<=height);check(d.source->scale>0);}
  }
  // Incremental preparation publishes exactly once, with identical placement
  // to the full build, independent of batch boundaries and backward seeks.
  auto measure=[](const std::string&s,double scale){return s.size()*15*scale;};
  for(int ticks:{0,100,1500,4000}){
   Builder builder;Timeline published,reference;uint64_t clock=0;
   reference.build(rows,500,174,measure);builder.start(rows,500,174);
   size_t previous=0;unsigned steps=0;
   while(builder.busy()){
    bool committed=builder.step(published,measure,[&](){clock+=ticks;return clock;});steps++;
    check(builder.processed()-previous<=Builder::max_rows);
    if(ticks>=1500)check(builder.processed()-previous<=2);
    previous=builder.processed();if(!committed)check(published.size()==0);
    check(steps<=rows.size()+1);
   }
   check(published.size()==reference.size());check(published.dropped==reference.dropped);
   for(double now=0;now<35;now+=.2){auto a=published.at(now),b=reference.at(now);check(a.size()==b.size());
    for(size_t i=0;i<a.size();i++){check(a[i].source->item.text==b[i].source->item.text);check(a[i].x==b[i].x&&a[i].y==b[i].y);}}
   check(!builder.step(published,measure,[&](){return clock;}));
   builder.start(rows,100,200);builder.step(published,measure,[&](){return clock;});
   std::vector<Item>empty;builder.start(empty,200,300);check(builder.step(published,measure,[&](){return clock;}));check(published.size()==0);
  }
  t.begin(500,174);Item first;first.text="first";first.time=1;t.append(first,measure);
  Item second=first;second.text="second";second.time=22;t.append(second,measure);
  auto before=t.at(23);check(before.size()==1);double x=before[0].x,y=before[0].y;
  t.prune(3);auto after=t.at(23);check(after.size()==1);check(after[0].x==x&&after[0].y==y);check(t.size()==1);
  second.time=24;t.append(second,measure);check(t.at(25).size()>=1);t.prune(100);check(t.size()==0);second.time=101;t.append(second,measure);check(t.at(102).size()==1);
  std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"device_tested\":false}\n";return 0;
 }catch(const std::exception&e){std::cout<<"failed "<<e.what()<<'\n';return 1;}}
