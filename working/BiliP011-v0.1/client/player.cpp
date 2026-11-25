// SPDX-License-Identifier: GPL-3.0-or-later
// P011 SDL2/libmpv player. No URLs, cookies, titles or account data in logs.
#include <SDL.h>
#include <GLES2/gl2.h>
#include <mpv/client.h>
#include <mpv/render_gl.h>
#include <ft2build.h>
#include FT_FREETYPE_H
#include <nlohmann/json.hpp>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <regex>
#include <string>
#include "progress_overlay.hpp"
#include "player_geometry.hpp"
#include "player_surface.hpp"
using J=nlohmann::json;
static volatile sig_atomic_t stopping=0;
static void stop_signal(int){stopping=1;}
static std::string root,session;
static const char *phase="guard",*failed_option="";
static int last_mpv_error=0;
static bool diagnostic_allowed=false;
static constexpr int decode_threads=6;
static unsigned sequence=0;
static void save(const char *name,const J &data) {
    if(root.empty())return;
    std::string path=root+'/'+name,tmp=path+'.'+std::to_string(getpid())+".tmp",body=data.dump()+"\n";
    int fd=open(tmp.c_str(),O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,0600);
    if(fd<0)throw 21;
    ssize_t count=write(fd,body.data(),body.size());int result=close(fd);
    if(count!=ssize_t(body.size())||result||rename(tmp.c_str(),path.c_str()))throw 21;
}
static bool audio_lease_release=false;
static void lease(bool active) {save("lease.json",{{"session",session},{"seq",++sequence},{"active",active&&!audio_lease_release}});}
struct Releaser {~Releaser(){try{lease(false);}catch(...){}}};
static void *get_proc(void*,const char *name){return SDL_GL_GetProcAddress(name);}
static void option(mpv_handle *m,const char *key,const char *value) {int code=mpv_set_option_string(m,key,value);if(code<0){failed_option=key;last_mpv_error=code;throw 22;}}
static void configure(mpv_handle *m) {
    for(auto pair:{std::make_pair("config","no"),{"terminal","no"},{"msg-level","all=no"},{"vo","libmpv"},{"ao","pulse"},{"hwdec","no"},{"idle","yes"},{"keep-open","no"},{"volume","100"},{"volume-max","100"},{"audio-client-name","P011 Bili"},{"network-timeout","10"},{"tls-verify","yes"},{"tls-ca-file","/etc/ssl/certs/ca-certificates.crt"},{"user-agent","wiliwili"},{"referrer","https://www.bilibili.com/"},{"demuxer-max-bytes","8388608"},{"demuxer-readahead-secs","3"},{"cache","yes"},{"osd-level","0"},{"sub-visibility","no"},{"sub-auto","no"},{"audio-file-auto","no"},{"video-margin-ratio-top","0.2208333333"},{"video-margin-ratio-bottom","0.2208333333"},{"video-margin-ratio-left","0.1875"},{"video-margin-ratio-right","0.1875"}})option(m,pair.first,pair.second);
#ifdef P011_ENHANCED_BUILD
    for(const char *key:{"video-margin-ratio-top","video-margin-ratio-bottom","video-margin-ratio-left","video-margin-ratio-right"})option(m,key,"0");
    // A bounded frame pipeline can overlap reference-frame waits across this
    // four-core CPU. Thread count is measured, never unbounded auto detection.
    option(m,"vd-lavc-threads",std::to_string(decode_threads).c_str());
    option(m,"vd-lavc-o","max_pixels=36000000");
    // Permit late decode/output frames to be discarded under overload. This
    // reduces wasted work, but cannot guarantee sync or full source FPS when
    // a stream exceeds decoder throughput. No interpolation is performed.
    option(m,"framedrop","decoder+vo");
#endif
}
static int preflight() {
    // Exercise the actual frozen binary's options and font loader, but never
    // SDL_Init, mpv_initialize, vendor IPC, a URL, an audio device or a window.
    alarm(10);mpv_handle *m=mpv_create();int code=m?0:7;
    if(m){try{configure(m);}catch(int value){code=value;}mpv_destroy(m);}
    FT_Library library=nullptr;FT_Face face=nullptr;
    int init=FT_Init_FreeType(&library);
    int font=init?-1:FT_New_Face(library,"/usr/share/fonts/ttf/SourceHanSansSC-Normal.OTF",0,&face);
    if(face)FT_Done_Face(face);if(library)FT_Done_FreeType(library);
    if(!code&&(init||font))code=24;
    bool overlay=p011_player::progress_overlay_selftest();if(!code&&!overlay)code=26;
    int protocol=1;
#ifdef P011_ENHANCED_BUILD
    protocol=2;
#endif
    std::cout<<J{{"ok",code==0},{"exit_code",code},{"mpv_code",last_mpv_error},{"option",failed_option},{"freetype_init",init},{"font_load",font},{"window_opened",false},{"audio_played",false},{"progress_overlay_selftest",overlay},{"protocol_version",protocol}}.dump()<<std::endl;
    return code;
}
#include "cached_media.hpp"
static bool media(const std::string &url,bool empty=false) {
    if(empty&&url.empty())return true;
    if(!p011_media::cached_path(url).empty()||p011_media::relay_url(url))return true;
    return std::regex_match(url,std::regex("https://(?:[a-zA-Z0-9-]+\\.)*(?:bilivideo\\.com|bilivideo\\.cn|acgvideo\\.com|biliapi\\.net)(?::443)?/[^\\r\\n]*"));
}
struct Glyph {GLuint texture=0;int width=0,height=0,left=0,top=0,advance=0;unsigned used=0;};
class Painter {
    GLuint program=0,buffer=0,white=0;GLint position=-1,uv=-1,color=-1,outline_mode=-1,border_color=-1,rounding=-1;
    FT_Library ft=nullptr;FT_Face face=nullptr;std::map<unsigned,Glyph> glyphs;
    std::map<unsigned,int> advances;unsigned glyph_clock=0;
    const p011_player::Layout *layout=nullptr;
    float transform_x=0,transform_y=0,transform_angle=0,transform_sx=1;
    static GLuint shader(GLenum type,const char *source){GLuint s=glCreateShader(type);glShaderSource(s,1,&source,nullptr);glCompileShader(s);GLint ok=0;glGetShaderiv(s,GL_COMPILE_STATUS,&ok);if(!ok)throw 23;return s;}
public:
    uint64_t glyph_rasterizations=0,glyph_metric_loads=0,glyph_evictions=0,quad_calls=0;
    Painter(){
        const char *vs="attribute vec2 p;attribute vec2 u;uniform vec2 canvas;uniform float origin_y;varying vec2 v;void main(){gl_Position=vec4(p.x*2./canvas.x-1.,1.-(p.y-origin_y)*2./canvas.y,0.,1.);v=u;}";
        const char *fs="precision mediump float;uniform sampler2D t;uniform vec4 c;uniform float o;uniform float b;uniform float image_mode;uniform vec2 k;varying vec2 v;void main(){vec4 s=texture2D(t,v);float a=mix(s.r,s.a,o);if(k.x>0.0){vec2 d=max(abs(v-0.5)-(0.5-k),0.0)/k;a*=1.0-smoothstep(0.91,1.0,length(d));}vec3 rgb=mix(vec3(b),c.rgb,mix(1.0,s.r/max(s.a,0.001),o));gl_FragColor=mix(vec4(rgb,c.a*a),vec4(s.rgb,c.a*s.a),image_mode);}";
        GLuint a=shader(GL_VERTEX_SHADER,vs),b=shader(GL_FRAGMENT_SHADER,fs);program=glCreateProgram();glAttachShader(program,a);glAttachShader(program,b);glLinkProgram(program);glDeleteShader(a);glDeleteShader(b);
        GLint ok=0;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)throw 23;
        position=glGetAttribLocation(program,"p");uv=glGetAttribLocation(program,"u");color=glGetUniformLocation(program,"c");
        outline_mode=glGetUniformLocation(program,"o");border_color=glGetUniformLocation(program,"b");
        rounding=glGetUniformLocation(program,"k");
        glGenBuffers(1,&buffer);glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,24*sizeof(GLfloat),nullptr,GL_DYNAMIC_DRAW);glBindBuffer(GL_ARRAY_BUFFER,0);
        glGenTextures(1,&white);glBindTexture(GL_TEXTURE_2D,white);unsigned char pixel[2]={255,255};
        glTexImage2D(GL_TEXTURE_2D,0,GL_LUMINANCE_ALPHA,1,1,0,GL_LUMINANCE_ALPHA,GL_UNSIGNED_BYTE,pixel);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        if(FT_Init_FreeType(&ft)||FT_New_Face(ft,"/usr/share/fonts/ttf/SourceHanSansSC-Normal.OTF",0,&face))throw 24;
        FT_Set_Pixel_Sizes(face,0,26);
    }
    ~Painter(){for(auto &p:glyphs)glDeleteTextures(1,&p.second.texture);if(face)FT_Done_Face(face);if(ft)FT_Done_FreeType(ft);glDeleteTextures(1,&white);glDeleteBuffers(1,&buffer);glDeleteProgram(program);}
    void begin(int w,int h,GLuint framebuffer=0){glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);glViewport(0,0,w,h);glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);glDisable(GL_DEPTH_TEST);glDisable(GL_STENCIL_TEST);glDisable(GL_SCISSOR_TEST);glDisable(GL_CULL_FACE);glEnable(GL_BLEND);glBlendEquation(GL_FUNC_ADD);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);glUseProgram(program);glActiveTexture(GL_TEXTURE0);glUniform1i(glGetUniformLocation(program,"t"),0);auto s=p011_player::active_surface();glUniform2f(glGetUniformLocation(program,"canvas"),s.width(),s.height());glUniform1f(glGetUniformLocation(program,"origin_y"),s.top());}
    void set_layout(const p011_player::Layout *value){layout=value;}
    void transform(float x=0,float y=0,float degrees=0,float sx=1){transform_x=x;transform_y=y;transform_angle=degrees*3.14159265358979323846/180;transform_sx=sx;}
    void quad(float x,float y,float w,float h,GLuint texture,float r,float g,float b,float a=1){
        quad_calls++;
        GLfloat vertices[]={x,y,0,0,x+w,y,1,0,x,y+h,0,1,x,y+h,0,1,x+w,y,1,0,x+w,y+h,1,1};
        if(transform_angle!=0||transform_sx!=1)for(int i=0;i<6;i++){
            float dx=(vertices[i*4]-transform_x)*transform_sx,dy=vertices[i*4+1]-transform_y;
            vertices[i*4]=transform_x+dx*std::cos(transform_angle)-dy*std::sin(transform_angle);
            vertices[i*4+1]=transform_y+dx*std::sin(transform_angle)+dy*std::cos(transform_angle);
        }
        if(layout)for(int i=0;i<6;i++){auto point=layout->physical({vertices[i*4],vertices[i*4+1]});vertices[i*4]=point.x;vertices[i*4+1]=point.y;}
        glBindTexture(GL_TEXTURE_2D,texture);glUniform4f(color,r,g,b,a);glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferSubData(GL_ARRAY_BUFFER,0,sizeof(vertices),vertices);
        glEnableVertexAttribArray(position);glEnableVertexAttribArray(uv);glVertexAttribPointer(position,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),nullptr);glVertexAttribPointer(uv,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),(void*)(2*sizeof(GLfloat)));glDrawArrays(GL_TRIANGLES,0,6);
    }
    void rect(float x,float y,float w,float h,float r,float g,float b,float a=1){glUniform2f(rounding,0,0);glUniform1f(outline_mode,0);quad(x,y,w,h,white,r,g,b,a);}
    void picture(float x,float y,float w,float h,GLuint texture){glUniform2f(rounding,0,0);glUniform1f(outline_mode,0);glUniform1f(glGetUniformLocation(program,"image_mode"),1);quad(x,y,w,h,texture,1,1,1,1);glUniform1f(glGetUniformLocation(program,"image_mode"),0);}
    void rounded(float x,float y,float w,float h,float r,float g,float b,float a=1,float radius=12){glUniform2f(rounding,radius/w,radius/h);glUniform1f(outline_mode,0);quad(x,y,w,h,white,r,g,b,a);glUniform2f(rounding,0,0);}
    const Glyph &glyph(unsigned cp){
        auto it=glyphs.find(cp);if(it!=glyphs.end()){it->second.used=++glyph_clock;return it->second;}
        // Bound texture memory when many unique public comment glyphs appear.
        if(glyphs.size()>=512){auto old=std::min_element(glyphs.begin(),glyphs.end(),[](const auto&a,const auto&b){return a.second.used<b.second.used;});glDeleteTextures(1,&old->second.texture);glyphs.erase(old);glyph_evictions++;}
        if(FT_Load_Char(face,cp,FT_LOAD_RENDER))throw 24;glyph_rasterizations++;auto s=face->glyph;Glyph g;
        g.width=s->bitmap.width+2;g.height=s->bitmap.rows+2;g.left=s->bitmap_left-1;g.top=s->bitmap_top+1;g.advance=s->advance.x>>6;g.used=++glyph_clock;
        // Cache coverage + one-pixel outline in two texture channels. This
        // draws outlined text once per glyph, not nine GL calls per glyph.
        std::vector<unsigned char>pixels(size_t(g.width)*g.height*2,0);
        for(int y=0;y<int(s->bitmap.rows);y++)for(int x=0;x<int(s->bitmap.width);x++){
            unsigned char coverage=s->bitmap.buffer[y*s->bitmap.pitch+x];int at=((y+1)*g.width+x+1)*2;pixels[at]=coverage;pixels[at+1]=std::max(pixels[at+1],coverage);
            for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){int target=((y+1+dy)*g.width+x+1+dx)*2+1;pixels[target]=std::max(pixels[target],static_cast<unsigned char>(coverage*.8f));}
        }
        glGenTextures(1,&g.texture);glBindTexture(GL_TEXTURE_2D,g.texture);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
        glTexImage2D(GL_TEXTURE_2D,0,GL_LUMINANCE_ALPHA,g.width,g.height,0,GL_LUMINANCE_ALPHA,GL_UNSIGNED_BYTE,pixels.data());
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        return glyphs.emplace(cp,g).first->second;
    }
    void text(float x,float baseline,const std::string &s,float scale=1,int rgb=0xf2faff,float alpha=1,bool outline=false){
        glUniform2f(rounding,0,0);
        float origin=x;float r=((rgb>>16)&255)/255.f,gc=((rgb>>8)&255)/255.f,b=(rgb&255)/255.f;
        float border=(r*.299f+gc*.587f+b*.114f)<.24f?1.f:0.f;
        glUniform1f(outline_mode,outline?1:0);glUniform1f(border_color,border);
        for(size_t i=0;i<s.size();){unsigned char c=s[i++];unsigned cp=c;int more=0;if(c>=0xf0){cp=c&7;more=3;}else if(c>=0xe0){cp=c&15;more=2;}else if(c>=0xc0){cp=c&31;more=1;}while(more--&&i<s.size())cp=(cp<<6)|(s[i++]&63);
            if(cp=='\n'){x=origin;baseline+=28*scale;continue;}
            auto &g=glyph(cp);if(g.width&&g.height){
                float gx=x+g.left*scale,gy=baseline-g.top*scale;
                quad(gx,gy,g.width*scale,g.height*scale,g.texture,r,gc,b,alpha);
            }x+=g.advance*scale;}
    }
    float measure(const std::string &s,float scale=1){float width=0,maxwidth=0;for(size_t i=0;i<s.size();){unsigned char c=s[i++];unsigned cp=c;int more=0;if(c>=0xf0){cp=c&7;more=3;}else if(c>=0xe0){cp=c&15;more=2;}else if(c>=0xc0){cp=c&31;more=1;}while(more--&&i<s.size())cp=(cp<<6)|(s[i++]&63);
        if(cp=='\n'){maxwidth=std::max(maxwidth,width);width=0;continue;}
        auto it=advances.find(cp);if(it==advances.end()){if(advances.size()>=4096)advances.clear();if(FT_Load_Char(face,cp,FT_LOAD_DEFAULT))throw 24;glyph_metric_loads++;it=advances.emplace(cp,face->glyph->advance.x>>6).first;}width+=it->second*scale;}return std::max(width,maxwidth);}
    void end(){glDisableVertexAttribArray(position);glDisableVertexAttribArray(uv);glDisable(GL_BLEND);glBindBuffer(GL_ARRAY_BUFFER,0);glBindTexture(GL_TEXTURE_2D,0);glUseProgram(0);}
};
static std::string clock_text(double value){if(!std::isfinite(value)||value<0)value=0;int s=int(value);char b[40];snprintf(b,sizeof(b),"%d:%02d",s/60,s%60);return b;}
static int run(){
    const char *p=getenv("P011_CLIENT_ROOT"),*id=getenv("P011_AWAKE_SESSION"),*limit=getenv("P011_PLAYER_LIMIT");
    if(!p||!id||!limit)return 19;root=p;session=id;
    if(!std::regex_match(session,std::regex("[a-f0-9]{24}"))||root!="/mnt/data/p011-toolbox/bili-awake/"+session)return 19;
    int seconds=atoi(limit);if(seconds<10||seconds>480)return 19;diagnostic_allowed=true;Releaser release;lease(false);alarm(seconds+8);phase="input";
    std::string input;char ch;while(std::cin.get(ch)){if(input.size()>=32768)return 2;input+=ch;}
    J request=J::parse(input);std::string video=request.value("video",""),audio=request.value("audio","");bool preview=request.value("preview",false);
    if(!media(video)||!media(audio,true))return 3;
    phase="sdl";if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_TIMER))return 4;
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_ES);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,2);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,0);SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);
    phase="window";SDL_Window *window=SDL_CreateWindow("P011 Bili",SDL_WINDOWPOS_UNDEFINED,SDL_WINDOWPOS_UNDEFINED,800,480,SDL_WINDOW_OPENGL|SDL_WINDOW_SHOWN|SDL_WINDOW_FULLSCREEN_DESKTOP|SDL_WINDOW_BORDERLESS|SDL_WINDOW_RESIZABLE);
    if(!window)return 5;phase="gl";SDL_GLContext gl=SDL_GL_CreateContext(window);if(!gl)return 6;SDL_GL_SetSwapInterval(1);
    phase="mpv_create";
    mpv_handle *m=mpv_create();if(!m)return 7;
    // This private libmpv is built without Lua / scripting. load-scripts and
    // ytdl are absent options (-5), not switches that can be set to "no".
    phase="mpv_options";
    configure(m);
    if(!audio.empty()) {mpv_node v={};v.u.string=&audio[0];v.format=MPV_FORMAT_STRING;mpv_node_list list={1,&v,nullptr};mpv_node n={};n.u.list=&list;n.format=MPV_FORMAT_NODE_ARRAY;if(mpv_set_option(m,"audio-files",MPV_FORMAT_NODE,&n)<0)return 11;}
    phase="mpv_initialize";last_mpv_error=mpv_initialize(m);if(last_mpv_error<0)return 8;
    mpv_opengl_init_params init={get_proc,nullptr};mpv_render_param params[]={{MPV_RENDER_PARAM_API_TYPE,(void*)MPV_RENDER_API_TYPE_OPENGL},{MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,&init},{MPV_RENDER_PARAM_INVALID,nullptr}};
    phase="mpv_render";mpv_render_context *render=nullptr;last_mpv_error=mpv_render_context_create(&render,m,params);if(last_mpv_error<0)return 9;
    const char *cmd[]={"loadfile",video.c_str(),nullptr};if(mpv_command_async(m,1,cmd)<0)return 10;
    Uint32 start=SDL_GetTicks(),lastwrite=0,lastadvance=0;double pos=0,duration=0,previous=-1,maxpos=0,volume=100;int width=0,height=0,pause=0,idle=1;
    int draws=0,pauses=0,seeks=0,overlay_taps=0,overlay_hidden_frames=0,overlay_visible_frames=0;
    p011_player::ProgressOverlay overlay;
    int64_t observed_drops=-1;bool loaded=false,finished=false,failure=false,pulse_seen=false;std::string reason="limit";
    {
        phase="painter";Painter painter;phase="playback";
        auto seek=[&](double delta){
            if(!loaded)return;
            double target=std::max(0.,pos+delta);
            if(duration>0)target=std::min(target,std::max(0.,duration-.05));
            std::string value=std::to_string(target);
            const char *c[]={"seek",value.c_str(),"absolute+exact",nullptr};
            if(mpv_command_async(m,2,c)>=0){previous=-1;seeks++;}
        };
        auto touch=[&](float x,float y){
            if(y<106||y>374)return;
            if(x>=146&&x<=654){overlay.tap(SDL_GetTicks());overlay_taps++;return;}
            overlay.reveal(SDL_GetTicks());
            int row=(int(y)-110)/86;
            if(x<146){if(row==0){finished=true;reason="back";}else if(row==1)seek(-15);else if(row==2){volume=std::max(0.,volume-10);mpv_set_property(m,"volume",MPV_FORMAT_DOUBLE,&volume);}}
            else if(x>654){if(row==0){pause=!pause;mpv_set_property(m,"pause",MPV_FORMAT_FLAG,&pause);pauses++;}else if(row==1)seek(15);else if(row==2){volume=std::min(100.,volume+10);mpv_set_property(m,"volume",MPV_FORMAT_DOUBLE,&volume);}}
        };
        while(!finished&&!stopping&&SDL_GetTicks()-start<Uint32(seconds*1000)){
            SDL_Event e;
            while(SDL_PollEvent(&e)){
                if(e.type==SDL_QUIT||(e.type==SDL_KEYDOWN&&e.key.keysym.sym==SDLK_ESCAPE)){finished=true;reason="back";}
                if(e.type==SDL_FINGERDOWN)touch(e.tfinger.x*800,e.tfinger.y*480);
                if(e.type==SDL_MOUSEBUTTONDOWN&&e.button.which!=SDL_TOUCH_MOUSEID){int w=800,h=480;SDL_GetWindowSize(window,&w,&h);if(w&&h)touch(e.button.x*800.f/w,e.button.y*480.f/h);}
            }
            mpv_event *event;
            while((event=mpv_wait_event(m,0))->event_id!=MPV_EVENT_NONE){
                if(event->event_id==MPV_EVENT_FILE_LOADED)loaded=true;
                if(event->event_id==MPV_EVENT_END_FILE){auto end=(mpv_event_end_file*)event->data;failure=end->error<0;finished=true;reason=failure?"error":"eof";}
            }
            Uint32 now=SDL_GetTicks();
            mpv_get_property(m,"pause",MPV_FORMAT_FLAG,&pause);mpv_get_property(m,"core-idle",MPV_FORMAT_FLAG,&idle);
            if(loaded){mpv_get_property(m,"time-pos",MPV_FORMAT_DOUBLE,&pos);mpv_get_property(m,"duration",MPV_FORMAT_DOUBLE,&duration);if(pos>previous+.01||pos<previous-.1){lastadvance=now;previous=pos;}maxpos=std::max(pos,maxpos);}
            bool active=loaded&&!pause&&!idle&&pos>0&&now-lastadvance<2000&&!finished;
            overlay.playback(now,active);
            bool progress_visible=overlay.visible(now);
            if(now-lastwrite>=500){
                char *ao=mpv_get_property_string(m,"current-ao");if(ao&&std::string(ao)=="pulse")pulse_seen=true;mpv_free(ao);
                int64_t count=-1;if(mpv_get_property(m,"frame-drop-count",MPV_FORMAT_INT64,&count)>=0)observed_drops=std::max(observed_drops,count);
                lease(active);save("player-state.json",{{"loaded",loaded},{"position",pos},{"duration",duration},{"paused",pause!=0},{"active",active},{"volume",volume},{"preview",preview},{"pulse_observed",pulse_seen},{"drops",observed_drops},{"progress_visible",progress_visible}});lastwrite=now;
            }
            SDL_GL_GetDrawableSize(window,&width,&height);if(width<=0||height<=0){SDL_Delay(20);continue;}
            glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,width,height);mpv_opengl_fbo fbo={0,width,height,0};int flip=1;
            mpv_render_param rp[]={{MPV_RENDER_PARAM_OPENGL_FBO,&fbo},{MPV_RENDER_PARAM_FLIP_Y,&flip},{MPV_RENDER_PARAM_INVALID,nullptr}};mpv_render_context_render(render,rp);
            painter.begin(width,height);
            painter.rect(0,106,150,268,.035,.055,.078);painter.rect(650,106,150,268,.035,.055,.078);
            for(int i=0;i<3;i++){painter.rect(8,112+i*86,132,78,.085,.14,.19);painter.rect(660,112+i*86,132,78,.085,.14,.19);}
            painter.text(44,161,"返回");painter.text(32,247,"后退15");painter.text(28,333,"音量 −");
            painter.text(696,161,pause?"继续":"暂停");painter.text(684,247,"快进15");painter.text(680,333,"音量 ＋");
            if(progress_visible){
                painter.rect(154,337,492,37,0,0,0,.65);painter.rect(160,368,480,4,.14,.22,.27);
                if(duration>0)painter.rect(160,368,float(480*std::max(0.,std::min(1.,pos/duration))),4,0,.77,.7);
                painter.text(162,359,clock_text(pos)+" / "+clock_text(duration),.62);
                std::string status=preview?"试看 ":"";status+=!loaded?"加载中":pause?"已暂停":idle?"缓冲中":"播放中";
                painter.text(340,359,status,.62);painter.text(565,359,std::to_string(int(volume))+"%",.62);
                overlay_visible_frames++;
            }else overlay_hidden_frames++;
            painter.end();
            SDL_GL_SwapWindow(window);mpv_render_context_report_swap(render);draws++;SDL_Delay(10);
        }
    }
    lease(false);
    // EOF tears down AO/video properties. Keep in-play observations instead
    // of mistaking post-EOF absence for silent playback / missing frame data.
    save("player-result.json",{{"loaded",loaded},{"max_position",maxpos},{"draws",draws},{"drops",observed_drops},{"pulse",pulse_seen},{"width",width},{"height",height},{"pause_actions",pauses},{"seek_actions",seeks},{"final_volume",volume},{"reason",stopping?"stopped":reason},{"elapsed_ms",SDL_GetTicks()-start},{"system_volume_changed",false},{"overlay_toggle_actions",overlay_taps},{"overlay_hidden_frames",overlay_hidden_frames},{"overlay_visible_frames",overlay_visible_frames}});
    mpv_render_context_free(render);mpv_terminate_destroy(m);SDL_GL_DeleteContext(gl);SDL_DestroyWindow(window);SDL_Quit();return failure?10:0;
}
int main(int argc,char **argv){
    prctl(PR_SET_PDEATHSIG,SIGTERM);const char *owner=getenv("P011_OWNER_PID");if(owner&&getppid()!=atoi(owner))return 90;
    signal(SIGTERM,stop_signal);signal(SIGINT,stop_signal);signal(SIGALRM,stop_signal);
    if(argc==2&&std::string(argv[1])=="--preflight")return preflight();
    if(argc!=1)return 2;
    int code=25;try{code=run();}catch(int value){code=value;}catch(...){}
    // Fixed phase/option names and numbers only. No media URL or API text.
    if(diagnostic_allowed)try{save("player-startup.json",{{"phase",phase},{"exit_code",code},{"mpv_code",last_mpv_error},{"option",failed_option}});}catch(...){}
    return code;
}
