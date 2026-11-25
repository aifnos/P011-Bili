// SPDX-License-Identifier: GPL-3.0-or-later
// Enhanced player reuses audited guards/font/GL helpers. Protocol 2 is private
// stdin/stdout IPC; it never opens an input server or changes system rotation.
#define P011_ENHANCED_BUILD 1
#define main p011_legacy_entry
#include "player.cpp"
#undef main
#include "player_controls.hpp"
#include "player_gestures.hpp"
#include "stream_transaction.hpp"
#include "danmaku_timeline.hpp"
#include "frame_telemetry.hpp"
#include "player_phase.hpp"
#include "player_packets.hpp"
#include "player_preview_image.hpp"
#include "player_features.hpp"
#include "hardware_client.hpp"
#include "hardware_picture.hpp"
#include "drm_trace.hpp"
#include "wayland_frame_pacer.hpp"
#include "wayland_presentation.hpp"
#include <cerrno>
#include <atomic>
#include <ctime>
#include <vector>
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBI_WRITE_NO_STDIO
#include "stb_image_write.h"
using p011_player::Layout;
using p011_player::Point;
using p011_player::Rect;
using p011_player::Button;

struct PlayerResources {
    bool sdl=false;SDL_Window*window=nullptr;SDL_GLContext gl=nullptr;mpv_handle*mpv=nullptr;mpv_render_context*render=nullptr;
    std::atomic<bool>video_update{true};
    HardwareBackend hardware;
    // Error paths must release GL/Wayland objects as deliberately as the
    // normal path. Merely exiting after a driver allocation error leaves the
    // old compositor/ION stack to recover everything from a disconnect.
    ~PlayerResources(){
        hardware.close();
        if(diagnostic_allowed)try{save("hardware-lifecycle.json",hardware.audit());}catch(...){}
        if(diagnostic_allowed)try{save("hardware-seek.json",hardware.seek_detail);}catch(...){}
        if(window&&gl)SDL_GL_MakeCurrent(window,gl);
        if(render){mpv_render_context_set_update_callback(render,nullptr,nullptr);mpv_render_context_free(render);}
        if(mpv)mpv_terminate_destroy(mpv);
        if(gl)SDL_GL_DeleteContext(gl);
        if(window)SDL_DestroyWindow(window);
        if(sdl)SDL_Quit();
#ifdef P011_DRM_TRACE
        if(diagnostic_allowed)try{save("drm-allocation.json",p011_drm_trace::snapshot());}catch(...){}
#endif
    }
};

static int load_stream(mpv_handle*m,const std::string&video,const std::string&audio,double start,int width=0,int height=0){
    if(!media(video)||!media(audio,true))return MPV_ERROR_INVALID_PARAMETER;
    if(width<0||height<0||width>16384||height>16384)return MPV_ERROR_INVALID_PARAMETER;
    // Source quality and frame rate remain unchanged. Only very large decoded
    // frames are reduced before GLES texture upload. Keep ordinary 1080P on
    // the measured unfiltered path; clear the filter on each smaller stream.
    std::string filter=std::max(width,height)>1920?"lavfi=[scale=w='min(960,iw)':h='min(960,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2:flags=fast_bilinear]":"";
    std::vector<std::string>keys={"audio-files","start","vf"},values={"",std::to_string(std::max(0.,start)),filter};
    if(!audio.empty()){keys.push_back("audio-files-append");values.push_back(audio);}
    std::vector<char*>names;std::vector<mpv_node>nodes;
    for(size_t i=0;i<keys.size();i++){names.push_back(&keys[i][0]);mpv_node n={};n.format=MPV_FORMAT_STRING;n.u.string=&values[i][0];nodes.push_back(n);}
    mpv_node_list opts={int(nodes.size()),nodes.data(),names.data()};mpv_node args[4]={};
    const std::string op="loadfile",replace="replace";
    for(int i=0;i<3;i++){args[i].format=MPV_FORMAT_STRING;args[i].u.string=const_cast<char*>((i==0?op:i==1?video:replace).c_str());}
    args[3].format=MPV_FORMAT_NODE_MAP;args[3].u.list=&opts;
    mpv_node_list list={4,args,nullptr};mpv_node command={};command.format=MPV_FORMAT_NODE_ARRAY;command.u.list=&list;
    return mpv_command_node_async(m,1,&command);
}
static std::vector<int> quality_ids(const J&data){
    std::vector<int>result;auto rows=data.value("qualities",J::array());
    if(rows.is_array()&&rows.size()<=64)for(auto&r:rows)if(r.is_object()&&r.contains("id")&&r["id"].is_number_integer()){
        int n=r["id"].get<int>();if(n>=0&&n<=65535&&std::find(result.begin(),result.end(),n)==result.end())result.push_back(n);
    }
    if(result.empty())result.push_back(0);return result;
}
static std::map<int,std::string> quality_labels(const J&data){std::map<int,std::string>out;auto rows=data.value("qualities",J::array());if(rows.is_array()&&rows.size()<=64)for(const auto&r:rows)if(r.is_object()&&r.contains("id")&&r["id"].is_number_integer()&&r.contains("label")&&r["label"].is_string()){auto s=r["label"].get<std::string>();if(s.size()<=192&&s.find_first_of("\r\n\t")==s.npos)out[r["id"].get<int>()]=s;}return out;}
static std::vector<int> codec_ids(const J&data){std::vector<int>v;auto rows=data.value("codecs",J::array());if(rows.is_array()&&rows.size()<=4)for(auto&r:rows)if(r.is_object()&&r.contains("id")&&r["id"].is_number_integer()){int c=r["id"].get<int>();if(c==0||c==7||c==12||c==13)v.push_back(c);}if(v.empty())v={0,7};return v;}
static void emit_request(const J&data){std::cout<<data.dump()<<'\n'<<std::flush;}
static J gl_faults=J::object();
static void inspect_gl(const char*where){
    for(int i=0;i<8;i++){GLenum code=glGetError();if(code==GL_NO_ERROR)break;std::string key=std::string(where)+"_"+std::to_string(code);gl_faults[key]=gl_faults.value(key,0)+1;}
    if(!gl_faults.empty()){save("capture-state.json",{{"stage_errors",gl_faults}});throw 32;}
}
#ifdef P011_DISPLAY_FIRST
#if !defined(P011_DRM_TRACE) || !defined(P011_STRIP_WINDOW)
#error Display-first experiment requires the private strip window and allocation evidence
#endif
static bool prepare_display_buffers(SDL_Window*window){
    // Diagnostic-only ordering experiment for this pinned vendor driver.
    // It has requested three 800x268 window buffers in the recorded runs.
    // Observe three successful allocations BEFORE starting mpv/GStreamer;
    // never treat a sleep, number of draws, or GL context as readiness proof.
    // This changes no ioctl arguments and does not allocate a separate FBO.
    const Uint32 began=SDL_GetTicks();unsigned frames=0,matched=0;bool quit=false;
    J report={{"diagnostic_only",true},{"media_started",false},{"passed",false},
              {"required_allocations",3},{"max_elapsed_ms",750},{"max_frames",48}};
    auto evidence=[&](){
        auto trace=p011_drm_trace::snapshot();matched=0;
        for(const auto&r:trace["last_requests"])
            if(r.value("width",0)==800&&r.value("height",0)==268&&r.value("bpp",0)==32&&
               r.value("result",-1)==0&&r.value("errno",-1)==0)matched++;
        report["drm"]=trace;report["successful_strip_allocations"]=matched;
        report["frames"]=frames;report["elapsed_ms"]=Uint32(SDL_GetTicks()-began);
        save("display-prepare.json",report);
    };
    try{
        while(!stopping&&!quit&&frames<48&&Uint32(SDL_GetTicks()-began)<750){
            SDL_Event event;while(SDL_PollEvent(&event))if(event.type==SDL_QUIT)quit=true;
            if(quit)break;
            int w=0,h=0;SDL_GL_GetDrawableSize(window,&w,&h);if(w!=800||h!=268)throw 37;
            glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);
            glClearColor(.025f,.03f,.035f,1);glClear(GL_COLOR_BUFFER_BIT);inspect_gl("prepare_clear");
            SDL_GL_SwapWindow(window);inspect_gl("prepare_swap");frames++;
            evidence();if(matched>=3){report["passed"]=true;break;}
        }
    }catch(...){evidence();throw;}
    evidence();return report.value("passed",false);
}
#endif
static void check_hardware_shapes(HardwarePicture&picture){
    // Automated-only synthetic GPU regression. Never counted as decoded or
    // displayed video, never saved as a video screenshot or run manually.
    auto f=std::make_unique<p011_hw::Frame>();J shapes=J::array();Layout l;
    for(auto size:{std::make_pair(640,294),std::make_pair(854,480),std::make_pair(480,854),std::make_pair(960,540)}){
        f->width=size.first;f->height=size.second;f->bytes=f->width*f->height*3/2;f->format=1;f->matrix=1;f->full_range=0;
        memset(f->pixels,128,f->bytes);
        save("hardware-graphics.json",{{"passed",false},{"synthetic",true},{"current_width",f->width},{"current_height",f->height},{"completed_shapes",shapes}});
        auto surface=p011_player::active_surface();picture.upload(*f);inspect_gl("shape_upload");picture.draw(l,p011_player::video_box(l,false),0,int(surface.width()),int(surface.height()));glFinish();inspect_gl("shape_draw");
        shapes.push_back({f->width,f->height});
    }
    picture.clear();glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT);
    save("hardware-graphics.json",{{"passed",true},{"synthetic",true},{"video_frames_counted",false},{"completed_shapes",shapes}});
}
static void configure_view(mpv_handle*m,const Layout&layout,bool story=false,const p011_player::Settings&s={}){
    Rect box=p011_player::video_box(layout,story);auto a=layout.physical({box.x,box.y}),b=layout.physical({box.x+box.w,box.y+box.h});
    auto surface=p011_player::active_surface();a=surface.local(a);b=surface.local(b);
    std::pair<const char*,double>margins[]={
        {"video-margin-ratio-left",std::min(a.x,b.x)/800.},
        {"video-margin-ratio-right",(800-std::max(a.x,b.x))/800.},
        {"video-margin-ratio-top",std::min(a.y,b.y)/surface.height()},
        {"video-margin-ratio-bottom",(surface.height()-std::max(a.y,b.y))/surface.height()}};
    for(auto&entry:margins)if(mpv_set_property_string(m,entry.first,std::to_string(entry.second).c_str())<0)throw 33;
    if(mpv_set_property_string(m,"video-rotate",layout.portrait()?"90":"0")<0)throw 33;
    for(auto entry:{std::make_pair("keepaspect",s.aspect==2?"no":"yes"),std::make_pair("panscan",s.aspect==1?"1":"0"),std::make_pair("video-aspect-override",s.aspect==3?"16:9":s.aspect==4?"4:3":"-1")})
        if(mpv_set_property_string(m,entry.first,entry.second)<0)throw 33;
}
static void save_capture(const std::string&name,int w,int h){
    static const std::vector<std::string>names={"player-landscape","player-paused","player-quality","player-danmaku","player-portrait","player-portrait-controls","player-next","player-codecs","player-hevc","player-av1","player-types","player-types-later","player-dm-settings","player-story","player-story-next","player-dm-layout","player-dm-half","player-aspect","player-fill","player-stats","player-story-drag","player-seek-preview","player-comments","player-listen","player-live","player-subtitles","player-chapters","player-subtitle-settings","player-timed-preview"};
    auto surface=p011_player::active_surface();
    if(std::find(names.begin(),names.end(),name)==names.end()||w!=int(surface.width())||h!=int(surface.height()))throw 29;
    inspect_gl("before_capture");
    std::vector<unsigned char>raw(size_t(w)*h*4),flipped(raw.size());glFinish();glPixelStorei(GL_PACK_ALIGNMENT,1);glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,raw.data());
    GLenum error=glGetError();unsigned lo=255,hi=0;size_t colored=0;
    for(size_t i=0;i<raw.size();i+=4){for(int k=0;k<3;k++){lo=std::min(lo,unsigned(raw[i+k]));hi=std::max(hi,unsigned(raw[i+k]));}if(raw[i]>12||raw[i+1]>12||raw[i+2]>12)colored++;}
    GLint bits[4]={};glGetIntegerv(GL_RED_BITS,bits);glGetIntegerv(GL_GREEN_BITS,bits+1);glGetIntegerv(GL_BLUE_BITS,bits+2);glGetIntegerv(GL_ALPHA_BITS,bits+3);
    save("capture-state.json",{{"gl_error",error},{"minimum",lo},{"maximum",hi},{"colored_pixels",colored},{"framebuffer",glCheckFramebufferStatus(GL_FRAMEBUFFER)},{"rgba_bits",{bits[0],bits[1],bits[2],bits[3]}},{"stage_errors",gl_faults}});
    for(int y=0;y<h;y++)memcpy(flipped.data()+size_t(y)*w*4,raw.data()+size_t(h-1-y)*w*4,size_t(w)*4);
    int fd=open((root+"/screenshots/"+name+".png").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(fd<0)throw 29;
    struct Writer{int fd;bool ok;};Writer writer={fd,true};
    auto output=[](void*ctx,void*data,int n){Writer*state=static_cast<Writer*>(ctx);char*p=static_cast<char*>(data);while(n>0){ssize_t used=write(state->fd,p,n);if(used<=0){state->ok=false;return;}n-=int(used);p+=used;}};
    int ok=stbi_write_png_to_func(output,&writer,w,h,4,flipped.data(),w*4);close(fd);if(!ok||!writer.ok)throw 29;
    if(error!=GL_NO_ERROR||hi-lo<24||colored<2000)throw 32;
}
static int v2_run(){
    const char*p=getenv("P011_CLIENT_ROOT"),*id=getenv("P011_AWAKE_SESSION"),*limit=getenv("P011_PLAYER_LIMIT");
    if(!p||!id||!limit)return 19;root=p;session=id;
    if(!std::regex_match(session,std::regex("[a-f0-9]{24}"))||root!="/mnt/data/p011-toolbox/bili-awake/"+session)return 19;
    int seconds=atoi(limit);if(seconds<10||seconds>86400)return 19;diagnostic_allowed=true;Releaser release;lease(false);alarm(seconds+8);
    phase="input";std::string initial;char c;
    // Read exactly one newline packet, avoiding iostream read-ahead before
    // switching this same anonymous pipe to nonblocking control messages.
    while(read(STDIN_FILENO,&c,1)==1&&c!='\n'){if(initial.size()>32768)return 2;initial+=c;}
    J request=J::parse(initial);if(request.value("protocol",0)!=2)return 2;
    std::string video=request.value("video",""),audio=request.value("audio","");if(!media(video)||!media(audio,true))return 3;
    bool muted=request.value("muted",false),dm_on=request.value("danmaku",true),preview=request.value("preview",false);
    bool story=request.value("story",false);int story_page=story?2:0;std::string title=request.value("title",""),up=request.value("up","");
    bool live=request.value("live",false),listening=request.value("listen",false);
    audio_lease_release=listening;
    p011_player::Features features;features.enabled=request.value("features",false);
    bool dm_filters[6]={true,true,true,true,true,true};
    bool dm_fixture=false;
    bool automated=muted&&getenv("P011_PLAYER_AUTOMATED")&&std::string(getenv("P011_PLAYER_AUTOMATED"))=="1";
    Layout layout;if(request.value("portrait",false))layout.orientation=p011_player::Orientation::PortraitClockwise;
    auto settings=p011_player::Settings::from(request.value("settings",J::object()));
    int actual_quality=request.value("quality",0),queue_at=request.value("queue_index",0),queue_count=request.value("queue_count",1),serial=1,generation=request.value("generation",0);
    int actual_codec=request.value("codec",7),codec_switches=0,menu_page=0;std::string decoder;
    std::vector<int>codecs=codec_ids(request);
    std::vector<int>qualities=quality_ids(request);std::vector<p011_dm::Item>danmaku,live_pending;
    unsigned live_dm_received=0;bool live_dm_authenticated=false;
    auto labels=quality_labels(request);
    p011_dm::Timeline dm_timeline;p011_dm::Builder dm_builder;bool dm_dirty=true;
    PlayerResources resources;
#ifdef P011_STRIP_WINDOW
    SDL_SetHint("P011_WAYLAND_CENTERED_WL_SHELL","1");
#endif
    phase="sdl";if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_TIMER))return 4;resources.sdl=true;
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_ES);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,2);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,0);SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);
    // SDL's low default RGB requirements select RGBA4444 on this vendor EGL.
    // Explicit 8-bit channels avoid 16-level posterization of both video/UI.
    for(auto attribute:{SDL_GL_RED_SIZE,SDL_GL_GREEN_SIZE,SDL_GL_BLUE_SIZE,SDL_GL_ALPHA_SIZE})if(SDL_GL_SetAttribute(attribute,8)<0)return 34;
    const auto surface=p011_player::active_surface();
    unsigned window_flags=SDL_WINDOW_OPENGL|SDL_WINDOW_SHOWN|SDL_WINDOW_BORDERLESS;
#ifdef P011_STRIP_WINDOW
    // Refuse a system-SDL fallback: only the isolated, bounded configure
    // implementation is authorized to create this content-only surface.
    phase="private_sdl";void*sdl_library=SDL_LoadObject("libSDL2-2.0.so.0");if(!sdl_library)return 36;
    auto configure_bound=reinterpret_cast<int(*)()>(SDL_LoadFunction(sdl_library,"P011_WaylandConfigureTimeoutMs"));
    int configure_timeout_ms=configure_bound?configure_bound():0;SDL_UnloadObject(sdl_library);if(configure_timeout_ms!=500)return 36;
#else
    window_flags|=SDL_WINDOW_FULLSCREEN_DESKTOP|SDL_WINDOW_RESIZABLE;
#endif
    phase="window";SDL_Window*window=SDL_CreateWindow("P011 Bili",SDL_WINDOWPOS_UNDEFINED,SDL_WINDOWPOS_UNDEFINED,int(surface.width()),int(surface.height()),window_flags);resources.window=window;if(!window)return 5;
#ifdef P011_STRIP_WINDOW
    // Protocol-level centering preserves the small buffer. SDL window x/y
    // are not compositor placement on Wayland. Confirm a fresh fullscreen
    // configure before drawing; whole-screen DRM captures test reality.
    phase="window_placement";sdl_library=SDL_LoadObject("libSDL2-2.0.so.0");if(!sdl_library)return 39;
    auto center_content=reinterpret_cast<int(*)(SDL_Window*)>(SDL_LoadFunction(sdl_library,"P011_WaylandCenterContentWindow"));
    int center_result=center_content?center_content(window):-1;SDL_UnloadObject(sdl_library);
    save("window-placement.json",{{"protocol","wl-shell-fill-centered"},{"configure_confirmed",center_result==0},{"buffer_width",800},{"buffer_height",268},{"output_width",800},{"output_height",480},{"actual_scanout_checked",false}});
    if(center_result!=0)return 39;
#endif
    phase="gl";SDL_GLContext gl=SDL_GL_CreateContext(window);resources.gl=gl;if(!gl)return 6;SDL_GL_SetSwapInterval(1);
    GLint channel_bits[4]={};glGetIntegerv(GL_RED_BITS,channel_bits);glGetIntegerv(GL_GREEN_BITS,channel_bits+1);glGetIntegerv(GL_BLUE_BITS,channel_bits+2);glGetIntegerv(GL_ALPHA_BITS,channel_bits+3);
    GLint max_texture=0,max_renderbuffer=0;glGetIntegerv(GL_MAX_TEXTURE_SIZE,&max_texture);glGetIntegerv(GL_MAX_RENDERBUFFER_SIZE,&max_renderbuffer);
    save("render-info.json",{{"rgba_bits",{channel_bits[0],channel_bits[1],channel_bits[2],channel_bits[3]}},{"max_texture_size",max_texture},{"max_renderbuffer_size",max_renderbuffer}});
    save("surface-info.json",{{"content_only",surface.content_only},{"buffer_width",surface.width()},{"buffer_height",surface.height()},{"panel_origin_y",surface.top()},{"configure_bound_ms",surface.content_only?500:0}});
    if(channel_bits[0]<8||channel_bits[1]<8||channel_bits[2]<8||channel_bits[3]<8)return 34;
#ifdef P011_DISPLAY_FIRST
    phase="display_buffers";if(!prepare_display_buffers(window))return 38;
#endif
    phase="mpv_create";mpv_handle*m=mpv_create();resources.mpv=m;if(!m)return 7;phase="mpv_options";configure(m);if(muted)option(m,"mute","yes");if(story)option(m,"loop-file","inf");
    phase="mpv_initialize";last_mpv_error=mpv_initialize(m);if(last_mpv_error<0)return 8;
    // Property-change events avoid synchronous core round trips on the GL
    // thread, particularly costly while paused or during codec reconfigure.
    const char*observed_names[]={"pause","core-idle","time-pos","duration","width","height","container-fps","avsync","frame-drop-count","decoder-frame-drop-count","video-format","current-ao","video-out-params/w","video-out-params/h"};
    mpv_format observed_types[]={MPV_FORMAT_FLAG,MPV_FORMAT_FLAG,MPV_FORMAT_DOUBLE,MPV_FORMAT_DOUBLE,MPV_FORMAT_INT64,MPV_FORMAT_INT64,MPV_FORMAT_DOUBLE,MPV_FORMAT_DOUBLE,MPV_FORMAT_INT64,MPV_FORMAT_INT64,MPV_FORMAT_STRING,MPV_FORMAT_STRING,MPV_FORMAT_INT64,MPV_FORMAT_INT64};
    for(int i=0;i<14;i++)if(mpv_observe_property(m,i+1,observed_names[i],observed_types[i])<0)return 35;
    mpv_opengl_init_params init={get_proc,nullptr};mpv_render_param params[]={{MPV_RENDER_PARAM_API_TYPE,(void*)MPV_RENDER_API_TYPE_OPENGL},{MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,&init},{MPV_RENDER_PARAM_INVALID,nullptr}};
    phase="mpv_render";mpv_render_context*render=nullptr;last_mpv_error=mpv_render_context_create(&render,m,params);resources.render=render;if(last_mpv_error<0)return 9;
    auto&video_update=resources.video_update;mpv_render_context_set_update_callback(render,[](void*ctx){static_cast<std::atomic<bool>*>(ctx)->store(true);},&video_update);
    auto&hw=resources.hardware;
    bool reset_hardware_picture=true,hardware_shapes_tested=false,compat_notified=false;
    double playback_rate=1.;
    auto load_selected=[&](const J&packet,double at,bool paused)->int{
        const std::string v=packet.value("video",""),a=packet.value("audio","");int w=packet.value("width",0),h=packet.value("height",0),codec=packet.value("codec",7);
        if(!media(v)||!media(a,true))return MPV_ERROR_INVALID_PARAMETER;
        hw.close();reset_hardware_picture=true;compat_notified=false;
        bool audio_only=packet.value("listen",false);
        mpv_set_property_string(m,"vid",audio_only?"no":"auto");
        if(!audio_only&&!packet.value("live",false)&&p011_hw::supported(codec,w,h,!a.empty())){
            const char*stop[]={"stop",nullptr};mpv_command(m,stop);
            J init={{"video",v},{"audio",a},{"width",w},{"height",h},{"muted",muted},{"paused",paused},{"start",at},{"volume",100},{"loop",false},{"limit",seconds},{"high_fps_compat",true},{"rate",playback_rate}};
            return hw.open(init)?0:MPV_ERROR_LOADING_FAILED;
        }
        mpv_set_property(m,"speed",MPV_FORMAT_DOUBLE,&playback_rate);
        return load_stream(m,audio_only&&!a.empty()?a:v,audio_only?"":a,at,audio_only?0:w,audio_only?0:h);
    };
    double initial_position=request.value("start",0.);
    if(!std::isfinite(initial_position)||initial_position<0||initial_position>86400)initial_position=0;
    if(load_selected(request,initial_position,false)<0)return 10;
    fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
    p011_ipc::Decoder packet_decoder(decode_preview_image);
    Uint32 start=SDL_GetTicks(),lastwrite=0,lastadvance=0,down_at=0,pending_at=0,toast_until=0;unsigned request_seq=0,pending_seq=0;
    double pos=0,duration=0,previous=-1,maxpos=0,volume=100;int pause=0,idle=1,width=0,height=0,menu=0;
    int draws=0,pauses=0,seeks=0,scrub_actions=0,rotations=0,swipes=0,switches=0,quality_switches=0,dm_toggles=0,dm_frames=0,overlay_taps=0,hidden=0,shown=0,captures=0;
    bool scrubbing=false;double scrub_ratio=0;
    p011_player::VideoGesture gesture;p011_player::FeedSlide slide;
    p011_player::HoldRate hold_rate;int hold_rate_actions=0,hold_rate_restores=0;
    p011_player::StreamTransaction transition(request);
    p011_player::FrameReload replay,seek_reload;
    auto previous_orientation=layout.orientation;
    bool previous_dm_on=dm_on;
    int switch_failures=0,switch_recoveries=0;unsigned switch_latency_ms=0,switch_total_ms=0;
    bool gesture_owned=false;int video_seek_actions=0,slide_frames=0,slide_cancels=0;
    double last_soft_pan=0;
    Point pointer_latest{0,0};
    SDL_FingerID active_finger=0;bool finger_down=false;
    int64_t drops=-1,decoder_drops=0;bool loaded=false,finished=false,failure=false,pulse=false,replacing=false,down=false,down_owned=false,dm_loaded=false,dm_failed=false;
    bool redraw=true;Uint32 lastdraw=0;int skipped_draws=0,settings_changes=0,source_width=0,source_height=0,observed_codec=0;double source_fps=0,avsync=0,cpu_pct=0;
    double cpu_last=double(std::clock())/CLOCKS_PER_SEC;Uint32 cpu_at=start;unsigned long long render_us=0;
    p011_player::FrameTelemetry frames;frames.sampled_at=start;
    p011_profile::Phases phase_times;
    const uint64_t profile_frequency=SDL_GetPerformanceFrequency();
    auto profile_record=[&](p011_profile::Id id,uint64_t began,bool playing,double position){
        const uint64_t elapsed=(SDL_GetPerformanceCounter()-began)*1000000/profile_frequency;
        phase_times.rows[id].record(elapsed,uint64_t(std::max(0.,std::min(86400.,position))*1000),playing);
    };
    auto profile_fields=[&](J&out){
        static const char*names[]={"input","status","layout","pacer","upload","overlay","swap"};
        for(unsigned i=0;i<p011_profile::Count;i++){
            const auto&s=phase_times.rows[i];const std::string key=std::string("phase_")+names[i]+"_";
            out[key+"count"]=s.count;out[key+"total_us"]=s.total_us;out[key+"max_us"]=s.max_us;
            out[key+"over_33ms"]=s.over_33ms;out[key+"over_100ms"]=s.over_100ms;out[key+"last_slow_position_ms"]=s.last_slow_position_ms;
        }
    };
    p011_player::PlaybackHealth health;
    int upload_width=0,upload_height=0;
    std::string reason="limit",input_buffer,capture_name,toast;Point down_point={0,0};Button pressed; p011_player::ProgressOverlay overlay;
    auto save_watch=[&](){save("watch-state.json",{{"generation",generation},{"serial",serial},{"loaded",loaded},{"position",pos},{"duration",duration},{"switch_pending",pending_seq!=0||replacing},
        {"paused",pause!=0},{"idle",idle!=0},{"rate",playback_rate},{"finished",finished||bool(stopping)}, {"completed",finished&&!failure&&!stopping&&reason=="eof"}});};
    {
        phase="painter";Painter painter;HardwarePicture hardware_picture;WaylandFramePacer pacer(window);WaylandPresentation presentation(window);painter.set_layout(&layout);configure_view(m,layout,story,settings);phase="playback";
        struct PreviewTexture {GLuint id=0;~PreviewTexture(){if(id)glDeleteTextures(1,&id);}} preview_texture;
        int preview_serial=0,preview_images=0;double preview_start=-1,preview_end=0;Uint32 preview_attempt=0;
        auto label=[&](int q){auto it=labels.find(q);return it==labels.end()?p011_player::quality_label(q):it->second;};
        auto compatible=[&](){return hw.active&&hw.status.value("high_fps_compat",false)&&hw.status.value("encoded_nonref_skipped",0u)>0;};
        auto backend_label=[&](){return listening?std::string("仅音频"):hw.active?std::string(compatible()?"AVC硬解 · 降帧兼容":"AVC · OMX硬解"):p011_player::codec_label(actual_codec)+(live?" · 直播软解":" · 软解");};
        auto buttons=[&](bool visible){
            auto all=p011_player::buttons(layout,visible,pause,dm_on,menu,qualities,menu_page,codecs,story,settings);
            if(!features.page.empty()){
                all.erase(std::remove_if(all.begin(),all.end(),[&](const Button&b){return b.action!="back"&&b.action!="pause"&&b.action!="volume-"&&b.action!="volume+";}),all.end());
                auto extra=features.buttons(layout);all.insert(all.end(),extra.begin(),extra.end());
            }
            if(live)all.erase(std::remove_if(all.begin(),all.end(),[](const Button&b){return b.action=="seek-"||b.action=="seek+"||b.action=="previous"||b.action=="next"||b.action=="feature-comments"||b.action=="feature-account"||b.action=="feature-subtitles"||b.action=="feature-chapters"||b.action=="rate-menu"||b.action=="codec-menu";}),all.end());
            for(auto&b:all){if(b.action=="listen")b.label=listening?"返回视频":"听视频";if(b.action=="quality")b.label=label(b.value);if(b.action=="codec")b.label=b.value==0?"自动 · AVC优先":b.value==7?"AVC · 硬解优先":p011_player::codec_label(b.value)+" · 软解";}return all;
        };
        auto notice=[&](const std::string&text){toast=text;toast_until=SDL_GetTicks()+3500;overlay.reveal(SDL_GetTicks());};
        emit_request({{"action","capabilities"},{"switch_ack",true}});
        auto reject_switch=[&](){
            emit_request({{"action","stream_result"},{"seq",transition.seq},{"ok",false}});
            transition.seq=0;failure=true;finished=true;reason="switch-recovery-failed";
        };
        auto recover_switch=[&](){
            if(!transition.recover(SDL_GetTicks()))return false;
            switch_failures++;story=transition.current.value("story",false);listening=transition.current.value("listen",false);audio_lease_release=listening;layout.orientation=previous_orientation;dm_on=previous_dm_on;
            configure_view(m,layout,story,settings);mpv_set_property_string(m,"loop-file",story?"inf":"no");
            slide.cancel(SDL_GetTicks());loaded=false;replacing=true;pause=transition.paused;
            last_mpv_error=load_selected(transition.current,transition.position,transition.paused);
            if(last_mpv_error<0)reject_switch();else {if(hw.active)hw.command({{"op","volume"},{"value",volume}});notice("切换未成功，正在恢复原视频…");}
            return true;
        };
        auto complete_switch=[&](){
            if(!transition.seq)return;
            bool restored=transition.restoring;unsigned seq=transition.seq;
            if(!restored){
                const auto&packet=transition.next;bool keep=packet.value("keep_position",false);
                actual_quality=packet.value("quality",0);qualities=quality_ids(packet);labels=quality_labels(packet);preview=packet.value("preview",false);
                int new_codec=packet.value("codec",7);if(keep&&new_codec!=actual_codec)codec_switches++;actual_codec=new_codec;codecs=codec_ids(packet);
                queue_at=packet.value("queue_index",queue_at);queue_count=packet.value("queue_count",queue_count);serial=packet.value("serial",serial);
                story_page=packet.value("story_page",story_page);
                if(keep)quality_switches++;else {switches++;danmaku.clear();dm_dirty=true;dm_fixture=false;dm_loaded=false;dm_failed=false;title=packet.value("title","");up=packet.value("up","");}
                listening=packet.value("listen",false);audio_lease_release=listening;if(!keep)features.reset(serial);else features.close();
                switch_latency_ms=SDL_GetTicks()-transition.started;
                switch_total_ms=SDL_GetTicks()-pending_at;
            }else switch_recoveries++;
            transition.ready();replacing=false;loaded=true;health={};redraw=true;
            emit_request({{"action","stream_result"},{"seq",seq},{"ok",!restored}});
            if(restored)notice("已恢复原视频，可重新选择");else {slide.ready(SDL_GetTicks());toast.clear();}
        };
        auto send=[&](const char*action,int quality=0){
            if(pending_seq||replacing)return;
            pending_seq=++request_seq;pending_at=SDL_GetTicks();
            emit_request({{"action",action},{"seq",pending_seq},{"quality",quality},{"codec",quality}});notice("正在加载…");
        };
        auto set_pause=[&](){if(hw.active)hw.command({{"op","pause"},{"value",pause!=0}});else mpv_set_property(m,"pause",MPV_FORMAT_FLAG,&pause);};
        auto seek_to=[&](double target){
            if(live||!loaded||replacing||pending_seq||!std::isfinite(target))return;
            target=std::max(0.,target);if(duration>0)target=std::min(target,std::max(0.,duration-.05));
            if(hw.active){
                if(!seek_reload.begin(true,false,SDL_GetTicks()))return;
                // Long-lived queue2/OMX pipelines can block a flushing seek.
                // Re-preroll a clean worker, preserving the pause and volume.
                hw.close();
                if(hw.failed||load_selected(transition.current,target,pause!=0)<0){seek_reload.fail();failure=true;finished=true;reason="hardware-seek-open";return;}
                hw.command({{"op","volume"},{"value",volume}});reset_hardware_picture=false;
                loaded=false;replacing=true;idle=1;redraw=true;notice("正在跳转…");
            }else {
                std::string value=std::to_string(target);const char*cmd[]={"seek",value.c_str(),"absolute+exact",nullptr};
                if(mpv_command_async(m,2,cmd)<0)return;
            }
            previous=-1;health.tracking=false;seeks++;
        };
        auto seek=[&](double delta){seek_to(pos+delta);};
        auto release_rate=[&](){if(hold_rate.release()){gesture_owned=false;playback_rate=hold_rate.original;notice("恢复原播放倍速");}};
        auto action=[&](const Button&b){
            redraw=true;overlay.reveal(SDL_GetTicks());const std::string&a=b.action;
            if(a.rfind("feature-",0)==0){
                if(a=="feature-close"){features.close();menu=0;return;}
                if(features.busy)return;
                auto ask=[&](const char*op,J args=J::object()){emit_request(features.request(op,args,SDL_GetTicks()));};
                if(a=="feature-comments") {menu=8;features.page="comments";features.opened++;features.root.clear();features.history.clear();features.rows=J::array();emit_request(features.comments(0,SDL_GetTicks()));}
                else if(a=="feature-account"){menu=8;features.page="interaction";features.confirm.clear();ask("relation");}
                else if(a=="feature-refresh"){if(features.page=="comments")emit_request(features.comments(0,SDL_GetTicks()));else if(features.page=="favorites")ask("favorites");else if(features.page=="chapters"||features.page=="subtitles")ask("player_metadata");else ask("relation");}
                else if(a=="feature-subtitles"||a=="feature-chapters"){
                    if(live){notice("直播不提供点播字幕或章节");return;}
                    menu=8;features.page=a=="feature-subtitles"?"subtitles":"chapters";features.rows=J::array();ask("player_metadata");
                }else if(a=="feature-select"&&!features.rows.empty()){
                    auto row=features.rows[features.at];
                    if(features.page=="chapters"){seek_to(row.value("start",0.));features.close();menu=0;}
                    else if(features.page=="subtitles")ask("player_subtitle",{{"track",row.value("id","")}});
                }else if(a=="feature-sub-toggle"){
                    if(features.cues.empty()){features.error="请先选用一种字幕";return;}features.subtitle_on=!features.subtitle_on;
                }else if(a=="feature-sub-settings"){features.page="subtitle-settings";features.error.clear();}
                else if(a=="feature-sub-size-"||a=="feature-sub-size+"){features.subtitle_scale=std::clamp(features.subtitle_scale+(a=="feature-sub-size+"?.08:-.08),.48,1.2);}
                else if(a=="feature-sub-delay-"||a=="feature-sub-delay+"){features.subtitle_offset=std::clamp(features.subtitle_offset+(a=="feature-sub-delay+"?.5:-.5),-10.,10.);}
                else if(a=="feature-sub-reset"){features.subtitle_scale=.76;features.subtitle_offset=0;}
                else if(a=="feature-up")features.scroll=std::max(0,features.scroll-3);
                else if(a=="feature-down")features.scroll=std::min(237,features.scroll+3);
                else if(a=="feature-next"){
                    features.confirm.clear();features.scroll=0;
                    if(features.at+1<int(features.rows.size()))features.at++;
                    else if(features.page=="comments"&&features.more){features.history.push_back(features.snapshot());if(features.history.size()>8)features.history.erase(features.history.begin());emit_request(features.comments(features.next,SDL_GetTicks()));}
                }else if(a=="feature-prev"){
                    features.confirm.clear();features.scroll=0;
                    if(features.at>0)features.at--;
                    else if(features.page=="comments"&&!features.history.empty()){auto saved=features.history.back();features.history.pop_back();features.restore(saved);features.at=std::max(0,int(features.rows.size())-1);}
                }else if(a=="feature-replies"){
                    if(!features.root.empty()){features.restore(features.saved_comments);features.history.clear();}
                    else if(!features.rows.empty()&&features.rows[features.at].value("replies",0)>0){features.saved_comments=features.snapshot();features.root=features.rows[features.at].value("id","");features.history.clear();emit_request(features.comments(0,SDL_GetTicks()));}
                }else if(a=="feature-favorites"){features.page="favorites";features.rows=J::array();features.confirm.clear();ask("favorites");}
                else {
                    if(features.nonce.empty()){features.error="请刷新状态后再操作";return;}
                    J args={{"intent",features.nonce}};
                    if(a=="feature-like"){args["action"]="like";args["value"]=!features.relation.value("like",false);}
                    else if(a=="feature-triple")args["action"]="triple";
                    else if(a=="feature-coin1"||a=="feature-coin2"){
                        std::string wanted=a=="feature-coin1"?"coin1":"coin2";
                        if(features.confirm!=wanted){features.confirm=wanted;features.error="投币后不可撤回，再次点击确认";return;}
                        args["action"]="coin";args["count"]=wanted=="coin1"?1:2;
                    }else if(a=="feature-folder"&&!features.rows.empty()){
                        if(features.confirm!="favorite"){features.confirm="favorite";features.error="再次点击确认更改此收藏夹";return;}
                        args["action"]="favorite";args["folder"]=features.rows[features.at].value("id","");args["value"]=!features.rows[features.at].value("selected",false);
                    }else return;
                    ask("interaction",args);features.nonce.clear();
                }
                return;
            }
            if(a=="listen"){
                if(!loaded||replacing||pending_seq)return;
                J packet=transition.current;packet["listen"]=!listening;
                loaded=false;replacing=true;
                if(load_selected(packet,live?0:pos,pause!=0)<0){failure=true;finished=true;reason="listen-open";return;}
                listening=!listening;audio_lease_release=listening;transition.current=packet;menu=0;dm_dirty=true;idle=1;redraw=true;notice(listening?"听视频 · 已关闭视频解码":"已返回视频");return;
            }
            if(a=="rate-menu"){if(live){notice("直播按实时速度播放");return;}menu=9;return;}
            if(a=="rate"){
                if(live||!loaded||replacing||pending_seq||b.value<50||b.value>200)return;
                playback_rate=b.value/100.;menu=0;
                if(hw.active)seek_to(pos);else mpv_set_property(m,"speed",MPV_FORMAT_DOUBLE,&playback_rate);
                notice("倍速已选："+std::to_string(playback_rate).substr(0,4)+"× · 高画质可能掉帧");return;
            }
            if(settings.change(a,b.value)){configure_view(m,layout,story,settings);dm_dirty=true;settings_changes++;emit_request({{"action","settings"},{"settings",settings.json()}});if(a=="aspect")menu=0;return;}
            if(a=="back"){finished=true;reason="back";}
            else if(a=="pause"){pause=!pause;set_pause();pauses++;}
            else if(a=="volume-"||a=="volume+"){volume=std::max(0.,std::min(100.,volume+(a=="volume+"?10:-10)));if(hw.active)hw.command({{"op","volume"},{"value",volume}});else mpv_set_property(m,"volume",MPV_FORMAT_DOUBLE,&volume);}
            else if(a=="rotate"){layout.orientation=layout.portrait()?p011_player::Orientation::Landscape:p011_player::Orientation::PortraitClockwise;configure_view(m,layout,story,settings);menu=0;rotations++;dm_dirty=true;}
            else if(a=="danmaku"){dm_on=!dm_on;dm_toggles++;if(dm_on&&dm_failed)notice("弹幕暂不可用，视频继续播放");}
            else if(a=="quality-menu"){menu=1;menu_page=0;}else if(a=="more"||a=="settings-back"){menu=2;menu_page=0;}else if(a=="close")menu=0;
            else if(a=="codec-menu"){menu=3;menu_page=0;}else if(a=="codec"){menu=0;send("codec",b.value);}
            else if(a=="dm-menu")menu=4;
            else if(a=="dm-layout")menu=5;else if(a=="aspect-menu")menu=6;else if(a=="stats-menu")menu=7;
            else if(a=="dm-filter"&&b.value>=0&&b.value<6){if(b.value==0)dm_on=!dm_on;else dm_filters[b.value]=!dm_filters[b.value];}
            else if(a=="menu-prev")menu_page=std::max(0,menu_page-1);
            else if(a=="menu-next"){int n=layout.portrait()?5:6;menu_page=std::min(menu==2?2:int((menu==3?codecs:qualities).size()-1)/n,menu_page+1);}
            else if(a=="quality"){menu=0;send("quality",b.value);}
            else if(a=="next"||a=="previous"){menu=0;send(a.c_str());}
        };
        auto pointer_down=[&](Point physical,Uint32 now){
            Point logical;if(down||!layout.logical(physical,logical))return;down=true;down_point=logical;pointer_latest=logical;down_at=now;down_owned=false;scrubbing=false;gesture_owned=false;
            auto all=buttons(overlay.visible(now));
            for(auto it=all.rbegin();it!=all.rend();++it)if(it->box.contains(logical)){pressed=*it;down_owned=true;break;}
            if(!live&&!down_owned&&!menu&&overlay.visible(now)&&loaded&&!replacing&&duration>0&&p011_player::progress_box(layout,story).contains(logical)){
                scrubbing=true;scrub_ratio=p011_player::progress_ratio(layout,logical,story);overlay.reveal(now);
            }
            if(!live&&!down_owned&&!scrubbing&&!menu&&loaded&&!replacing&&!pending_seq&&!slide.active()&&p011_player::video_box(layout,story).contains(logical)){
                gesture_owned=true;gesture.begin(logical,now,pos,duration,p011_player::video_box(layout,story).w,layout.portrait());
            }
        };
        auto pointer_move=[&](Point physical,Uint32 now){
            if(!down)return;Point logical;if(!layout.logical(physical,logical))return;pointer_latest=logical;
            if(hold_rate.active)return;
            if(scrubbing){scrub_ratio=p011_player::progress_ratio(layout,logical,story);overlay.reveal(now);redraw=true;}
            else if(gesture_owned){gesture.move(logical);redraw=true;
                if(gesture.axis==p011_player::VideoGesture::Horizontal)overlay.reveal(now);
                if(story&&gesture.axis==p011_player::VideoGesture::Vertical)slide.drag(gesture.delta);
            }
        };
        auto pointer_up=[&](Point physical,Uint32 now){
            if(hold_rate.active){down=false;release_rate();return;}
            if(!down)return;pointer_move(physical,now);redraw=true;down=false;Point logical;if(!layout.logical(physical,logical)){scrubbing=false;gesture_owned=false;slide.cancel(now);return;}
            if(scrubbing){scrubbing=false;scrub_ratio=p011_player::progress_ratio(layout,logical,story);seek_to(duration*scrub_ratio);scrub_actions++;overlay.reveal(now);return;}
            if(down_owned){if(pressed.box.contains(logical)&&std::abs(logical.x-down_point.x)<36&&std::abs(logical.y-down_point.y)<36){auto target=pressed;if(target.action=="feature-like"&&now-down_at>=900)target.action="feature-triple";action(target);}return;}
            if(gesture_owned&&gesture.axis==p011_player::VideoGesture::Horizontal){seek_to(gesture.target);video_seek_actions++;gesture_owned=false;overlay.reveal(now);return;}
            if(gesture_owned&&gesture.axis==p011_player::VideoGesture::Vertical){
                bool commit=gesture.commit(now);if(story)slide.release(commit,now);
                if(commit){swipes++;send(gesture.delta<0?"next":"previous");}else slide_cancels++;
                gesture_owned=false;return;
            }
            if(gesture_owned&&gesture.axis!=p011_player::VideoGesture::Pending){gesture_owned=false;return;}
            gesture_owned=false;
            if(pending_seq||replacing||slide.active())return;
            auto swipe=layout.swipe(down_point,logical,now-down_at,false);
            if(!live&&swipe!=p011_player::Swipe::None&&!menu){swipes++;send(swipe==p011_player::Swipe::Next?"next":"previous");return;}
            if(!menu&&std::abs(logical.x-down_point.x)<24&&std::abs(logical.y-down_point.y)<24){if(story){pause=!pause;set_pause();pauses++;overlay.reveal(now);}else{overlay.tap(now);overlay_taps++;}}
        };
        auto test_action=[&](const std::string&a){
            if(!automated)return;
            if(a.rfind("capture_",0)==0){std::string name=a.substr(8);std::replace(name.begin(),name.end(),'_','-');capture_name="player-"+name;return;}
            Uint32 now=SDL_GetTicks();
            // Historical QA names now exercise the real swipe-to-seek path,
            // not invisible +/- buttons or a direct seek shortcut.
            if(a=="seek-"||a=="seek+"){
                auto box=p011_player::video_box(layout,story);Point from={box.x+box.w/2,box.y+box.h*.6};
                float dx=15*box.w/std::min(180.,std::max(30.,duration));if(a=="seek-")dx=-dx;
                pointer_down(layout.physical(from),now);pointer_move(layout.physical({from.x+dx,from.y}),now+180);pointer_up(layout.physical({from.x+dx,from.y}),now+220);return;
            }
            if(a=="tap_center"){auto p=layout.physical(layout.portrait()?Point{134,400}:Point{400,160});pointer_down(p,now);pointer_up(p,now+40);return;}
            if((a=="swipe_next"||a=="swipe_previous")&&layout.portrait()){bool next=a=="swipe_next";pointer_down(layout.physical({134,next?550.:350.}),now);pointer_move(layout.physical({134,450}),now+90);pointer_up(layout.physical({134,next?350.:550.}),now+180);return;}
            if(a=="video_seek"||a=="video_seek_hold"||a=="story_drag_hold"||a=="story_drag_cancel"){
                auto start=layout.portrait()?Point{90,450}:Point{320,160};pointer_down(layout.physical(start),now);
                Point end=a.rfind("video_seek",0)==0?Point{start.x+80,start.y+4}:Point{start.x,start.y-90};
                pointer_move(layout.physical(end),now+250);if(a!="story_drag_hold"&&a!="video_seek_hold")pointer_up(layout.physical(end),now+500);return;
            }
            if(a=="gesture_release"){pointer_up(layout.physical(pointer_latest),now);return;}
            if(a=="hold_rate_start"){pointer_down(layout.physical(layout.portrait()?Point{134,400}:Point{400,160}),now);return;}
            if(a=="hold_rate_release"){pointer_up(layout.physical(pointer_latest),now);return;}
            if(a=="seek_dm"){if(!danmaku.empty())seek(danmaku[0].time+1-pos);return;}
            if(a=="story_start"){send("story");return;}
            if(a=="story_replay_probe"){if(story&&hw.active&&duration>2&&!pending_seq&&!replacing)seek_to(duration-1.5);return;}
            if(a=="dm_fixture"){
                danmaku.clear();dm_on=true;dm_fixture=true;pause=1;set_pause();
                for(int mode=1;mode<=6;mode++){p011_dm::Item d;d.time=std::max(0.,pos-2.5);d.mode=mode;d.size=25;d.life=mode==4||mode==5?4:8;
                    d.text=mode==4?"底部固定":mode==5?"顶部固定":mode==6?"逆向滚动":"滚动弹幕 "+std::to_string(mode);
                    d.color=mode==2?0xff6666:mode==4?0x66ff99:mode==5?0xffdd44:0xffffff;danmaku.push_back(d);}
                p011_dm::Item advanced;advanced.mode=7;advanced.time=std::max(0.,pos-1);advanced.life=5;advanced.text="高级 · 位移/透明度";advanced.color=0x66ccff;
                advanced.advanced={{"life",5},{"path",{{.05,.55},{.55,.6}}},{"relative",true},{"move",4},{"alpha0",1},{"alpha1",.5},{"rotate_z",8}};
                danmaku.push_back(advanced);std::stable_sort(danmaku.begin(),danmaku.end(),[](const p011_dm::Item&a,const p011_dm::Item&b){return a.time<b.time;});dm_dirty=true;menu=0;return;
            }
            if(a=="progress_quarter"||a=="progress_drag"){
                overlay.reveal(now);Rect b=p011_player::progress_box(layout,story);auto start=layout.physical({b.x+6+(b.w-12)*.25,b.y+b.h/2});
                auto end=layout.physical({b.x+6+(b.w-12)*(a=="progress_drag"?.5:.25),b.y+b.h/2});
                pointer_down(start,now);pointer_move(end,now+80);pointer_up(end,now+120);return;
            }
            overlay.reveal(now);std::string target=a;int value=-1;
            if(a=="quality_32"||a=="quality_80"){menu=1;target="quality";value=std::stoi(a.substr(8));for(size_t i=0;i<qualities.size();i++)if(qualities[i]==value)menu_page=int(i)/(layout.portrait()?5:6);}
            if(a=="codec_7"||a=="codec_12"||a=="codec_13"){menu=3;target="codec";value=std::stoi(a.substr(6));}
            if(a=="codec-menu"||a=="dm-menu"||a=="aspect-menu"||a=="dm-layout"||a=="stats-menu"){menu=2;menu_page=0;}
            if(a=="aspect_fit"||a=="aspect_fill"){menu=6;target="aspect";value=a=="aspect_fit"?0:1;}
            if(a=="rate_150"||a=="rate_100"){menu=9;target="rate";value=a=="rate_150"?150:100;}
            for(const auto&b:buttons(true))if(b.action==target&&(value<0||b.value==value)){
                auto p=layout.physical({b.box.x+b.box.w/2,b.box.y+b.box.h/2});pointer_down(p,now);pointer_up(p,now+40);return;
            }
        };
        while(!finished&&!stopping&&SDL_GetTicks()-start<Uint32(seconds*1000)){
            const bool profile_playing=hw.active&&loaded&&!pause&&!idle&&!replacing;
            uint64_t profile_at=SDL_GetPerformanceCounter();
            SDL_Event e;while(SDL_PollEvent(&e)){
                Uint32 now=SDL_GetTicks();
                if(e.type==SDL_QUIT||(e.type==SDL_KEYDOWN&&e.key.keysym.sym==SDLK_ESCAPE)){finished=true;reason="back";}
                if(e.type==SDL_FINGERDOWN&&!finger_down){active_finger=e.tfinger.fingerId;finger_down=true;pointer_down(surface.from_normalized({e.tfinger.x,e.tfinger.y}),now);}
                if(e.type==SDL_FINGERUP&&finger_down&&e.tfinger.fingerId==active_finger){pointer_up(surface.from_normalized({e.tfinger.x,e.tfinger.y}),now);finger_down=false;}
                if(e.type==SDL_FINGERMOTION&&finger_down&&e.tfinger.fingerId==active_finger)pointer_move(surface.from_normalized({e.tfinger.x,e.tfinger.y}),now);
                if(e.type==SDL_WINDOWEVENT&&e.window.event==SDL_WINDOWEVENT_FOCUS_LOST){release_rate();down=false;finger_down=false;scrubbing=false;gesture_owned=false;if(!slide.waiting)slide.cancel(now);}
                if(e.type==SDL_MOUSEMOTION&&e.motion.which!=SDL_TOUCH_MOUSEID){int w=0,h=0;SDL_GetWindowSize(window,&w,&h);if(w&&h)pointer_move(surface.from_normalized({double(e.motion.x)/w,double(e.motion.y)/h}),now);}
                if((e.type==SDL_MOUSEBUTTONDOWN||e.type==SDL_MOUSEBUTTONUP)&&e.button.which!=SDL_TOUCH_MOUSEID){int w=0,h=0;SDL_GetWindowSize(window,&w,&h);if(w&&h){Point p=surface.from_normalized({double(e.button.x)/w,double(e.button.y)/h});if(e.type==SDL_MOUSEBUTTONDOWN)pointer_down(p,now);else pointer_up(p,now);}}
            }
            if(down&&gesture_owned&&gesture.axis==p011_player::VideoGesture::Pending&&!live&&!pause&&!menu&&features.page.empty()&&loaded&&!replacing&&!pending_seq&&SDL_GetTicks()-down_at>=900&&hold_rate.begin(playback_rate)){
                playback_rate=2.;hold_rate_actions++;
                if(hw.active)seek_to(pos);else mpv_set_property(m,"speed",MPV_FORMAT_DOUBLE,&playback_rate);
                notice("2× 加速中 · 松开恢复");
            }
            if(hold_rate.restore_pending&&loaded&&!replacing&&!pending_seq){
                playback_rate=hold_rate.original;hold_rate.restored();hold_rate_restores++;
                if(hw.active)seek_to(pos);else mpv_set_property(m,"speed",MPV_FORMAT_DOUBLE,&playback_rate);
            }
            // Bound both UI read work and decoder queueing. Do not read more
            // while a complete packet is waiting for the single worker slot.
            if(input_buffer.find('\n')==input_buffer.npos){
                char bytes[16384];size_t used=0;
                while(used<65536){
                    if(input_buffer.size()>=p011_ipc::Decoder::max_bytes)throw 30;
                    ssize_t n=read(STDIN_FILENO,bytes,std::min(sizeof(bytes),p011_ipc::Decoder::max_bytes-input_buffer.size()));
                    if(n<=0)break;input_buffer.append(bytes,n);used+=size_t(n);
                    if(input_buffer.find('\n')!=input_buffer.npos)break;
                }
            }
            size_t newline=input_buffer.find('\n');
            if(newline!=input_buffer.npos&&packet_decoder.submit(input_buffer,newline))input_buffer.erase(0,newline+1);
            std::unique_ptr<p011_ipc::Packet> decoded;
            while(packet_decoder.take(decoded)){
                J&packet=decoded->value;if(!packet.is_object())continue;
                std::string op=packet.value("op","");
                if(op=="test"){test_action(packet.value("action",""));continue;}
                if(op=="feature"){
                    if(features.accept(packet)){
                        redraw=true;
                        if(packet.value("feature","")=="player_preview"&&!decoded->image.empty()){
                            if(!preview_texture.id)glGenTextures(1,&preview_texture.id);
                            glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,preview_texture.id);
                            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,decoded->image_width,decoded->image_height,0,GL_RGBA,GL_UNSIGNED_BYTE,decoded->image.data());
                            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
                            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
                            preview_start=packet["data"].value("start",-1.);preview_end=packet["data"].value("end",0.);preview_serial=serial;preview_images++;
                        }
                    }continue;
                }
                if(op=="preferences"&&!packet.value("ok",true)){notice("本次设置已生效，但保存失败");continue;}
                if(op=="live-status"&&live){live_dm_authenticated=packet.value("authenticated",false);dm_loaded=live_dm_authenticated;dm_failed=packet.value("failed",false);continue;}
                if(op=="live-danmaku"&&live){
                    live_dm_received+=decoded->danmaku.size();
                    if(loaded&&!pause&&!idle&&!listening)for(auto&d:decoded->danmaku)if(live_pending.size()<32){d.time=pos+.05;d.mode=1;live_pending.push_back(std::move(d));}
                    continue;
                }
                if(op=="danmaku"&&packet.value("serial",0)==serial&&!dm_fixture){danmaku=std::move(decoded->danmaku);dm_dirty=true;dm_loaded=packet.value("ok",false);dm_failed=!dm_loaded;continue;}
                if(op=="stream"&&pending_seq&&packet.value("seq",0u)==pending_seq){
                    unsigned accepted_seq=pending_seq;pending_seq=0;
                    if(!packet.value("ok",false)){slide.cancel(SDL_GetTicks());std::string error=packet.value("error","");notice(error=="CANCELED"?"已经是第一条":error=="RESOURCE_LIMIT"?"内存不足，已保留当前画质":"暂时无法切换，请重试");continue;}
                    bool keep=packet.value("keep_position",false);double next_pos=live?0:keep?pos:0;
                    packet["live"]=live;packet["listen"]=listening&&!packet.value("story",false);
                    previous_orientation=layout.orientation;
                    if(!transition.begin(accepted_seq,packet,pos,pause!=0,SDL_GetTicks()))continue;
                    replay.cancel();
                    seek_reload.cancel();
                    previous_dm_on=dm_on;
                    replacing=true;loaded=false;previous=-1;
                    if(packet.value("story",false)&&!story){story=true;dm_on=false;layout.orientation=p011_player::Orientation::PortraitClockwise;configure_view(m,layout,true,settings);mpv_set_property_string(m,"loop-file","inf");dm_dirty=true;rotations++;}
                    last_mpv_error=load_selected(packet,next_pos,keep&&pause);
                    if(last_mpv_error<0){recover_switch();continue;}
                    redraw=true;
                    if(!keep){pos=0;duration=0;pause=0;set_pause();}
                    if(hw.active)hw.command({{"op","volume"},{"value",volume}});
                    notice(keep?"正在切换画质…":"正在打开下一视频…");
                }
            }
            mpv_event*event;while((event=mpv_wait_event(m,0))->event_id!=MPV_EVENT_NONE){
                if(hw.active)continue;
                if(event->event_id==MPV_EVENT_PROPERTY_CHANGE){auto prop=static_cast<mpv_event_property*>(event->data);if(prop->data){
                    switch(event->reply_userdata){
                    case 1:pause=*static_cast<int*>(prop->data);redraw=true;break;
                    case 2:idle=*static_cast<int*>(prop->data);break;
                    case 3:pos=*static_cast<double*>(prop->data);break;
                    case 4:duration=*static_cast<double*>(prop->data);break;
                    case 5:source_width=int(*static_cast<int64_t*>(prop->data));break;
                    case 6:source_height=int(*static_cast<int64_t*>(prop->data));break;
                    case 7:source_fps=*static_cast<double*>(prop->data);break;
                    case 8:avsync=*static_cast<double*>(prop->data);break;
                    case 9:drops=*static_cast<int64_t*>(prop->data);break;
                    case 10:decoder_drops=*static_cast<int64_t*>(prop->data);break;
                    case 11:{const char*s=*static_cast<char**>(prop->data);std::string fmt=s?s:"";observed_codec=fmt=="h264"?7:fmt=="hevc"?12:fmt=="av1"?13:0;break;}
                    case 12:{const char*s=*static_cast<char**>(prop->data);if(s&&std::string(s)=="pulse")pulse=true;break;}
                    case 13:upload_width=int(*static_cast<int64_t*>(prop->data));break;
                    case 14:upload_height=int(*static_cast<int64_t*>(prop->data));break;
                    }
                }}
                if(event->event_id==MPV_EVENT_FILE_LOADED){loaded=true;if(!transition.seq){replacing=false;health={};toast.clear();}redraw=true;mpv_set_property(m,"pause",MPV_FORMAT_FLAG,&pause);}
                if(event->event_id==MPV_EVENT_END_FILE){auto end=static_cast<mpv_event_end_file*>(event->data);if(replacing&&end->reason==MPV_END_FILE_REASON_STOP)continue;last_mpv_error=end->error;if(transition.seq&&end->error<0){if(!recover_switch())reject_switch();continue;}failure=end->error<0;finished=true;reason=failure?"error":"eof";}
            }
            profile_record(p011_profile::Input,profile_at,profile_playing,pos);profile_at=SDL_GetPerformanceCounter();
            Uint32 now=SDL_GetTicks();if(pending_seq&&now-pending_at>50000){emit_request({{"action","stream_result"},{"seq",pending_seq},{"ok",false}});pending_seq=0;slide.cancel(now);notice("加载超时，请重试");}
            if(transition.expired(now)){if(!recover_switch())reject_switch();}
            if(replay.expired(now)){replay.fail();failure=true;finished=true;reason="story-replay-timeout";}
            if(seek_reload.expired(now)){seek_reload.fail();failure=true;finished=true;reason="hardware-seek-timeout";}
            if(hw.active){
                hw.poll(now);
                if(hw.failed){J detail=hw.error_detail;detail["error"]=hw.error;save("hardware-error.json",detail);if(transition.seq){if(!recover_switch())reject_switch();}else {replay.fail();seek_reload.fail();failure=true;finished=true;reason="hardware-error";}}
                if(!finished&&hw.eof){
                    seek_reload.cancel();
                    if(transition.seq){if(!recover_switch())reject_switch();}
                    else if(story){
                        if(!replay.begin(true,false,now)){replay.fail();failure=true;finished=true;reason="story-replay-empty";}
                        else {
                            // Never keep two decoders alive. Close validates the final
                            // cache ownership report before a fresh worker is opened.
                            hw.close();
                            if(hw.failed||load_selected(transition.current,0,pause!=0)<0){replay.fail();failure=true;finished=true;reason="story-replay-open";}
                            else {
                                hw.command({{"op","volume"},{"value",volume}});
                                reset_hardware_picture=false; // Retain only the last GL picture until a new frame.
                                loaded=false;replacing=true;pos=0;previous=-1;idle=1;health={};redraw=true;
                            }
                        }
                    }else {finished=true;reason="eof";}
                }
                if(!finished&&hw.active&&hw.got_status){const auto&s=hw.status;bool ready=s.value("ready",false)&&s.value("delivered",0)>0;
                    if(ready&&!loaded){loaded=true;if(!transition.seq&&!replay.pending&&!seek_reload.pending){replacing=false;health={};toast.clear();}redraw=true;}
                    pos=hw.position();duration=s.value("duration",0.);idle=!ready||s.value("seeking",false);pulse=s.value("pulse",false);source_fps=s.value("source_fps",0.);
                    source_width=s.value("source_width",0);source_height=s.value("source_height",0);upload_width=s.value("upload_width",0);upload_height=s.value("upload_height",0);
                    observed_codec=7;drops=s.value("drops",int64_t(0))+hw.ui_drops;decoder_drops=s.value("decoder_drops",int64_t(0));avsync=hw.displayed_pts-pos;
                }
            }
            if(loaded){if(pos>previous+.01||pos<previous-.1){lastadvance=now;previous=pos;}maxpos=std::max(maxpos,pos);}
            if(features.busy&&now-features.began>50000){features.busy=false;features.pending=0;features.error="请求超时，请刷新状态后重试";redraw=true;}
            if(transition.seq&&(transition.restoring?transition.current:transition.next).value("listen",false)&&loaded&&pulse&&pos>0)complete_switch();
            bool active=loaded&&!pause&&!idle&&pos>0&&now-lastadvance<2000&&!finished;overlay.playback(now,active);if(scrubbing)overlay.reveal(now);bool visible=overlay.visible(now);
            if(now-lastwrite>=500){
                frames.sample(now);
                const auto stats_rate_state=p011_player::frame_rate_state(loaded,pause!=0,active,pending_seq!=0||replacing,frames.submitted_fps);
                if(compatible()&&!compat_notified){
                    notice("高帧率降帧兼容；实际帧率见播放信息");toast_until=now+7000;compat_notified=true;redraw=true;
                }
                if(health.observe(now,active&&!pending_seq&&!replacing&&!menu,source_fps,frames.submitted_fps,avsync)){
                    if(!compatible()||std::abs(avsync)>.2||frames.submitted_fps<std::min(30.,source_fps/2)*.9){notice("当前规格播放吃力，可降低画质或切换编码");toast_until=now+6000;redraw=true;}
                }
                double cpu=double(std::clock())/CLOCKS_PER_SEC;cpu_pct=(cpu-cpu_last)*100000/std::max(1u,now-cpu_at)+(hw.active?hw.status.value("cpu_percent",0.):0.);cpu_last=cpu;cpu_at=now;
                J ms=settings.json();ms.update({{"stats_rate_state",unsigned(stats_rate_state)},{"performance_limited",health.limited},{"performance_warning_shown",health.warned},{"generation",generation},{"selected_codec",actual_codec},{"observed_codec",observed_codec},{"codec_switches",codec_switches},{"story",story},{"story_page",story_page},{"dm_fixture",dm_fixture},{"dm_scheduled",dm_timeline.size()},{"dm_dropped",dm_timeline.dropped},{"source_width",source_width},{"source_height",source_height},{"source_fps",source_fps},{"decoder_drops",decoder_drops},{"avsync",avsync},{"cpu_percent",cpu_pct},{"draws",draws},{"skipped_draws",skipped_draws},{"settings_changes",settings_changes}});
                ms.update({{"hardware_backend",hw.active},{"hardware_verified",hw.verified()},{"hardware_private_plugin",hw.active&&hw.status.value("omx_private_plugin",false)},{"hardware_error",hw.error},{"hardware_encoded",hw.status.value("encoded",0)},{"hardware_decoded",hw.status.value("decoded",0)},{"hardware_delivered",hw.status.value("delivered",0)},{"hardware_copy_us",hw.status.value("copy_us",0ULL)},{"hardware_map_us",hw.status.value("map_us",0ULL)},{"hardware_pull_us",hw.status.value("pull_us",0ULL)},
                           {"hardware_sample_age_ms",hw.sample_age_us()/1000.},{"hardware_sampled_position",hw.status.value("position",0.)},{"hardware_raw_position_delta",hw.active?hw.displayed_pts-hw.status.value("position",0.):0.},
                           {"high_fps_compat",compatible()},{"hardware_nonref_skipped",hw.status.value("encoded_nonref_skipped",0u)},
                           {"hardware_nonref_keep_every",hw.status.value("nonref_keep_every",0u)},
                           {"hardware_cached_retention_active",hw.active&&hw.status.value("cached_retention_active",false)},
                           {"hardware_fused_copy",hw.active&&hw.status.value("fused_half_copy",false)},
                           {"hardware_fused_frames",hw.status.value("fused_half_frames",0ULL)},
                           {"hardware_output_width",hw.status.value("output_width",0)},{"hardware_output_height",hw.status.value("output_height",0)},
                           {"hardware_sink_qos_drops",hw.status.value("sink_qos_drops",0ULL)},
                           {"hardware_shared_slot_drops",hw.status.value("shared_slot_drops",0ULL)},
                           {"hardware_ui_ready_drops",hw.ui_drops},{"hardware_total_drops",hw.status.value("drops",0ULL)+hw.ui_drops},
                           {"glyph_rasterizations",painter.glyph_rasterizations},{"glyph_metric_loads",painter.glyph_metric_loads},
                           {"glyph_evictions",painter.glyph_evictions},{"glyph_quad_calls",painter.quad_calls}});
#ifdef P011_BUNDLED_OUTPUT_CACHE
                ms["hardware_cache_feature"]=true;
                for(const char*key:{"output_cache_enabled","cache_vendor_verified","cache_changed_allocations","cache_active",
                        "cache_registered","cache_forgotten","cache_read_begin","cache_read_end","cache_sync_errors","cache_ownership_errors",
                        "cache_fallback_registered","cache_fallback_forgotten","cache_fallback_active","cache_fallback_read_begin","cache_fallback_read_end"}){
                    auto found=hw.status.find(key);if(found!=hw.status.end()&&(found->is_number_unsigned()||found->is_boolean()))ms[std::string("hardware_")+key]=*found;
                }
                ms["hardware_output_cache_enabled"]=hw.active&&hw.status.value("output_cache_enabled",false);
#endif
                ms.update({{"video_seek_actions",video_seek_actions},{"slide_frames",slide_frames},{"slide_cancels",slide_cancels},{"slide_offset",slide.offset}});
                ms.update({{"cached_media",hw.active&&hw.status.value("cached_media",false)},{"gesture_seeking",down&&gesture_owned&&gesture.axis==p011_player::VideoGesture::Horizontal}});
                double ahead_seconds=0;if(!hw.active)mpv_get_property(m,"demuxer-cache-duration",MPV_FORMAT_DOUBLE,&ahead_seconds);
                ms["prefetch_safe"]=hw.active?hw.status.value("prefetch_safe",false):std::isfinite(ahead_seconds)&&ahead_seconds>=2.;
                ms["prefix_cache_capable"]=true;
                if(hw.active)for(const char*k:{"prefetch_video_bytes","prefetch_audio_bytes","prefetch_video_eof","prefetch_audio_eof"})ms[k]=hw.status.value(k,J(0));
                ms.update({{"switch_ack",true},{"switch_failures",switch_failures},{"switch_recoveries",switch_recoveries},{"switch_latency_ms",switch_latency_ms},{"switch_total_ms",switch_total_ms}});
                ms.update({{"story_loop_restarts",replay.requested},{"story_loop_completed",replay.completed},{"story_loop_failures",replay.failures},{"story_loop_pending",replay.pending}});
                ms.update({{"hardware_seek_restarts",seek_reload.requested},{"hardware_seek_completed",seek_reload.completed},{"hardware_seek_failures",seek_reload.failures},{"hardware_seek_pending",seek_reload.pending}});
                ms.update({{"live",live},{"listen",listening},{"feature_opened",features.opened},{"feature_comment_reads",features.comment_reads},{"feature_busy",features.busy}});
                ms.update({{"subtitle_tracks",features.tracks.size()},{"subtitle_cues",features.cues.size()},{"subtitle_enabled",features.subtitle_on},{"chapter_count",features.chapters.size()},{"playback_rate",playback_rate},{"preview_images",preview_images},
                    {"hold_rate_active",hold_rate.active},{"hold_rate_restore_pending",hold_rate.restore_pending},{"hold_rate_actions",hold_rate_actions},{"hold_rate_restores",hold_rate_restores}});
                ms.update({{"live_danmaku_received",live_dm_received},{"live_danmaku_authenticated",live_dm_authenticated}});
                profile_fields(ms);save("media-state.json",ms);
                save_watch();
                lease(active);save("player-state.json",{{"upload_width",upload_width},{"upload_height",upload_height},{"submitted_frames",frames.submitted},{"submitted_fps",frames.submitted_fps},{"protocol_version",2},{"generation",generation},{"loaded",loaded},{"position",pos},{"duration",duration},{"paused",pause!=0},{"active",active},{"volume",volume},{"preview",preview},{"pulse_observed",pulse},{"drops",drops},{"progress_visible",visible},{"portrait",layout.portrait()},{"quality",actual_quality},{"switch_pending",pending_seq!=0||replacing},{"quality_switches",quality_switches},{"video_switches",switches},{"danmaku_count",danmaku.size()},{"danmaku_loaded",dm_loaded},{"danmaku_failed",dm_failed},{"danmaku_frames",dm_frames},{"danmaku_visible",dm_on},{"queue_index",queue_at},{"queue_count",queue_count},{"muted",muted},{"menu",menu},{"capture_count",captures},{"pause_actions",pauses},{"seek_actions",seeks},{"scrub_actions",scrub_actions},{"rotation_actions",rotations},{"swipe_actions",swipes}});lastwrite=now;
            }
            profile_record(p011_profile::Status,profile_at,profile_playing,pos);profile_at=SDL_GetPerformanceCounter();
            SDL_GL_GetDrawableSize(window,&width,&height);if(width<=0||height<=0){SDL_Delay(20);continue;}
            if(surface.content_only&&(width!=int(surface.width())||height!=int(surface.height())))throw 37;
            Rect area=p011_player::video_box(layout,story);
            const bool preview_wanted=!live&&!story&&!menu&&(scrubbing||(down&&gesture_owned&&gesture.axis==p011_player::VideoGesture::Horizontal));
            const double preview_position=scrubbing?duration*scrub_ratio:gesture.target;
            const bool preview_current=preview_serial==serial&&preview_position>=preview_start&&preview_position<preview_end;
            if(preview_wanted&&!preview_current&&!features.busy&&now-preview_attempt>1800){
                preview_attempt=now;emit_request(features.request("player_preview",{{"position",preview_position}},now));
            }
            double slide_y=story&&layout.portrait()?slide.sample(now):0;
            if(slide.active()){redraw=true;slide_frames++;}
            // The software renderer has a native pan property; no extra video
            // framebuffer is allocated for either decoder path.
            if(!hw.active&&source_width>0&&source_height>0){
                double ratio=settings.aspect==3?16./9:settings.aspect==4?4./3:double(source_width)/source_height;
                double scaled_h=settings.aspect==1?std::max<double>(area.w/ratio,area.h):std::min<double>(area.w/ratio,area.h);
                double pan=layout.portrait()?-slide_y/std::max(1.,scaled_h):0;
                if(std::abs(pan-last_soft_pan)>.001){mpv_set_property(m,"video-pan-x",MPV_FORMAT_DOUBLE,&pan);last_soft_pan=pan;}
            }
            // Reserve a stable safe area even while controls are hidden. A
            // toolbar appearing must not relocate an already flying comment.
            Rect dm_area=area;
            if(!layout.portrait()){dm_area.y+=50;dm_area.h-=94;}
            else if(story){dm_area.y+=66;dm_area.h-=204;}
            else dm_area.h-=40;
            dm_area.h*=settings.area/100.f;
            if(dm_dirty){dm_builder.start(danmaku,dm_area.w,dm_area.h,settings.size/100.,settings.speed/100.);dm_dirty=false;redraw=true;}
            if(dm_builder.step(dm_timeline,[&](const std::string&s,double scale){return painter.measure(s,scale);},[&](){return (SDL_GetPerformanceCounter()-profile_at)*1000000/profile_frequency;}))redraw=true;
            if(live&&!dm_builder.busy()&&!live_pending.empty()){
                dm_timeline.prune(pos-20);
                danmaku.erase(std::remove_if(danmaku.begin(),danmaku.end(),[&](const p011_dm::Item&d){return d.time<pos-20;}),danmaku.end());
                for(auto&d:live_pending)if(danmaku.size()<200){dm_timeline.append(d,[&](const std::string&s,double scale){return painter.measure(s,scale);});danmaku.push_back(std::move(d));}
                live_pending.clear();redraw=true;
            }
            profile_record(p011_profile::Layout,profile_at,profile_playing,pos);profile_at=SDL_GetPerformanceCounter();
            const bool frame_ready=pacer.before_frame();profile_record(p011_profile::Pacer,profile_at,profile_playing,pos);
            if(!frame_ready)continue;
            bool video_frame=false;p011_hw::Frame*hardware_frame=hw.active?hw.frame():nullptr;
            if(hw.active)video_frame=hardware_frame!=nullptr;
            else if(video_update.exchange(false))video_frame=(mpv_render_context_update(render)&MPV_RENDER_UPDATE_FRAME)!=0;
            Uint32 interval=active&&dm_on&&!danmaku.empty()&&!menu?33:visible&&active?100:250;
            if(!video_frame&&!redraw&&capture_name.empty()&&now-lastdraw<interval){skipped_draws++;SDL_Delay(4);continue;}
            redraw=false;lastdraw=now;Uint64 render_start=SDL_GetPerformanceCounter();
            profile_at=render_start;
            mpv_render_frame_info frame_info={};mpv_render_param fi={MPV_RENDER_PARAM_NEXT_FRAME_INFO,&frame_info};
            if(hw.active)frame_info.flags=video_frame?1:3;
            else if(mpv_render_context_get_info(render,fi)<0)frame_info.flags=0;
            // The old Mali driver faults when sampling the extra video FBO.
            // Use the already accepted direct default-framebuffer path; mpv
            // rotates the video and applies physical margins itself.
            glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,width,height);
            inspect_gl("framebuffer_bind");
            mpv_opengl_fbo fbo={0,width,height,0};int flip=1;mpv_render_param rp[]={{MPV_RENDER_PARAM_OPENGL_FBO,&fbo},{MPV_RENDER_PARAM_FLIP_Y,&flip},{MPV_RENDER_PARAM_INVALID,nullptr}};
            if(hw.active){glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT);inspect_gl("framebuffer_clear");}
            else{mpv_render_context_render(render,rp);inspect_gl("mpv");}
            if(reset_hardware_picture){hardware_picture.clear();reset_hardware_picture=false;}
            if(hw.active){
                if(hardware_frame){
                    if(automated&&!hardware_shapes_tested){check_hardware_shapes(hardware_picture);hardware_shapes_tested=true;}
                    hardware_picture.upload(*hardware_frame);
                    presentation.video_frame(hardware_frame->serial,hardware_frame->pts);
                    hw.release(hardware_frame);inspect_gl("hardware_upload");
                }
                hardware_picture.draw(layout,area,settings.aspect,width,height,slide_y);inspect_gl("hardware_draw");
            }
            profile_record(p011_profile::Upload,profile_at,profile_playing,pos);profile_at=SDL_GetPerformanceCounter();
            painter.begin(width,height);
            if(area.x>0)painter.rect(0,0,area.x,layout.height(),.063,.067,.082);
            if(area.x+area.w<layout.width())painter.rect(area.x+area.w,0,layout.width()-area.x-area.w,layout.height(),.063,.067,.082);
            if(area.y>0)painter.rect(0,0,layout.width(),area.y,.063,.067,.082);
            if(area.y+area.h<layout.height())painter.rect(0,area.y+area.h,layout.width(),layout.height()-area.y-area.h,.063,.067,.082);
            // Incoming placeholder is below navigation: Back remains visible
            // and actionable even while a slow network is loading the item.
            if(slide.active()&&story&&layout.portrait()){
                double incoming=slide_y+(slide_y<0?800:-800);
                float y=std::max(72.,std::min(720.,incoming+400));
                if(std::abs(slide_y)>60){painter.rect(0,slide_y<0?std::max(0.,800+slide_y):0,268,std::abs(slide_y),.065,.067,.083);
                    painter.text(50,y,slide.waiting?"正在加载…":slide_y<0?"继续上滑":"向下查看",.78,0xe8d4df);}
            }
            if(dm_on&&!listening&&!danmaku.empty()&&loaded&&!menu&&!slide.active()&&!dm_builder.busy()){
                auto a=layout.physical({dm_area.x,dm_area.y}),b=layout.physical({dm_area.x+dm_area.w,dm_area.y+dm_area.h});
                auto clip=surface.clip(a,b,width,height);
                glEnable(GL_SCISSOR_TEST);glScissor(clip.x,clip.y,clip.w,clip.h);auto current_dm=dm_timeline.at(pos);
                for(const auto&d:current_dm){const auto&p=*d.source;int mode=p.item.mode;
                    if((!dm_filters[1]&&(mode<=3||mode==6))||(!dm_filters[2]&&mode==5)||(!dm_filters[3]&&mode==4)||(!dm_filters[4]&&p.item.color!=0xffffff)||(!dm_filters[5]&&mode==7))continue;
                    float tx=dm_area.x+d.x,ty=dm_area.y+d.y;
                    painter.transform(tx,ty,d.angle,d.yscale);
                    painter.text(tx,ty,p.item.text,p.scale,p.item.color,d.alpha*settings.opacity/100.f,d.outline);
                }
                painter.transform();if(!current_dm.empty())dm_frames++;glDisable(GL_SCISSOR_TEST);
            }
            if(!listening&&!menu){
                auto text=features.subtitle(pos);
                if(text!=features.subtitle_text||features.subtitle_width!=area.w||features.subtitle_cached_scale!=features.subtitle_scale){
                    features.subtitle_text=text;features.subtitle_width=area.w;features.subtitle_cached_scale=features.subtitle_scale;
                    features.subtitle_lines=p011_player::feature_lines(text,area.w-24,[&](const std::string&s){return painter.measure(s,features.subtitle_scale);});
                }
                const int count=std::min(3,int(features.subtitle_lines.size()));
                float bottom=std::min(area.y+area.h-10,visible?p011_player::progress_box(layout,story).y-8:area.y+area.h-10);
                for(int n=0;n<count;n++){auto&s=features.subtitle_lines[n];float scale=features.subtitle_scale;
                    painter.text(area.x+(area.w-painter.measure(s,scale))/2,bottom-(count-1-n)*30*scale,s,scale,0xffffff,1,true);}
            }
            if(listening&&!menu){painter.rect(area.x,area.y,area.w,area.h,.063,.067,.082);painter.text(area.x+16,area.y+area.h*.44,"听视频 · 仅音频",.95,0xfb7299);painter.text(area.x+16,area.y+area.h*.44+34,"播放设置中可返回视频",.62,0xc0c0c8);}
            if(menu&&features.page.empty()){Rect mbox=layout.portrait()?Rect{4,146,260,464}:Rect{150,0,500,268};painter.rect(mbox.x,mbox.y,mbox.w,mbox.h,.063,.067,.082,.97);painter.text(mbox.x+12,mbox.y+32,menu==1?"清晰度":menu==3?"视频编码 · "+p011_player::codec_label(actual_codec):menu==4?"弹幕类型":menu==5?"弹幕设置 · 点按调整":menu==6?"画面比例":menu==7?"播放信息":menu==9?"播放倍速 · 保持音调":"播放设置 · "+std::to_string(menu_page+1)+"/3",.72);
                if(menu==7){
                    const auto rate_state=p011_player::frame_rate_state(loaded,pause!=0,active,pending_seq!=0||replacing,frames.submitted_fps);
                    std::vector<std::string>lines={std::to_string(source_width)+"×"+std::to_string(source_height)+" · 源 "+std::to_string(int(source_fps+.5))+"fps",p011_player::frame_rate_text(rate_state,frames.submitted_fps),backend_label()+" · CPU "+std::to_string(int(cpu_pct))+"%",(compatible()?"兼容跳帧 "+std::to_string(hw.status.value("encoded_nonref_skipped",0u))+" · ":std::string())+"丢帧 "+std::to_string(drops)+" / 解码 "+std::to_string(decoder_drops),"音画差 "+std::to_string(int(avsync*1000))+"ms · 四核400%"};
                    for(size_t i=0;i<lines.size();i++){
                        float scale=layout.portrait()?.49f:.66f;
                        float measured=painter.measure(lines[i],scale);
                        if(measured>mbox.w-24)scale*=(mbox.w-24)/measured;
                        painter.text(mbox.x+12,mbox.y+66+i*29,lines[i],scale);
                    }
                }
            }
            if(!features.page.empty()){
                auto r=features.box(layout);painter.rounded(r.x,r.y,r.w,r.h,.07,.075,.095,.98);
                std::string heading=features.page=="comments"?(features.root.empty()?"热门评论":"评论回复"):features.page=="favorites"?"选择收藏夹":features.page=="subtitles"?"CC 字幕":features.page=="chapters"?"视频章节":features.page=="subtitle-settings"?"字幕设置":"视频互动";
                if(features.busy)heading+=" · 读取中…";
                painter.text(r.x+12,r.y+27,heading,.73,0xff91b3);
                std::string body;
                if(features.page=="interaction")body="轻点点赞，长按三连（会投币及收藏）\n已投 "+std::to_string(features.relation.value("coin",0))+" 币 · "+(features.relation.value("favorite",false)?"已收藏":"未收藏");
                else if(features.page=="subtitle-settings"){char offset[24];snprintf(offset,sizeof(offset),"%+.1f",features.subtitle_offset);body="字号 "+std::to_string(int(features.subtitle_scale*100))+"%\n字幕偏移 "+offset+" 秒\n正值延后，负值提前；换视频自动清除字幕";}
                else if(!features.rows.empty()&&features.at<int(features.rows.size())){
                    auto row=features.rows[features.at];
                    if(features.page=="subtitles")body=std::to_string(features.at+1)+" / "+std::to_string(features.rows.size())+" · "+row.value("label","")+(row.value("ai",false)?"（AI 字幕）":"")+"\n"+(row.value("id","")==features.subtitle_track?"当前字幕":"点选用载入字幕");
                    else if(features.page=="chapters")body=clock_text(row.value("start",0.))+" · "+row.value("title","")+"\n"+std::to_string(features.at+1)+" / "+std::to_string(features.rows.size());
                    else body=features.page=="comments"?row.value("author","")+" · 赞 "+std::to_string(row.value("likes",0))+"\n"+row.value("text",""):row.value("title","")+"\n"+(row.value("selected",false)?std::string("已加入此收藏夹"):std::string("尚未加入"));
                }else body=features.busy?"正在读取 B 站内容…":"暂无内容";
                if(!features.error.empty())body=features.error+"\n"+body;
                if(body!=features.cached_body||r.w!=features.cached_width){features.cached_body=body;features.cached_width=r.w;features.cached_lines=p011_player::feature_lines(body,r.w-24,[&](const std::string&s){return painter.measure(s,.62f);});}
                const auto&lines=features.cached_lines;
                int line_count=layout.portrait()?10:4;features.scroll=std::min(features.scroll,std::max(0,int(lines.size())-line_count));
                for(int n=0;n<line_count&&features.scroll+n<int(lines.size());n++)painter.text(r.x+12,r.y+53+n*21,lines[features.scroll+n],.62);
                if(lines.size()>size_t(line_count))painter.text(r.x+r.w-102,r.y+132,"可上下翻阅",.48,0xa3a3b1);
            }
            for(const auto&b:buttons(visible)){
                bool selected=(b.action=="quality"&&b.value==actual_quality)||(b.action=="codec"&&b.value==actual_codec)||(b.action=="aspect"&&b.value==settings.aspect)||(b.action=="dm-filter"&&(b.value==0?dm_on:dm_filters[b.value]));
                bool touching=down&&down_owned&&pressed.action==b.action&&pressed.value==b.value;
                painter.rounded(b.box.x,b.box.y,b.box.w,b.box.h,selected?.68:touching?.29:.125,selected?.26:touching?.19:.137,selected?.41:touching?.25:.17,layout.portrait()&&story?.86:1);
                float scale=b.box.w<124?.73f:.92f;float tw=painter.measure(b.label,scale);if(tw>b.box.w-10)scale*=(b.box.w-10)/tw;
                painter.text(b.box.x+(b.box.w-painter.measure(b.label,scale))/2,b.box.y+b.box.h/2+10*scale,b.label,scale);
                if(touching&&b.action=="feature-like")painter.rect(b.box.x,b.box.y+b.box.h-4,b.box.w*std::min(1.,double(now-down_at)/900),4,.98,.44,.6);
            }
            if(visible&&!menu){Rect pb=p011_player::progress_box(layout,story);float px=pb.x,py=pb.y,pw=pb.w;double displayed=scrubbing?duration*scrub_ratio:pos;
                painter.rounded(px,py,pw,pb.h,0,0,0,.62,8);painter.rect(px+6,py+pb.h-7,pw-12,3,.28,.28,.33);if(duration>0){float end=float((pw-12)*std::max(0.,std::min(1.,displayed/duration)));painter.rect(px+6,py+pb.h-7,end,3,.985,.447,.6);painter.rounded(px+1+end,py+pb.h-11,10,10,1,.83,.88,1,5);}
                painter.text(px+6,py+23,live?std::string("直播中 · 不支持快进"):clock_text(displayed)+" / "+clock_text(duration),.62);
                if(!layout.portrait())painter.text(px+184,py+23,(preview?"试看 ":"")+std::string(!loaded?"加载中":pause?"已暂停":idle?"缓冲中":"播放中")+" · "+label(actual_quality)+" "+backend_label(),.49);
                shown++;
            }else hidden++;
            if(story&&layout.portrait()&&!menu&&!slide.active()){
                painter.text(10,686,up.empty()?"发现":up,.62,0xffffff,1,true);
                std::string line=title;while(!line.empty()&&painter.measure(line,.72)>245){size_t end=line.size()-1;while(end>0&&(static_cast<unsigned char>(line[end])&0xc0)==0x80)--end;line.resize(end);}
                painter.text(10,715,line,.72,0xffffff,1,true);painter.text(10,742,pause?"已暂停 · 轻点继续":"上滑继续探索",.60,0xd0d0d8,1,true);
            }
            if(down&&gesture_owned&&gesture.axis==p011_player::VideoGesture::Horizontal){
                const bool picture=preview_wanted&&preview_current&&preview_texture.id;
                float x=layout.portrait()?16:picture?350:245,y=layout.portrait()?picture?422:340:85,w=layout.portrait()?236:picture?264:310;
                painter.rounded(x,y,w,82,.09,.09,.12,.94);painter.text(x+20,y+33,clock_text(gesture.target)+" / "+clock_text(duration),.85,0xff91b3);
                painter.text(x+20,y+63,(gesture.target>=gesture.base?"+":"")+std::to_string(int(gesture.target-gesture.base))+" 秒 · 松手跳转",.65);
            }
            if(preview_wanted&&preview_current&&preview_texture.id){
                float x=layout.portrait()?54:178,y=layout.portrait()?320:82;
                painter.rect(x-3,y-3,166,96,.05,.05,.07,.96);painter.picture(x,y,160,90,preview_texture.id);
            }
            if(dm_fixture)painter.text(area.x+8,area.y+area.h-6,"合成弹幕类型验收样例",.5,0xaaaaaa,1,true);
            if(!toast.empty()&&now<toast_until){float tx=layout.portrait()?8:158,ty=layout.portrait()?600:193,tw=layout.portrait()?252:484;painter.rect(tx,ty,tw,34,0,0,0,.85);float scale=std::min(.72f,(tw-12)/painter.measure(toast));painter.text(tx+6,ty+24,toast,scale);}
            // Swap supplies synchronization; glFinish here needlessly stalls
            // the CPU after every frame. Capture keeps its explicit fence.
            painter.end();inspect_gl("overlay");
            profile_record(p011_profile::Overlay,profile_at,profile_playing,pos);
            if(!capture_name.empty()&&!dm_builder.busy()){
                if(capture_name=="player-paused"&&!hw.active){
                    // Public automated content only. Compare decoder output
                    // with the GL screenshot without logging any media URL.
                    std::string path=root+"/screenshots/decoder-reference.png";struct stat info;
                    if(lstat(path.c_str(),&info)==-1&&errno==ENOENT){const char*cmd[]={"screenshot-to-file",path.c_str(),"video",nullptr};mpv_command_async(m,3,cmd);}
                }
                save_capture(capture_name,width,height);capture_name.clear();captures++;
            }
            profile_at=SDL_GetPerformanceCounter();pacer.before_swap();presentation.before_swap(hw.active&&loaded&&active&&!pause&&!replacing&&pending_seq==0);SDL_GL_SwapWindow(window);inspect_gl("window_swap");profile_record(p011_profile::Swap,profile_at,profile_playing,pos);if(!hw.active)mpv_render_context_report_swap(render);frames.swap(frame_info.flags);draws++;render_us+=(SDL_GetPerformanceCounter()-render_start)*1000000/SDL_GetPerformanceFrequency();SDL_Delay(2);
            // A paused hardware stream can produce its sole preroll frame
            // before the periodic status packet. The displayed frame itself
            // is the readiness evidence; do not wait for a nonexistent second.
            if(transition.seq&&(loaded||hw.active)&&video_frame&&(frame_info.flags&1)&&!(frame_info.flags&2))complete_switch();
            if(replay.pending&&hw.active&&video_frame&&(frame_info.flags&1)&&!(frame_info.flags&2)){replay.frame();replacing=false;loaded=true;health={};redraw=true;}
            if(seek_reload.pending&&hw.active&&video_frame&&(frame_info.flags&1)&&!(frame_info.flags&2)){seek_reload.frame();replacing=false;loaded=true;health={};toast.clear();redraw=true;}
        }
    }
    save_watch();lease(false);hw.close();
    save("playback-settings.json",settings.json());
    save("gesture-result.json",{{"video_seek_actions",video_seek_actions},{"slide_frames",slide_frames},{"slide_cancels",slide_cancels},{"single_decoder",true}});
    save("story-loop-result.json",{{"requested",replay.requested},{"completed",replay.completed},{"failures",replay.failures},{"pending",replay.pending},{"single_decoder",true}});
    save("hardware-seek-reload.json",{{"requested",seek_reload.requested},{"completed",seek_reload.completed},{"failures",seek_reload.failures},{"pending",seek_reload.pending},{"single_decoder",true}});
    auto packet_stats=packet_decoder.stats();
    J phase_result={{"scope","hardware_active_only"},{"contains_media_data",false},{"async_packets",packet_stats.packets},{"async_danmaku_packets",packet_stats.danmaku_packets},{"async_max_parse_us",packet_stats.max_parse_us},{"async_max_bytes",packet_stats.max_bytes},{"layout_batch_rows",p011_dm::Builder::max_rows},{"layout_budget_us",p011_dm::Builder::budget_us}};profile_fields(phase_result);save("phase-result.json",phase_result);
    save("performance-result.json",{{"submitted_frames",frames.submitted},{"redraw_frames",frames.redrawn},{"repeat_frames",frames.repeated},{"draws",draws},{"idle_draws_skipped",skipped_draws},{"render_microseconds",render_us},{"cpu_seconds",double(std::clock())/CLOCKS_PER_SEC},{"decoder_drops",decoder_drops},{"source_width",source_width},{"source_height",source_height},{"settings_changes",settings_changes}});
    save("player-result.json",{{"protocol_version",2},{"generation",generation},{"loaded",loaded},{"max_position",maxpos},{"draws",draws},{"drops",drops},{"pulse",pulse},{"width",width},{"height",height},{"pause_actions",pauses},{"seek_actions",seeks},{"scrub_actions",scrub_actions},{"final_volume",volume},{"reason",stopping?"stopped":reason},{"elapsed_ms",SDL_GetTicks()-start},{"system_volume_changed",false},{"overlay_toggle_actions",overlay_taps},{"overlay_hidden_frames",hidden},{"overlay_visible_frames",shown},{"quality_switches",quality_switches},{"video_switches",switches},{"rotation_actions",rotations},{"swipe_actions",swipes},{"danmaku_toggle_actions",dm_toggles},{"danmaku_count",danmaku.size()},{"danmaku_frames",dm_frames},{"muted",muted},{"capture_count",captures},{"hardware",hw.audit()},{"gl_errors",gl_faults}});
    return failure?10:0;
}
int main(int argc,char**argv){
    prctl(PR_SET_PDEATHSIG,SIGTERM);const char*owner=getenv("P011_OWNER_PID");if(owner&&getppid()!=atoi(owner))return 90;
    signal(SIGTERM,stop_signal);signal(SIGINT,stop_signal);signal(SIGALRM,stop_signal);signal(SIGPIPE,SIG_IGN);
    if(argc==2&&std::string(argv[1])=="--preflight")return preflight();if(argc!=1)return 2;
    int code=25;try{code=v2_run();}catch(int value){code=value;}catch(...){}
    if(diagnostic_allowed)try{save("player-startup.json",{{"phase",phase},{"exit_code",code},{"mpv_code",last_mpv_error},{"option",failed_option}});}catch(...){}
    return code;
}
