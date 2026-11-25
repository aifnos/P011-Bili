// SPDX-License-Identifier: GPL-3.0-or-later
// Ten-second private window experiment. No media/network or vendor IPC.
// Keep RGBA8888; test whether the compositor accepts an 800x268 surface.
#include <SDL.h>
#define SDL_VIDEO_DRIVER_WAYLAND 1
#include <SDL_syswm.h>
#include <GLES2/gl2.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>
#include <iostream>
#include <nlohmann/json.hpp>
using J = nlohmann::json;
#include "../client/drm_trace.hpp"

// SDL 2.0.8 commits the initial xdg surface but does not wait for configure.
// A bounded sync barrier dispatches its existing listeners. It does NOT prove
// configure/ack readiness; the host separately audits the full protocol order.
// No new listener is installed on SDL's own surface.
struct wl_proxy;struct wl_interface;
static bool dispatch_sync(SDL_Window* window) {
    SDL_SysWMinfo info{};SDL_GetVersion(&info.version);
    if(!SDL_GetWindowWMInfo(window,&info)||info.subsystem!=SDL_SYSWM_WAYLAND)return false;
    void* lib=SDL_LoadObject("/usr/lib/libwayland-client.so.0");if(!lib)return false;
    auto construct=reinterpret_cast<wl_proxy*(*)(wl_proxy*,uint32_t,const wl_interface*,...)>(SDL_LoadFunction(lib,"wl_proxy_marshal_constructor"));
    auto marshal=reinterpret_cast<void(*)(wl_proxy*,uint32_t,...)>(SDL_LoadFunction(lib,"wl_proxy_marshal"));
    auto listen=reinterpret_cast<int(*)(wl_proxy*,void(**)(void),void*)>(SDL_LoadFunction(lib,"wl_proxy_add_listener"));
    auto destroy=reinterpret_cast<void(*)(wl_proxy*)>(SDL_LoadFunction(lib,"wl_proxy_destroy"));
    auto pending=reinterpret_cast<int(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_dispatch_pending"));
    auto prepare=reinterpret_cast<int(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_prepare_read"));
    auto flush=reinterpret_cast<int(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_flush"));
    auto read_events=reinterpret_cast<int(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_read_events"));
    auto get_fd=reinterpret_cast<int(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_get_fd"));
    auto cancel=reinterpret_cast<void(*)(wl_display*)>(SDL_LoadFunction(lib,"wl_display_cancel_read"));
    auto interface=reinterpret_cast<const wl_interface*>(SDL_LoadFunction(lib,"wl_callback_interface"));
    if(!construct||!marshal||!listen||!destroy||!pending||!prepare||!flush||!read_events||!get_fd||!cancel||!interface){SDL_UnloadObject(lib);return false;}
    auto display=info.info.wl.display;
    // Recommit role state without attaching any buffer. Safe even when the
    // vendor SDL already committed; requests apply only to this own surface.
    marshal(reinterpret_cast<wl_proxy*>(info.info.wl.surface),6);
    wl_proxy* callback=construct(reinterpret_cast<wl_proxy*>(display),0,interface,nullptr);
    if(!callback){SDL_UnloadObject(lib);return false;}
    bool done=false;
    auto complete=+[](void* data,wl_proxy*,uint32_t){*static_cast<bool*>(data)=true;};
    void(*listeners[1])(void)={reinterpret_cast<void(*)(void)>(complete)};
    bool ok=listen(callback,listeners,&done)==0;const Uint32 until=SDL_GetTicks()+500;
    while(ok&&!done&&!SDL_TICKS_PASSED(SDL_GetTicks(),until)) {
        if(pending(display)<0){ok=false;break;}if(done)break;
        if(prepare(display)!=0)continue;
        if(flush(display)<0&&errno!=EAGAIN){cancel(display);ok=false;break;}
        pollfd fd{get_fd(display),POLLIN,0};int n=poll(&fd,1,20);
        if(n>0&&(fd.revents&(POLLERR|POLLHUP|POLLNVAL))){cancel(display);ok=false;}
        else if(n>0&&(fd.revents&POLLIN)){if(read_events(display)<0)ok=false;}
        else {cancel(display);if(n<0&&errno!=EINTR)ok=false;}
    }
    if(ok&&done)ok=flush(display)>=0||errno==EAGAIN;
    destroy(callback);SDL_UnloadObject(lib);return ok&&done;
}

int main() {
    alarm(10);
    J result = {{"requested_width",800},{"requested_height",268},
                {"synthetic",true},{"media_played",false}};
    SDL_Window* window=nullptr;SDL_GLContext context=nullptr;
    bool initialized=false;int frames=0,w=0,h=0;GLenum fault=GL_NO_ERROR;
    try {
        if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_TIMER))throw 1;
        initialized=true;
#ifdef P011_PRIVATE_SDL_CONFIGURE
        void* sdl_library=SDL_LoadObject("libSDL2-2.0.so.0");if(!sdl_library)throw 9;
        auto guard=reinterpret_cast<int(*)()>(SDL_LoadFunction(sdl_library,"P011_WaylandConfigureTimeoutMs"));
        int guard_ms=guard?guard():0;SDL_UnloadObject(sdl_library);
        result["private_sdl_configure_timeout_ms"]=guard_ms;if(guard_ms!=500)throw 9;
#endif
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_ES);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,2);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,0);
        SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);
        for(auto a:{SDL_GL_RED_SIZE,SDL_GL_GREEN_SIZE,SDL_GL_BLUE_SIZE,SDL_GL_ALPHA_SIZE})
            if(SDL_GL_SetAttribute(a,8))throw 2;
        const Uint32 window_start=SDL_GetTicks();
        window=SDL_CreateWindow("P011 bounded strip probe",SDL_WINDOWPOS_UNDEFINED,
            SDL_WINDOWPOS_UNDEFINED,800,268,SDL_WINDOW_OPENGL|SDL_WINDOW_SHOWN|SDL_WINDOW_BORDERLESS);
        result["window_create_ms"]=Uint32(SDL_GetTicks()-window_start);
        if(!window)throw 3;
#ifndef P011_PRIVATE_SDL_CONFIGURE
        result["empty_commit_sync"]=dispatch_sync(window);if(!result["empty_commit_sync"].get<bool>())throw 8;
        // Diagnostic-only discriminator: sync can precede compositor idle
        // configure emission. This is not a production readiness heuristic.
        const Uint32 settle=SDL_GetTicks()+250;
        while(!SDL_TICKS_PASSED(SDL_GetTicks(),settle)){SDL_PumpEvents();SDL_Delay(5);}
        result["diagnostic_settle_ms"]=250;
#else
        result["diagnostic_settle_ms"]=0;
#endif
        context=SDL_GL_CreateContext(window);if(!context)throw 4;
        SDL_GL_SetSwapInterval(1);
        GLint bits[4]={};glGetIntegerv(GL_RED_BITS,bits);glGetIntegerv(GL_GREEN_BITS,bits+1);
        glGetIntegerv(GL_BLUE_BITS,bits+2);glGetIntegerv(GL_ALPHA_BITS,bits+3);
        result["rgba_bits"]={bits[0],bits[1],bits[2],bits[3]};
        const Uint32 until=SDL_GetTicks()+3500;
        bool quit=false;
        while(!quit&&!SDL_TICKS_PASSED(SDL_GetTicks(),until)) {
            SDL_Event event;while(SDL_PollEvent(&event))if(event.type==SDL_QUIT)quit=true;
            SDL_GL_GetDrawableSize(window,&w,&h);if(w!=800||h!=268)throw 5;
            glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);
            glClearColor(.04f,.04f,.04f,1);glClear(GL_COLOR_BUFFER_BIT);
            glEnable(GL_SCISSOR_TEST);glScissor(40,30,720,208);
            glClearColor(.08f,.55f,.38f,1);glClear(GL_COLOR_BUFFER_BIT);glDisable(GL_SCISSOR_TEST);
            fault=glGetError();if(fault!=GL_NO_ERROR)throw 6;
            SDL_GL_SwapWindow(window);fault=glGetError();if(fault!=GL_NO_ERROR)throw 7;
            frames++;SDL_Delay(12);
        }
        result["passed"]=frames>=60&&bits[0]==8&&bits[1]==8&&bits[2]==8&&bits[3]==8;
    } catch(int code) {result["error_stage"]=code;result["passed"]=false;}
    result["frames"]=frames;result["drawable"]={w,h};result["gl_error"]=fault;
    if(context)SDL_GL_DeleteContext(context);
    if(window)SDL_DestroyWindow(window);
    if(initialized)SDL_Quit();
    result["drm"]=p011_drm_trace::snapshot();
    std::cout<<"PROBE="<<result.dump()<<std::endl;
    return result.value("passed",false)?0:1;
}
