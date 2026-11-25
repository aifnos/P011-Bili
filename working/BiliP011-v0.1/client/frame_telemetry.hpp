// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cmath>
#include <string>
namespace p011_player {
// Counts distinct frames handed to a completed buffer swap, not UI redraws,
// source metadata, monitor refresh, or a claim of physical panel scanout.
struct FrameTelemetry {
    uint64_t submitted=0,redrawn=0,repeated=0,samples=0;
    uint32_t sampled_at=0;
    double submitted_fps=0;
    void swap(uint64_t flags) {
        if(!(flags&1))return;
        if(flags&2)redrawn++;
        else if(flags&4)repeated++;
        else submitted++;
    }
    void sample(uint32_t now) {
        uint32_t dt=now-sampled_at;
        if(dt>=1000){submitted_fps=(submitted-samples)*1000.0/dt;samples=submitted;sampled_at=now;}
    }
};
// Presentation only. Keep the original counters, sample windows and health
// thresholds intact; paused/loading windows are not playback-performance data.
enum class FrameRateState : unsigned { Loading=0, Paused=1, Waiting=2, Measured=3, Unavailable=4 };
inline FrameRateState frame_rate_state(bool loaded,bool paused,bool active,bool switching,double rate){
    if(!loaded||switching)return FrameRateState::Loading;
    if(paused)return FrameRateState::Paused;
    if(!active)return FrameRateState::Waiting;
    if(!std::isfinite(rate)||rate<0||rate>10000)return FrameRateState::Unavailable;
    return FrameRateState::Measured;
}
inline std::string frame_rate_text(FrameRateState state,double rate){
    if(state==FrameRateState::Loading)return "加载中 · 帧率待采样";
    if(state==FrameRateState::Paused)return "已暂停 · 帧率不适用";
    if(state==FrameRateState::Waiting)return "等待画面 · 帧率待采样";
    if(state!=FrameRateState::Measured||!std::isfinite(rate)||rate<0||rate>10000)return "帧率采样暂不可用";
    return "实测提交 "+std::to_string(int(rate+.5))+"fps · 非屏幕刷新率";
}
// Advisory only: never silently switch quality, alter playback speed, or
// count interpolated/UI frames as decoded video. Suppress brief startup,
// seek and buffering transients; emit at most once per stream.
struct PlaybackHealth {
    uint32_t bad_since=0;
    bool tracking=false,warned=false,limited=false;
    bool observe(uint32_t now,bool active,double source,double submitted,double avsync) {
        bool bad=active&&std::isfinite(source)&&std::isfinite(submitted)&&std::isfinite(avsync)&&
            source>0&&(submitted<source*.8||std::abs(avsync)>.2);
        if(!bad){tracking=false;limited=false;return false;}
        if(!tracking){bad_since=now;tracking=true;}
        limited=now-bad_since>=4000;
        if(limited&&!warned){warned=true;return true;}
        return false;
    }
};
}
