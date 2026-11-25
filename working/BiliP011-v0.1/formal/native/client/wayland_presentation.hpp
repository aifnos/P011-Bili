// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Opt-in numeric-only observer on SDL's existing connection and surface.
// No new rendering surface, frame pacing, system clock change or roundtrip.
// Protocol: third_party/presentation-time-v1.xml (upstream license retained).
#ifdef P011_PRESENTATION_FEEDBACK
#ifndef SDL_VIDEO_DRIVER_WAYLAND
#define SDL_VIDEO_DRIVER_WAYLAND 1
#endif
#include <SDL_syswm.h>
#include "presentation-time-client-protocol.h"
#include <poll.h>
#include <array>
#include <vector>
#include <cmath>
#include <ctime>
class WaylandPresentation {
    struct Entry {
        WaylandPresentation*owner=nullptr;struct wp_presentation_feedback*proxy=nullptr;
        uint64_t commit=0,video=0,submit_ns=0;uint32_t source_serial=0;
        int64_t pts_us=-1;bool playing=false;
    };
    // Row: outcome(1=presented,2=discarded,3=unresolved), commit, video id,
    // source serial, source PTS us, submit ns, presentation ns, refresh ns,
    // refresh sequence, flags, stable-playing-at-submission.
    using Row=std::array<int64_t,11>;
    static constexpr size_t pending_limit=256,row_limit=32768;
    wl_display*display=nullptr;wl_surface*surface=nullptr;wl_registry*registry=nullptr;
    wp_presentation*presentation=nullptr;
    std::array<Entry,pending_limit>pending{};std::vector<Row>rows;
    uint64_t commits=0,video=0,last_submit=0;uint32_t serial=0,global_name=0;
    int64_t pts=-1;int64_t clock_id=-1;
    uint64_t capacity_skips=0,invalid_timestamps=0,clock_errors=0;
    bool removed=false;
    static void global(void*data,wl_registry*r,uint32_t name,const char*iface,uint32_t version){
        auto*self=static_cast<WaylandPresentation*>(data);
        if(!self->presentation&&version>=1&&!strcmp(iface,"wp_presentation")){
            self->presentation=static_cast<wp_presentation*>(wl_registry_bind(r,name,&wp_presentation_interface,1));
            if(self->presentation){self->global_name=name;wp_presentation_add_listener(self->presentation,&clock_listener,self);}
        }
    }
    static void global_remove(void*data,wl_registry*,uint32_t name){
        auto*self=static_cast<WaylandPresentation*>(data);if(name==self->global_name)self->removed=true;
    }
    static void clock_event(void*data,wp_presentation*,uint32_t id){
        static_cast<WaylandPresentation*>(data)->clock_id=id;
    }
    static void sync_output(void*,struct wp_presentation_feedback*,wl_output*){}
    static void presented(void*data,struct wp_presentation_feedback*,uint32_t hi,uint32_t lo,uint32_t nsec,
                          uint32_t refresh,uint32_t seq_hi,uint32_t seq_lo,uint32_t flags){
        auto*entry=static_cast<Entry*>(data);auto*self=entry->owner;
        const uint64_t sec=(uint64_t(hi)<<32)|lo,sequence=(uint64_t(seq_hi)<<32)|seq_lo;
        if(nsec>=1000000000||sec>(uint64_t(INT64_MAX)-nsec)/1000000000||sequence>uint64_t(INT64_MAX)){
            self->invalid_timestamps++;self->record(*entry,3,0,0,0,0);
        }else self->record(*entry,1,sec*1000000000+nsec,refresh,sequence,flags);
    }
    static void discarded(void*data,struct wp_presentation_feedback*){
        auto*entry=static_cast<Entry*>(data);entry->owner->record(*entry,2,0,0,0,0);
    }
    inline static const wl_registry_listener registry_listener={global,global_remove};
    inline static const wp_presentation_listener clock_listener={clock_event};
    inline static const wp_presentation_feedback_listener feedback_listener={sync_output,presented,discarded};
    void record(Entry&e,int outcome,uint64_t time,uint32_t refresh,uint64_t sequence,uint32_t flags){
        if(rows.size()<row_limit)rows.push_back({outcome,int64_t(e.commit),int64_t(e.video),e.source_serial,e.pts_us,
            int64_t(e.submit_ns),int64_t(time),refresh,int64_t(sequence),flags,e.playing?1:0});
        else capacity_skips++;
        if(e.proxy)wp_presentation_feedback_destroy(e.proxy);e.proxy=nullptr;
    }
    bool dispatch_until_clock(){
        const uint32_t end=SDL_GetTicks()+500;
        while(clock_id<0&&!SDL_TICKS_PASSED(SDL_GetTicks(),end)){
            if(wl_display_dispatch_pending(display)<0)return false;
            if(clock_id>=0)break;
            if(wl_display_prepare_read(display)!=0)continue;
            if(wl_display_flush(display)<0&&errno!=EAGAIN){wl_display_cancel_read(display);return false;}
            const uint32_t now=SDL_GetTicks();
            if(SDL_TICKS_PASSED(now,end)){wl_display_cancel_read(display);break;}
            pollfd fd{wl_display_get_fd(display),POLLIN,0};int result=poll(&fd,1,int(end-now));
            if(result>0&&(fd.revents&POLLIN)){if(wl_display_read_events(display)<0)return false;}
            else {wl_display_cancel_read(display);if(result<0&&errno==EINTR)continue;return false;}
        }
        return clock_id>=0&&!removed;
    }
    void close(){
        for(auto&e:pending)if(e.proxy)record(e,3,0,0,0,0);
        if(presentation){wp_presentation_destroy(presentation);presentation=nullptr;}
        if(registry){wl_registry_destroy(registry);registry=nullptr;}
    }
public:
    explicit WaylandPresentation(SDL_Window*window){
        const char*stage="wm-info";Uint32 began=SDL_GetTicks();
        try{
            rows.reserve(row_limit);for(auto&e:pending)e.owner=this;
            SDL_SysWMinfo info{};SDL_GetVersion(&info.version);
            if(!SDL_GetWindowWMInfo(window,&info)||info.subsystem!=SDL_SYSWM_WAYLAND)throw 60;
            stage="handles";
            display=info.info.wl.display;surface=info.info.wl.surface;
            if(!display||!surface)throw 60;
            stage="registry";
            registry=wl_display_get_registry(display);if(!registry)throw 60;
            stage="registry-listener";
            if(wl_registry_add_listener(registry,&registry_listener,this)<0)throw 60;
            stage="clock-event";if(!dispatch_until_clock())throw 60;
            stage="clock-id";
            timespec ts{};if(clock_id!=CLOCK_MONOTONIC||clock_gettime(clockid_t(clock_id),&ts))throw 60;
            if(diagnostic_allowed)save("presentation-startup.json",{{"passed",true},{"clock_id",clock_id},{"elapsed_ms",SDL_GetTicks()-began}});
        }catch(...){
            if(diagnostic_allowed)try{save("presentation-startup.json",{{"passed",false},{"stage",stage},{"clock_id",clock_id},{"presentation_bound",presentation!=nullptr},{"registry_bound",registry!=nullptr},{"elapsed_ms",SDL_GetTicks()-began},{"display_error",display?wl_display_get_error(display):0}});}catch(...){}
            close();throw;
        }
    }
    WaylandPresentation(const WaylandPresentation&)=delete;
    WaylandPresentation&operator=(const WaylandPresentation&)=delete;
    ~WaylandPresentation(){
        close();
        if(diagnostic_allowed)try{save("presentation-feedback.json",{{"schema",1},{"protocol_version",1},
            {"clock_id",clock_id},{"commits",commits},{"video_frames",video},{"capacity_skips",capacity_skips},
            {"invalid_timestamps",invalid_timestamps},{"clock_errors",clock_errors},{"global_removed",removed},
            {"pending_limit",pending_limit},{"row_limit",row_limit},{"physical_optical_measurement",false},
            {"rows",rows}});}catch(...){}
    }
    // Called before release of a consumed hardware frame, never inferred from
    // UI redraws or mpv metadata. Keep this identity on subsequent redraws.
    void video_frame(uint32_t source_serial,double source_pts){
        if(!std::isfinite(source_pts)||source_pts<0||source_pts>1e8){invalid_timestamps++;return;}
        video++;serial=source_serial;pts=int64_t(std::llround(source_pts*1e6));
    }
    void before_swap(bool hardware_playing){
        commits++;
        if(removed||!presentation||rows.size()+pending_limit>=row_limit){capacity_skips++;return;}
        Entry*entry=nullptr;for(auto&e:pending)if(!e.proxy){entry=&e;break;}
        if(!entry){capacity_skips++;return;}
        timespec ts{};if(clock_gettime(clockid_t(clock_id),&ts)){clock_errors++;return;}
        uint64_t now=uint64_t(ts.tv_sec)*1000000000+ts.tv_nsec;
        if(now<last_submit){clock_errors++;return;}last_submit=now;
        entry->commit=commits;entry->video=video;entry->source_serial=serial;entry->pts_us=pts;
        entry->submit_ns=now;entry->playing=hardware_playing;
        entry->proxy=wp_presentation_feedback(presentation,surface);
        if(!entry->proxy){capacity_skips++;return;}
        if(wp_presentation_feedback_add_listener(entry->proxy,&feedback_listener,entry)<0){
            wp_presentation_feedback_destroy(entry->proxy);entry->proxy=nullptr;capacity_skips++;
        }
    }
};
#else
class WaylandPresentation {
public:
    explicit WaylandPresentation(SDL_Window*){}
    void video_frame(uint32_t,double){}
    void before_swap(bool){}
};
#endif
