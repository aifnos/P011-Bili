// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/player_packets.hpp"
#include <iostream>
using namespace p011_ipc;
using J=p011_dm::Json;
int main(){unsigned checks=0;auto check=[&](bool ok){checks++;if(!ok)throw std::runtime_error(std::to_string(checks));};
 try{
    auto wait=[&](Decoder&decoder){std::unique_ptr<Packet> p;auto until=std::chrono::steady_clock::now()+std::chrono::seconds(2);
        while(!decoder.take(p)){check(std::chrono::steady_clock::now()<until);std::this_thread::sleep_for(std::chrono::milliseconds(1));}return p;};
    Decoder decoder;std::string raw=R"({"op":"test","action":"pause"})";
    check(decoder.submit(raw,raw.size()));check(!decoder.submit(raw,raw.size()));
    auto p=wait(decoder);check(p->value["action"]=="pause");check(p->danmaku.empty());
    for(const std::string&bad:{"not json","[]","null","{",R"({"op":13})"}){
        check(decoder.submit(bad,bad.size()));auto q=wait(decoder);check(q->danmaku.empty());
    }
    J items=J::array();for(int i=0;i<2000;i++)items.push_back({{"text","test "+std::to_string(i)},{"time",2000-i},{"mode",i%6+1}});
    raw=J{{"op","danmaku"},{"ok",true},{"serial",7},{"items",items}}.dump();
    check(decoder.submit(raw,raw.size()));check(!decoder.submit(raw,raw.size()));p=wait(decoder);
    check(p->value["serial"]==7);check(!p->value.contains("items"));check(p->danmaku.size()==2000);
    for(size_t i=1;i<p->danmaku.size();i++)check(p->danmaku[i-1].time<=p->danmaku[i].time);
    auto stats=decoder.stats();check(stats.packets==7);check(stats.danmaku_packets==1);check(stats.max_bytes==raw.size());
    items.push_back({{"text","excess"},{"time",0}});raw=J{{"op","danmaku"},{"items",items}}.dump();
    check(decoder.submit(raw,raw.size()));check(wait(decoder)->danmaku.empty());
    bool rejected=false;try{decoder.submit(raw,Decoder::max_bytes+1);}catch(const std::length_error&){rejected=true;}check(rejected);
    rejected=false;try{decoder.submit(raw,raw.size()+1);}catch(const std::length_error&){rejected=true;}check(rejected);
    // The worker is joined even when destruction happens with work pending.
    for(int i=0;i<20;i++){Decoder temporary;check(temporary.submit(raw,raw.size()));}
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"device_tested\":false}\n";return 0;
 }catch(const std::exception&e){std::cerr<<"failed "<<e.what()<<'\n';return 1;}
}
