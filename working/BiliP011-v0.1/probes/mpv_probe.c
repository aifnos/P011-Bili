/* Finite independent HTTPS playback probe. Uses vendor SDL only, private mpv.
 * Stream URLs arrive through stdin and are never printed. No cookies or login.
 */
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <SDL.h>
#include <GLES2/gl2.h>
#include <mpv/client.h>
#include <mpv/render_gl.h>

static void *get_proc(void *unused, const char *name) { (void)unused;return SDL_GL_GetProcAddress(name); }
static int option(mpv_handle *m,const char *k,const char *v) {
    int rc=mpv_set_option_string(m,k,v);
    if(rc<0)fprintf(stderr,"OPTION_ERROR=%s:%d\n",k,rc);
    return rc;
}
static const char *lease_path=NULL,*lease_session=NULL;
static unsigned lease_seq=0;
static int lease(int active) {
    if(!lease_path)return 0;
    char tmp[512],body[256];
    if(snprintf(tmp,sizeof(tmp),"%s.%d.tmp",lease_path,(int)getpid())>=(int)sizeof(tmp))return -1;
    int len=snprintf(body,sizeof(body),"{\"session\":\"%s\",\"seq\":%u,\"active\":%s}\n",lease_session,++lease_seq,active?"true":"false");
    int fd=open(tmp,O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,0600);
    if(fd<0)return -1;
    ssize_t written=write(fd,body,len);int closed=close(fd);
    if(written!=len||closed||rename(tmp,lease_path))return -1;
    return 0;
}
int main(int argc,char **argv) {
    if(argc==2 && strcmp(argv[1],"--volume-check")==0) {
        // Silent target check: no SDL, no video URL, ao=null, no system mixer.
        alarm(10);mpv_handle *check=mpv_create();if(!check)return 21;
        option(check,"config","no");option(check,"terminal","no");option(check,"vo","null");option(check,"ao","null");option(check,"volume","100");
        int init=mpv_initialize(check);double value=-1;
        int read=init<0?init:mpv_get_property(check,"volume",MPV_FORMAT_DOUBLE,&value);
        printf("SILENT_VOLUME_CHECK init=%d read=%d volume=%.1f AUDIO_PLAYED=0 SYSTEM_VOLUME_UNCHANGED=1\n",init,read,value);
        mpv_terminate_destroy(check);return init==0&&read==0&&value==100?0:22;
    }
    lease_path=getenv("P011_AWAKE_LEASE");lease_session=getenv("P011_AWAKE_SESSION");
    if(lease_path && (!lease_session||strlen(lease_session)!=24||strspn(lease_session,"0123456789abcdef")!=24))return 19;
    if(lease_path) {
        char expected[256];snprintf(expected,sizeof(expected),"/mnt/data/p011-toolbox/bili-awake/%s/lease.json",lease_session);
        if(strcmp(expected,lease_path)||lease(0))return 19;
    }
    const int seconds=lease_path?120:60;
    // Unity gain for normal playback. Safety probes may request a lower value;
    // neither path writes the pen's system volume or saves a mixer setting.
    const char *volume=getenv("P011_PROBE_VOLUME");
    if(!volume)volume="100";
    if(!volume[0]||strlen(volume)>3||strspn(volume,"0123456789")!=strlen(volume)||atoi(volume)>100)return 20;
    alarm(lease_path?155:85);
    char video[16384],audio[16384];
    if(!fgets(video,sizeof(video),stdin)||!fgets(audio,sizeof(audio),stdin))return 2;
    video[strcspn(video,"\r\n")]=0;audio[strcspn(audio,"\r\n")]=0;
    if(strncmp(video,"https://",8)|| (audio[0]&&strncmp(audio,"https://",8)))return 3;
    if(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_TIMER))return 4;
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,2);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,0);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);
    SDL_Window *w=SDL_CreateWindow("P011 finite video probe",SDL_WINDOWPOS_UNDEFINED,SDL_WINDOWPOS_UNDEFINED,800,480,
        SDL_WINDOW_OPENGL|SDL_WINDOW_SHOWN|SDL_WINDOW_FULLSCREEN_DESKTOP|SDL_WINDOW_BORDERLESS|SDL_WINDOW_RESIZABLE);
    if(!w){SDL_Quit();return 5;}
    SDL_GLContext gl=SDL_GL_CreateContext(w);
    if(!gl){SDL_DestroyWindow(w);SDL_Quit();return 6;}
    SDL_GL_SetSwapInterval(1);
    mpv_handle *m=mpv_create();
    if(!m)return 7;
    option(m,"config","no");option(m,"terminal","no");option(m,"msg-level","all=no");
    option(m,"vo","libmpv");option(m,"ao","pulse");option(m,"hwdec","no");
    option(m,"idle","yes");option(m,"keep-open","yes");option(m,"length",lease_path?"120":"60");
    option(m,"volume",volume);option(m,"audio-client-name","P011 Bili finite probe");
    option(m,"network-timeout","10");option(m,"tls-verify","yes");
    option(m,"tls-ca-file","/etc/ssl/certs/ca-certificates.crt");
    option(m,"user-agent","wiliwili");option(m,"referrer","https://www.bilibili.com/");
    option(m,"demuxer-max-bytes","8388608");option(m,"demuxer-readahead-secs","3");
    option(m,"cache","yes");option(m,"osd-level","0");option(m,"sub-visibility","no");
    option(m,"video-margin-ratio-top","0.2208333333");option(m,"video-margin-ratio-bottom","0.2208333333");
    if(audio[0]) {
        mpv_node value={.u.string=audio,.format=MPV_FORMAT_STRING};
        mpv_node_list list={.num=1,.values=&value,.keys=NULL};
        mpv_node node={.u.list=&list,.format=MPV_FORMAT_NODE_ARRAY};
        int ar=mpv_set_option(m,"audio-files",MPV_FORMAT_NODE,&node);
        printf("AUDIO_ATTACHED=%d\n",ar);if(ar<0)return 11;
    }
    int rc=mpv_initialize(m);printf("MPV_INIT=%d\n",rc);fflush(stdout);
    if(rc<0)return 8;
    double actual_volume=-1;
    mpv_get_property(m,"volume",MPV_FORMAT_DOUBLE,&actual_volume);
    printf("PLAYER_VOLUME=%.1f SYSTEM_VOLUME_UNCHANGED=1\n",actual_volume);
    mpv_opengl_init_params init={get_proc,NULL};
    mpv_render_param initparams[]={{MPV_RENDER_PARAM_API_TYPE,MPV_RENDER_API_TYPE_OPENGL},{MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,&init},{0,NULL}};
    mpv_render_context *render=NULL;
    rc=mpv_render_context_create(&render,m,initparams);printf("RENDER_INIT=%d\n",rc);fflush(stdout);
    if(rc<0)return 9;
    const char *command[]={"loadfile",video,NULL};rc=mpv_command_async(m,1,command);
    printf("LOAD_SUBMITTED=%d\n",rc);
    Uint32 start=SDL_GetTicks(),lastlease=0,lastadvance=0;int running=1,loaded=0,draws=0,finalw=0,finalh=0,lastsec=-1;
    int previous_active=-1,paused_once=0;double maxpos=0,previous_pos=-1;
    while(running && SDL_GetTicks()-start<(Uint32)(seconds+20)*1000) {
        SDL_Event event;
        while(SDL_PollEvent(&event)) {
            if(event.type==SDL_QUIT||event.type==SDL_FINGERDOWN||(event.type==SDL_KEYDOWN&&event.key.keysym.sym==SDLK_ESCAPE)) {
                printf("EXIT_EVENT type=%u elapsed_ms=%u\n",event.type,SDL_GetTicks()-start);running=0;
            }
        }
        SDL_GL_GetDrawableSize(w,&finalw,&finalh);
        mpv_event *e;
        while((e=mpv_wait_event(m,0))->event_id!=MPV_EVENT_NONE) {
            if(e->event_id==MPV_EVENT_FILE_LOADED){loaded=1;puts("FILE_LOADED");}
            if(e->event_id==MPV_EVENT_END_FILE){mpv_event_end_file *end=e->data;printf("END_REASON=%d ERROR=%d\n",end->reason,end->error);running=0;}
        }
        if(loaded) {
            double pos=0;
            if(mpv_get_property(m,"time-pos",MPV_FORMAT_DOUBLE,&pos)>=0) {
                if(pos>maxpos)maxpos=pos;
                if(pos>previous_pos+0.01){lastadvance=SDL_GetTicks();previous_pos=pos;}
                if((int)pos!=lastsec){lastsec=(int)pos;printf("POSITION=%.3f\n",pos);fflush(stdout);}
                if(pos>=seconds-0.2)running=0;
                if(lease_path && getenv("P011_PAUSE_TEST") && !paused_once && pos>=10) {
                    int pause=1;mpv_set_property(m,"pause",MPV_FORMAT_FLAG,&pause);paused_once=1;
                    printf("TEST_PAUSE_STARTED\n");
                }
            }
        }
        Uint32 now=SDL_GetTicks();
        if(paused_once==1 && now-lastadvance>=5000) {
            int pause=0;mpv_set_property(m,"pause",MPV_FORMAT_FLAG,&pause);paused_once=2;puts("TEST_PAUSE_ENDED");
        }
        if(lease_path && (now-lastlease>=500 || !running)) {
            int pause=1,idle=1;
            mpv_get_property(m,"pause",MPV_FORMAT_FLAG,&pause);mpv_get_property(m,"core-idle",MPV_FORMAT_FLAG,&idle);
            int active=running && loaded && !pause && !idle && previous_pos>0 && now-lastadvance<2000;
            if(lease(active)){puts("LEASE_WRITE_FAILED");running=0;}
            if(active!=previous_active){printf("LEASE_ACTIVE=%d\n",active);fflush(stdout);previous_active=active;}
            lastlease=now;
        }
        glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,finalw,finalh);
        mpv_opengl_fbo fbo={0,finalw,finalh,0};int flip=1;
        mpv_render_param params[]={{MPV_RENDER_PARAM_OPENGL_FBO,&fbo},{MPV_RENDER_PARAM_FLIP_Y,&flip},{0,NULL}};
        mpv_render_context_render(render,params);SDL_GL_SwapWindow(w);mpv_render_context_report_swap(render);draws++;
        SDL_Delay(10);
    }
    if(lease(0))puts("LEASE_RELEASE_WRITE_FAILED");
    int64_t drops=-1;mpv_get_property(m,"frame-drop-count",MPV_FORMAT_INT64,&drops);
    char *ao=mpv_get_property_string(m,"current-ao");
    printf("RESULT loaded=%d maxpos=%.3f draws=%d drops=%lld ao=%s drawable=%dx%d\n",loaded,maxpos,draws,(long long)drops,ao?ao:"none",finalw,finalh);
    int audio_ok=ao && strcmp(ao,"pulse")==0;
    mpv_free(ao);mpv_render_context_free(render);mpv_terminate_destroy(m);
    SDL_GL_DeleteContext(gl);SDL_DestroyWindow(w);SDL_Quit();puts("OWN_WINDOW_CLOSED");
    return loaded&&maxpos>=3&&audio_ok?0:10;
}
