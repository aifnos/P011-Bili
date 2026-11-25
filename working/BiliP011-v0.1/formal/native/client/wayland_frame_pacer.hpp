// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// SDL 2.0.8 exposes the existing Wayland connection. Own only one wl_callback,
// never the display/surface, and never do an unbounded display roundtrip.
// API/protocol reference: Wayland 1.14 client-core.h and wl_surface.frame.
#ifdef P011_FRAME_PACING
#define SDL_VIDEO_DRIVER_WAYLAND 1
#include <SDL_syswm.h>
#include <poll.h>
struct wl_proxy;struct wl_interface;
class WaylandFramePacer {
    void*library=nullptr;wl_display*display=nullptr;wl_proxy*surface=nullptr,*callback=nullptr;
    wl_proxy*(*construct)(wl_proxy*,uint32_t,const wl_interface*,...)=nullptr;
    int(*listen)(wl_proxy*,void(**)(void),void*)=nullptr;
    void(*destroy)(wl_proxy*)=nullptr;
    int(*pending)(wl_display*)=nullptr;
    int(*prepare)(wl_display*)=nullptr;
    int(*flush)(wl_display*)=nullptr;
    int(*read_events)(wl_display*)=nullptr;
    int(*get_fd)(wl_display*)=nullptr;
    void(*cancel)(wl_display*)=nullptr;
    const wl_interface*interface=nullptr;
    unsigned requested=0,completed=0,timeouts=0,waited_ms=0;
    static void done(void*data,wl_proxy*object,uint32_t){auto*self=static_cast<WaylandFramePacer*>(data);self->destroy(object);self->callback=nullptr;self->completed++;}
    void(*listener[1])(void)={reinterpret_cast<void(*)(void)>(&done)};
    template<class T>void symbol(T&target,const char*name){target=reinterpret_cast<T>(SDL_LoadFunction(library,name));if(!target)throw 59;}
public:
    explicit WaylandFramePacer(SDL_Window*window){
        SDL_SysWMinfo info{};SDL_GetVersion(&info.version);
        if(!SDL_GetWindowWMInfo(window,&info)||info.subsystem!=SDL_SYSWM_WAYLAND)throw 59;
        display=info.info.wl.display;surface=reinterpret_cast<wl_proxy*>(info.info.wl.surface);
        library=SDL_LoadObject("/usr/lib/libwayland-client.so.0");if(!library||!display||!surface)throw 59;
        symbol(construct,"wl_proxy_marshal_constructor");symbol(listen,"wl_proxy_add_listener");symbol(destroy,"wl_proxy_destroy");
        symbol(pending,"wl_display_dispatch_pending");symbol(prepare,"wl_display_prepare_read");symbol(flush,"wl_display_flush");
        symbol(read_events,"wl_display_read_events");symbol(get_fd,"wl_display_get_fd");symbol(cancel,"wl_display_cancel_read");
        interface=reinterpret_cast<const wl_interface*>(SDL_LoadFunction(library,"wl_callback_interface"));if(!interface)throw 59;
    }
    ~WaylandFramePacer(){
        if(callback&&destroy)destroy(callback);
        if(library)SDL_UnloadObject(library);
        if(diagnostic_allowed)try{save("frame-pacing.json",{{"enabled",true},{"requested",requested},{"completed",completed},{"timeouts",timeouts},{"waited_ms",waited_ms},{"max_wait_ms",80}});}catch(...){}
    }
    bool before_frame(){
        auto began=SDL_GetTicks();auto until=began+80;
        while(callback&&!stopping){
            if(pending(display)<0)throw 59;
            if(!callback)break;
            if(SDL_TICKS_PASSED(SDL_GetTicks(),until)){timeouts++;break;}
            if(prepare(display)!=0)continue;
            int result=flush(display);if(result<0&&errno!=EAGAIN){cancel(display);throw 59;}
            auto now=SDL_GetTicks();if(SDL_TICKS_PASSED(now,until)){cancel(display);timeouts++;break;}
            pollfd fd{get_fd(display),POLLIN,0};result=poll(&fd,1,int(until-now));
            if(result>0&&(fd.revents&POLLIN)){if(read_events(display)<0)throw 59;}
            else{cancel(display);if(result<0&&errno!=EINTR)throw 59;if(result==0){timeouts++;break;}}
        }
        waited_ms+=SDL_GetTicks()-began;return !callback&&!stopping;
    }
    void before_swap(){
        if(callback)throw 59;
        callback=construct(surface,3,interface,nullptr);if(!callback)throw 59;
        if(listen(callback,listener,this)<0)throw 59;requested++;
    }
};
#else
class WaylandFramePacer {
public:explicit WaylandFramePacer(SDL_Window*){}bool before_frame(){return true;}void before_swap(){}
};
#endif
