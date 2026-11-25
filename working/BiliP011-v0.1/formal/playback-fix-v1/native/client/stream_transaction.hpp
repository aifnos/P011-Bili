// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <nlohmann/json.hpp>
namespace p011_player {
// Private URLs exist in memory only. Commit is driven by a rendered new frame.
struct StreamTransaction {
    nlohmann::json current, next;
    unsigned seq=0, started=0;
    double position=0;
    bool paused=false, restoring=false;
    explicit StreamTransaction(const nlohmann::json&initial):current(initial){}
    bool begin(unsigned request,const nlohmann::json&packet,double at,bool pause,unsigned now){
        if(!request||seq)return false;
        seq=request;next=packet;position=at;paused=pause;started=now;restoring=false;return true;
    }
    bool recover(unsigned now){if(!seq||restoring)return false;restoring=true;started=now;return true;}
    void ready(){if(!restoring)current=next;next=nlohmann::json();seq=0;restoring=false;}
    bool expired(unsigned now)const{return seq&&now-started>20000;}
};
// Vendor OMX flushes after EOS or prolonged playback may never return.
// Reopens are sequential and confirmed only by a displayed fresh frame.
struct FrameReload {
    bool pending=false;
    unsigned started=0, requested=0, completed=0, failures=0;
    bool begin(bool enabled,bool switching,unsigned now){
        if(!enabled||switching||pending)return false;
        pending=true;started=now;requested++;return true;
    }
    void cancel(){pending=false;}
    void frame(){if(pending){pending=false;completed++;}}
    void fail(){if(pending){pending=false;failures++;}}
    bool expired(unsigned now)const{return pending&&now-started>20000;}
};
}
