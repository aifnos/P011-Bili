// SPDX-License-Identifier: GPL-3.0-or-later
// Separate executable: vendor GStreamer/libav and private mpv/FFmpeg never
// share a symbol namespace. Video and audio use ONE Gst pipeline/clock.
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <nlohmann/json.hpp>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <dirent.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <fstream>
#include <regex>
#include <string>
#include "hardware_protocol.hpp"
#include "cached_media.hpp"
#include "hardware_pack.hpp"
#include "hardware_output.hpp"
#include "hardware_allocation.hpp"
#include "h264_access_unit.hpp"
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
#include "../probes/omx_cache_bridge.h"
#include <dlfcn.h>
#endif
#ifdef P011_BUNDLED_OUTPUT_CACHE
#include "hardware_cache_gate.hpp"
#endif
using J=nlohmann::json;
static volatile sig_atomic_t stopping=0;
static void stop(int){stopping=1;}
static bool output(const J&v){std::string s=v.dump()+"\n";return write(4,s.data(),s.size())==ssize_t(s.size());}
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
static J cache_snapshot(){
    auto s=p011_cache_snapshot();
    return {{"cache_changed_allocations",s.changed_allocations},{"cache_control_allocations",s.control_allocations},
            {"cache_forwarded_allocations",s.forwarded_allocations},{"cache_registered",s.registered},
            {"cache_forgotten",s.forgotten},{"cache_active",s.active},{"cache_read_begin",s.read_begin},
            {"cache_read_end",s.read_end},{"cache_sync_errors",s.sync_errors},
            {"cache_ownership_errors",s.ownership_errors},{"cache_sync_ns",s.sync_ns},
            {"cache_fallback_registered",s.fallback_registered},{"cache_fallback_forgotten",s.fallback_forgotten},
            {"cache_fallback_active",s.fallback_active},{"cache_fallback_read_begin",s.fallback_read_begin},
            {"cache_fallback_read_end",s.fallback_read_end}};
}
#endif
#ifdef P011_OUTPUT_CACHE_PROBE
static bool cache_root_valid(){
    const char*root=getenv("P011_CACHE_PROBE_ROOT"),*owner=getenv("P011_SEEK_PROBE_ROOT"),*plugin=getenv("GST_PLUGIN_PATH_1_0");
    return root&&owner&&plugin&&!strcmp(root,owner)&&!strcmp(root,plugin)&&
        std::regex_match(root,std::regex("/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}"));
}
#endif
static bool media(const std::string&s){return p011_media::relay_url(s)||!p011_media::cached_path(s).empty()||(s.size()<=16384&&std::regex_match(s,std::regex("https://(?:[a-zA-Z0-9-]+\\.)*(?:bilivideo\\.com|bilivideo\\.cn|acgvideo\\.com|biliapi\\.net)(?::443)?/[^\\r\\n]+")));}
static double seconds(GstClockTime n){return GST_CLOCK_TIME_IS_VALID(n)?double(n)/GST_SECOND:0.;}
static bool hw_library(){std::ifstream f("/proc/self/maps");std::string s;while(std::getline(f,s))if(s.find("libomx_avcdec_hw_sprd.so")!=s.npos)return true;return false;}
static bool vsp(){DIR*d=opendir("/proc/self/fd");if(!d)return false;bool found=false;while(auto*e=readdir(d)){char b[128];std::string p=std::string("/proc/self/fd/")+e->d_name;ssize_t n=readlink(p.c_str(),b,sizeof(b)-1);if(n>0){b[n]=0;if(std::string(b)=="/dev/sprd_vsp")found=true;}}closedir(d);return found;}
static bool pull_mode(GstElement*pipe,const char*name){
    auto*element=gst_bin_get_by_name(GST_BIN(pipe),name);if(!element)return false;
    auto*pad=gst_element_get_static_pad(element,"sink");bool pull=pad&&GST_PAD_MODE(pad)==GST_PAD_MODE_PULL;
    if(pad)gst_object_unref(pad);gst_object_unref(element);return pull;
}
static bool bundled_omx_path(GstElement*decoder){
#ifdef P011_BUNDLED_OMX
    // Only an immutable sibling of THIS executable may enable production
    // fused copy. No path comes from the media request or arbitrary env.
    char path[4096];ssize_t n=readlink("/proc/self/exe",path,sizeof(path)-1);
    if(n<=0||n==ssize_t(sizeof(path)-1))return false;path[n]=0;
    std::string expected=path;auto slash=expected.rfind('/');if(slash==expected.npos)return false;
    expected.resize(slash);slash=expected.rfind('/');if(slash==expected.npos)return false;
    expected.resize(slash);expected+="/lib/gst/libgstomx.so";
    struct stat info{};if(lstat(expected.c_str(),&info)||!S_ISREG(info.st_mode)||info.st_uid!=getuid())return false;
    auto*factory=gst_element_get_factory(decoder);
    auto*plugin=factory?gst_plugin_feature_get_plugin(GST_PLUGIN_FEATURE(factory)):nullptr;
    const char*filename=plugin?gst_plugin_get_filename(plugin):nullptr;
    const bool ok=filename&&expected==filename;
    if(plugin)gst_object_unref(plugin);return ok;
#else
    (void)decoder;return false;
#endif
}
static void private_profile(GstElement*decoder,J&status){
    const char*directory=getenv("GST_PLUGIN_PATH_1_0");
    auto*factory=gst_element_get_factory(decoder);
    auto*plugin=factory?gst_plugin_feature_get_plugin(GST_PLUGIN_FEATURE(factory)):nullptr;
    const char*filename=plugin?gst_plugin_get_filename(plugin):nullptr;
    status["omx_private_plugin"]=directory&&filename&&std::string(filename)==std::string(directory)+"/libgstomx.so";
    if(plugin)gst_object_unref(plugin);
    auto*property=g_object_class_find_property(G_OBJECT_GET_CLASS(decoder),"p011-probe-profile");
    if(!property||G_PARAM_SPEC_VALUE_TYPE(property)!=GST_TYPE_STRUCTURE)return;
    GstStructure*profile=nullptr;g_object_get(decoder,"p011-probe-profile",&profile,nullptr);
    if(!profile)return;
    // Exact numerical allowlist. Factory plugins have no such property.
    for(const char*group:{"loop","acquire","match","fill","copy","allocate","push","release"})
        for(const char*field:{"count","wall_ns","cpu_ns"}){
            std::string key=std::string(group)+"_"+field;guint64 value=0;
            if(gst_structure_get_uint64(profile,key.c_str(),&value))status["omx_profile_"+key]=value;
        }
    guint64 errors=0;if(gst_structure_get_uint64(profile,"clock_errors",&errors))status["omx_profile_clock_errors"]=errors;
    gst_structure_free(profile);
}
struct Pipeline {
    GstElement*pipe=nullptr,*sink=nullptr,*audio=nullptr,*vol=nullptr,*decoder=nullptr,*video_input=nullptr,*video_network=nullptr,*audio_network=nullptr,*audio_input=nullptr;GstBus*bus=nullptr;
    ~Pipeline(){if(pipe)gst_element_set_state(pipe,GST_STATE_NULL);for(auto*p:{sink,audio,vol,decoder,video_input,video_network,audio_network,audio_input})if(p)gst_object_unref(p);if(bus)gst_object_unref(bus);if(pipe)gst_object_unref(pipe);}
};
struct NetworkEnd {
    std::atomic<bool> complete{false};
    static GstPadProbeReturn probe(GstPad*,GstPadProbeInfo*info,gpointer data){
        auto&s=*static_cast<NetworkEnd*>(data);auto*e=GST_PAD_PROBE_INFO_EVENT(info);if(!e)return GST_PAD_PROBE_OK;
        auto t=GST_EVENT_TYPE(e);if(t==GST_EVENT_EOS)s.complete.store(true);
        else if(t==GST_EVENT_STREAM_START||t==GST_EVENT_SEGMENT||t==GST_EVENT_FLUSH_START)s.complete.store(false);
        return GST_PAD_PROBE_OK;
    }
    void attach(GstElement*pipe,const char*name){
        auto*src=gst_bin_get_by_name(GST_BIN(pipe),name);auto*pad=src?gst_element_get_static_pad(src,"src"):nullptr;
        if(src)gst_object_unref(src);if(!pad)throw 42;
        gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM|GST_PAD_PROBE_TYPE_EVENT_FLUSH),probe,this,nullptr);gst_object_unref(pad);
    }
};
struct StreamTrace {
    std::atomic<unsigned>segments{0},flush_start{0},flush_stop{0},buffers{0},seq{0};
    std::atomic<int64_t>start{-1},time{-1},pts{-1};
    static GstPadProbeReturn probe(GstPad*,GstPadProbeInfo*info,gpointer data){
        auto&t=*static_cast<StreamTrace*>(data);
        if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER){
            auto*b=GST_PAD_PROBE_INFO_BUFFER(info);if(b&&GST_CLOCK_TIME_IS_VALID(GST_BUFFER_PTS(b)))t.pts.store(GST_BUFFER_PTS(b));t.buffers.fetch_add(1);
        }
        if(GST_PAD_PROBE_INFO_TYPE(info)&(GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM|GST_PAD_PROBE_TYPE_EVENT_FLUSH)){
            auto*e=GST_PAD_PROBE_INFO_EVENT(info);if(!e)return GST_PAD_PROBE_OK;
            if(GST_EVENT_TYPE(e)==GST_EVENT_FLUSH_START)t.flush_start.fetch_add(1);
            if(GST_EVENT_TYPE(e)==GST_EVENT_FLUSH_STOP)t.flush_stop.fetch_add(1);
            if(GST_EVENT_TYPE(e)==GST_EVENT_SEGMENT){
                const GstSegment*s=nullptr;gst_event_parse_segment(e,&s);
                if(s&&s->format==GST_FORMAT_TIME){t.start.store(s->start);t.time.store(s->time);t.seq.store(gst_event_get_seqnum(e));t.segments.fetch_add(1);}
            }
        }
        return GST_PAD_PROBE_OK;
    }
    void attach(GstElement*sink){
        auto*pad=sink?gst_element_get_static_pad(sink,"sink"):nullptr;if(!pad)throw 42;
        gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM|GST_PAD_PROBE_TYPE_EVENT_FLUSH),probe,this,nullptr);gst_object_unref(pad);
    }
    void snapshot(J&v,const std::string&prefix)const{
        v[prefix+"segments"]=segments.load();v[prefix+"flush_start"]=flush_start.load();v[prefix+"flush_stop"]=flush_stop.load();
        v[prefix+"buffers"]=buffers.load();v[prefix+"segment_seq"]=seq.load();
        v[prefix+"segment_start"]=double(start.load())/GST_SECOND;v[prefix+"segment_time"]=double(time.load())/GST_SECOND;
        v[prefix+"buffer_pts"]=double(pts.load())/GST_SECOND;
    }
};
struct EncodedTrace {
    std::atomic<unsigned>annexb{0},unsupported{0},invalid{0},reference{0},disposable{0},metadata{0},skipped{0};
    std::atomic<bool>aligned_annexb{false},nonref_allowed{false};
    std::atomic<unsigned>selected_period{0};
    std::atomic<bool>cached_output_ready{false};
    bool nonref_requested=false,diagnostic_nonref=false;
    // CAPS and BUFFER callbacks share the serialized input-pad thread.
    int caps_width=0,caps_height=0,caps_num=0,caps_den=0;
    p011_hw::NonReferencePolicy nonref_policy;
    void select_production_policy(){
        if(diagnostic_nonref)return;
        const bool cached=cached_output_ready.load()&&caps_width==1920&&caps_height==1080;
        const unsigned period=p011_hw::production_nonref_period(caps_num,caps_den,cached);
        if(nonref_policy.keep_every!=period){nonref_policy.keep_every=period;nonref_policy.reset();}
        selected_period.store(period);
    }
    static GstPadProbeReturn probe(GstPad*,GstPadProbeInfo*info,gpointer data){
        auto&t=*static_cast<EncodedTrace*>(data);
        if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM){
            auto*event=GST_PAD_PROBE_INFO_EVENT(info);
            if(event&&GST_EVENT_TYPE(event)==GST_EVENT_CAPS){
                GstCaps*caps=nullptr;gst_event_parse_caps(event,&caps);
                auto*s=caps&&gst_caps_get_size(caps)==1?gst_caps_get_structure(caps,0):nullptr;
                const char*format=s?gst_structure_get_string(s,"stream-format"):nullptr;
                const char*alignment=s?gst_structure_get_string(s,"alignment"):nullptr;
                t.aligned_annexb.store(format&&alignment&&!strcmp(format,"byte-stream")&&!strcmp(alignment,"au"));
                int width=0,height=0,num=0,den=0;
                if(s){gst_structure_get_int(s,"width",&width);gst_structure_get_int(s,"height",&height);gst_structure_get_fraction(s,"framerate",&num,&den);}
                t.caps_width=width;t.caps_height=height;t.caps_num=num;t.caps_den=den;
                t.cached_output_ready.store(false);t.select_production_policy();
                t.selected_period.store(t.nonref_policy.keep_every);
                t.nonref_allowed.store(t.aligned_annexb.load()&&p011_hw::nonref_eligible(t.nonref_requested,width,height,num,den));
                t.nonref_policy.reset();
            }
        }
        if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER){
            t.select_production_policy();
            if(!t.aligned_annexb.load()){t.unsupported++;return GST_PAD_PROBE_OK;}
            auto*buffer=GST_PAD_PROBE_INFO_BUFFER(info);GstMapInfo map=GST_MAP_INFO_INIT;
            if(!buffer||!gst_buffer_map(buffer,&map,GST_MAP_READ)){t.invalid++;return GST_PAD_PROBE_OK;}
            const auto au=p011_hw::inspect_annexb(map.data,map.size);gst_buffer_unmap(buffer,&map);
            t.annexb++;if(!au.valid)t.invalid++;else{
                t.reference+=au.reference;t.disposable+=au.discardable;t.metadata+=au.metadata;
                // Keep every reference,
                // IDR, parameter set, SEI, unknown and malformed access unit.
                // The original timestamps, clock, latency and QoS stay intact.
                if(t.nonref_policy.drop(au,t.nonref_allowed.load())){
                    t.skipped++;return GST_PAD_PROBE_DROP;
                }
            }
        }
        return GST_PAD_PROBE_OK;
    }
    void attach(GstElement*decoder){
        auto*pad=gst_element_get_static_pad(decoder,"sink");if(!pad)throw 42;
        auto id=gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM),probe,this,nullptr);
        gst_object_unref(pad);if(!id)throw 42;
    }
    void snapshot(J&v)const{
        v.update({{"encoded_annexb",annexb.load()},{"encoded_unsupported",unsupported.load()},
                  {"encoded_invalid",invalid.load()},{"encoded_reference",reference.load()},
                  {"encoded_disposable",disposable.load()},{"encoded_metadata",metadata.load()},
                  {"encoded_nonref_skipped",skipped.load()},{"high_fps_compat",nonref_allowed.load()},
                  {"nonref_probe_active",diagnostic_nonref&&nonref_allowed.load()},
                  {"cached_retention_active",!diagnostic_nonref&&nonref_allowed.load()&&cached_output_ready.load()&&selected_period.load()==2},
                  {"nonref_keep_every",selected_period.load()}});
    }
};
static void source(GstElement*pipe,const char*name,const std::string&url){auto*s=gst_bin_get_by_name(GST_BIN(pipe),name);if(!s)throw 43;auto path=p011_media::cached_path(url);if(!path.empty())g_object_set(s,"location",path.c_str(),nullptr);else{auto*h=gst_structure_new("headers","Referer",G_TYPE_STRING,"https://www.bilibili.com/",nullptr);g_object_set(s,"location",url.c_str(),"extra-headers",h,nullptr);gst_structure_free(h);}gst_object_unref(s);}
static J safe_error(GstElement*pipe,GstMessage*message,bool ready,bool paused,bool seeking){
    GError*error=nullptr;gchar*debug=nullptr;gst_message_parse_error(message,&error,&debug);
    // Numeric roles only. GStreamer error/debug text can contain signed URLs;
    // neither arbitrary object paths nor error strings leave this worker.
    int role=0,index=0;for(const char*name:{"vs","as","vd","ad","dec","frames","audio"}){
        ++index;auto*object=gst_bin_get_by_name(GST_BIN(pipe),name);
        if(object&&GST_MESSAGE_SRC(message)==GST_OBJECT(object))role=index;
        if(object)gst_object_unref(object);
    }
    int domain=error?(error->domain==GST_CORE_ERROR?1:error->domain==GST_LIBRARY_ERROR?2:
                     error->domain==GST_RESOURCE_ERROR?3:error->domain==GST_STREAM_ERROR?4:0):0;
    J result={{"error",45},{"gst_code",error?error->code:0},{"gst_domain_kind",domain},
              {"gst_source_role",role},{"gst_phase",seeking?3:!ready?0:paused?2:1}};
    const char*text=error&&error->message?error->message:"";
    for(auto item:{std::make_pair("gst_not_linked","not-linked"),std::make_pair("gst_not_negotiated","not-negotiated"),
                  std::make_pair("gst_range","range"),std::make_pair("gst_seek","seek"),
                  std::make_pair("gst_timeout","timed out"),std::make_pair("gst_stream_error","Internal data stream error")})
        result[item.first]=bool(strstr(text,item.second)||(debug&&strstr(debug,item.second)));
    if(error)g_error_free(error);g_free(debug);return result;
}
static int run(){
    struct stat st{};if(fstat(3,&st)||st.st_size!=sizeof(p011_hw::Shared))return 40;
    auto*shared=static_cast<p011_hw::Shared*>(mmap(nullptr,sizeof(p011_hw::Shared),PROT_READ|PROT_WRITE,MAP_SHARED,3,0));
    if(shared==MAP_FAILED||shared->signature!=p011_hw::magic||shared->revision!=p011_hw::version)return 40;
    std::string input;char ch;while(read(0,&ch,1)==1&&ch!='\n'){if(input.size()>=32768)return 41;input+=ch;}
    J request=J::parse(input);std::string video=request.value("video",""),audio=request.value("audio","");
    int w=request.value("width",0),h=request.value("height",0),limit=request.value("limit",0);
    const double rate=request.value("rate",1.);
    if(!std::isfinite(rate)||rate<.5||rate>2)return 41;
    if(!media(video)||!media(audio)||!p011_hw::supported(7,w,h,true)||limit<10||limit>480)return 41;
    const bool fused_probe=request.value("fused_half_probe",false);
    bool fused_half=fused_probe;
    const char*probe_root=getenv("P011_SEEK_PROBE_ROOT"),*plugin_root=getenv("GST_PLUGIN_PATH_1_0");
    if(fused_probe&&(!probe_root||!plugin_root||std::string(probe_root)!=plugin_root))return 41;
#ifdef P011_OUTPUT_CACHE_PROBE
    const std::string cache_mode=request.value("output_cache_mode","");
    const char*cache_env=getenv("P011_CACHE_PROBE_MODE");
    if(!cache_root_valid()||!cache_env||cache_mode!=cache_env||(cache_mode!="cached"&&cache_mode!="uncached")||
       !fused_probe||!request.value("private_omx_probe",false)||!request.value("muted",false)||limit>40||
       w!=1920||h!=1080||request.value("nonref_probe",false)||request.value("high_fps_compat",false))return 41;
#endif
    const bool throughput_probe=request.value("throughput_probe",false);
    // Explicit muted, finite, private-only maximum-throughput measurement.
    // Never allow the ordinary player or a frame-skipping probe to select it.
    if(throughput_probe&&(!probe_root||!plugin_root||std::string(probe_root)!=plugin_root||
        !request.value("private_omx_probe",false)||!request.value("muted",false)||limit>40||
        request.value("nonref_probe",false)||request.value("high_fps_compat",false)))return 41;
#ifdef P011_BUNDLED_OUTPUT_CACHE
    if(p011_hw::cache_bundle_plugin().empty()||fused_probe||throughput_probe||request.value("private_omx_probe",false))return 41;
    const bool cache_vendor_verified=p011_hw::cache_vendor_verified();
    if(!p011_cache_configure_bundle(cache_vendor_verified))return 56;
#endif
    alarm(limit+5);gst_init(nullptr,nullptr);
    // Native YUV: one bounded panel-size copy, no CPU RGBA conversion/FBO.
    int downsample=std::max(w,h)>960?2:1;
    int ow=(w/downsample)/2*2,oh=(h/downsample)/2*2;
    // GStreamer 1.14 queue2 can expose byte-range pull scheduling using a
    // bounded RAM ring. This lets qtdemux own indexed seeking instead of
    // relying on the HTTP push-seek path. No tempfile/full-file disk cache.
    // Video 8 MiB + audio 2 MiB; queued ahead <=4 MiB + 1 MiB respectively.
    std::string chain="souphttpsrc name=vs ssl-strict=true user-agent=wiliwili timeout=8 ! queue2 name=vnet ring-buffer-max-size=8388608 max-size-bytes=4194304 max-size-buffers=0 max-size-time=0 use-buffering=false ! qtdemux name=vd vd.video_0 ! queue name=vin max-size-buffers=8 max-size-bytes=4194304 max-size-time=2000000000 ! h264parse ! omxh264dec name=dec ! queue max-size-buffers=3 max-size-bytes=0 max-size-time=0 ! appsink name=frames caps=\"video/x-raw,format=NV12\" sync=true qos=true max-lateness=40000000 max-buffers=2 drop=true enable-last-sample=false "
        "souphttpsrc name=as ssl-strict=true user-agent=wiliwili timeout=8 ! queue2 name=anet ring-buffer-max-size=2097152 max-size-bytes=1048576 max-size-buffers=0 max-size-time=0 use-buffering=false ! qtdemux name=ad ad.audio_0 ! queue name=ain max-size-buffers=0 max-size-bytes=1048576 max-size-time=2000000000 ! aacparse ! avdec_aac ! audioconvert ! audioresample ! volume name=vol ! pulsesink name=audio sync=true";
    // Keep the verified 1x path unchanged. Older device GStreamer supports
    // segment-rate scaletempo, not the newer 1.26 mode property.
    if(rate!=1.){auto at=chain.find(" ! volume name=vol");chain.insert(at," ! scaletempo ! audioconvert ! audioresample");}
    // Declared before Pipeline: callbacks remain alive until its NULL state
    // Replace only the fixed source declaration, never interpolate a URL or
    // pathname into gst_parse_launch. Source locations are assigned below.
    for(auto pair:{std::make_pair("vs",video),std::make_pair("as",audio)})if(!p011_media::cached_path(pair.second).empty()){
        std::string old=std::string("souphttpsrc name=")+pair.first+" ssl-strict=true user-agent=wiliwili timeout=8";
        size_t at=chain.find(old);if(at==chain.npos)return 43;chain.replace(at,old.size(),std::string("filesrc name=")+pair.first);
    }
    // Declared before Pipeline: callbacks remain alive until its NULL state
    // has joined every streaming thread during normal/error teardown.
    std::atomic<unsigned>decoded{0},encoded{0};StreamTrace video_trace,audio_trace;p011_hw::VideoAllocation allocation;EncodedTrace encoded_trace;NetworkEnd video_download,audio_download;
    encoded_trace.diagnostic_nonref=request.value("nonref_probe",false)&&getenv("P011_SEEK_PROBE_ROOT");
    encoded_trace.nonref_requested=encoded_trace.diagnostic_nonref||request.value("high_fps_compat",false);
    unsigned keep_every=request.value("nonref_keep_every",0u);
    if(keep_every!=0&&keep_every!=2&&keep_every!=3)return 41;
    encoded_trace.nonref_policy.keep_every=encoded_trace.diagnostic_nonref?keep_every:3;
    Pipeline p;GError*err=nullptr;p.pipe=gst_parse_launch(chain.c_str(),&err);if(err){g_error_free(err);throw 42;}if(!p.pipe)throw 42;
    p.sink=gst_bin_get_by_name(GST_BIN(p.pipe),"frames");p.audio=gst_bin_get_by_name(GST_BIN(p.pipe),"audio");p.vol=gst_bin_get_by_name(GST_BIN(p.pipe),"vol");p.decoder=gst_bin_get_by_name(GST_BIN(p.pipe),"dec");p.bus=gst_element_get_bus(p.pipe);
    p.video_input=gst_bin_get_by_name(GST_BIN(p.pipe),"vin");p.video_network=gst_bin_get_by_name(GST_BIN(p.pipe),"vnet");
    p.audio_network=gst_bin_get_by_name(GST_BIN(p.pipe),"anet");
    p.audio_input=gst_bin_get_by_name(GST_BIN(p.pipe),"ain");
    video_download.attach(p.pipe,"vs");audio_download.attach(p.pipe,"as");
    if(!p.video_input||!p.video_network)throw 42;
    bool diagnostic_decoder_qos_property=false;
    if(throughput_probe){
        // GstVideoDecoder's qos property was added in 1.18; this device uses
        // 1.14.2. With sink QoS disabled no late-frame events enter this new
        // video branch. Disable/read back the decoder property if available,
        // but do not reject an otherwise valid 1.14 diagnostic pipeline.
        diagnostic_decoder_qos_property=g_object_class_find_property(G_OBJECT_GET_CLASS(p.decoder),"qos")!=nullptr;
        gboolean decoder_qos=FALSE;
        if(diagnostic_decoder_qos_property){
            g_object_set(p.decoder,"qos",FALSE,nullptr);
            g_object_get(p.decoder,"qos",&decoder_qos,nullptr);
        }
        g_object_set(p.sink,"sync",FALSE,"qos",FALSE,"max-lateness",gint64(-1),"drop",FALSE,nullptr);
        gboolean sink_sync=TRUE,sink_qos=TRUE,sink_drop=TRUE;gint64 lateness=0;
        g_object_get(p.sink,"sync",&sink_sync,"qos",&sink_qos,"max-lateness",&lateness,"drop",&sink_drop,nullptr);
        if(decoder_qos||sink_sync||sink_qos||sink_drop||lateness!=-1)throw 41;
    }
    auto*half_property=g_object_class_find_property(G_OBJECT_GET_CLASS(p.decoder),"p011-fused-half");
    gboolean half_capable=FALSE;
    if(half_property&&G_PARAM_SPEC_VALUE_TYPE(half_property)==G_TYPE_BOOLEAN)
        g_object_get(p.decoder,"p011-fused-half",&half_capable,nullptr);
    if(half_capable&&!fused_probe&&bundled_omx_path(p.decoder))fused_half=true;
    if(bool(half_capable)!=fused_half)throw 41; // Never enable an unverified plugin.
    video_trace.attach(p.sink);audio_trace.attach(p.audio);allocation.attach(p.sink);encoded_trace.attach(p.decoder);
    // A common reservoir accommodates OMX reordering/processing on BOTH
    // sinks, rather than delaying only the picture or disabling QoS.
    gst_pipeline_set_latency(GST_PIPELINE(p.pipe),200*GST_MSECOND);
    for(auto entry:{std::make_pair("src",&decoded),std::make_pair("sink",&encoded)}){
        auto*pad=gst_element_get_static_pad(p.decoder,entry.first);if(!pad)throw 42;
        gst_pad_add_probe(pad,GST_PAD_PROBE_TYPE_BUFFER,[](GstPad*,GstPadProbeInfo*,gpointer data)->GstPadProbeReturn{static_cast<std::atomic<unsigned>*>(data)->fetch_add(1);return GST_PAD_PROBE_OK;},entry.second,nullptr);gst_object_unref(pad);
    }
    const bool cached_input=!p011_media::cached_path(video).empty()||p011_media::relay_url(video),has_audio=!audio.empty();
    source(p.pipe,"vs",video);source(p.pipe,"as",audio);video.clear();audio.clear();request.erase("video");request.erase("audio");
    bool paused=request.value("paused",false),muted=request.value("muted",false),ready=false,seeking=false,ended=false;
    double volume=std::clamp(request.value("volume",100.)/100.,0.,1.),target=std::max(0.,request.value("start",0.)),pts=0,pos=0,duration=0,source_fps=0;
    g_object_set(p.vol,"volume",volume,"mute",gboolean(muted),nullptr);
    if(gst_element_set_state(p.pipe,GST_STATE_PAUSED)==GST_STATE_CHANGE_FAILURE)throw 43;
    fcntl(0,F_SETFL,fcntl(0,F_GETFL)|O_NONBLOCK);input.clear();uint32_t serial=0;uint64_t delivered=0,shared_drop=0,sink_drop=0,decoder_drop=0,copy_us=0,map_us=0,pull_us=0;bool hardware=false,device=false;
    uint64_t video_meta_frames=0,omx_memory_frames=0,system_memory_frames=0,other_memory_frames=0;
    uint64_t fused_half_frames=0;int output_width=0,output_height=0;
    int mapped_stride_y=0;size_t mapped_offset_uv=0,mapped_bytes=0;
    auto boot=g_get_monotonic_time(),last_status=boot;bool startup_seek=target>.01||rate!=1.;double cpu0=double(clock())/CLOCKS_PER_SEC;auto cpu_at=boot;
    unsigned seek_requests=0;
    auto seek=[&](double to){
        to=std::max(0.,std::min(to,duration>0?duration-.05:to));auto began=g_get_monotonic_time();
        auto*event=gst_event_new_seek(rate,GST_FORMAT_TIME,GstSeekFlags(GST_SEEK_FLAG_FLUSH|GST_SEEK_FLAG_ACCURATE),GST_SEEK_TYPE_SET,gint64(to*GST_SECOND),GST_SEEK_TYPE_NONE,GST_CLOCK_TIME_NONE);
        auto seq=gst_event_get_seqnum(event);
        output({{"seek_event",1},{"seek_requests",++seek_requests},{"seek_target",to},{"seek_paused",paused},{"seek_seq",seq},
                {"seek_before_video_buffers",video_trace.buffers.load()},{"seek_before_audio_buffers",audio_trace.buffers.load()}});
        for(auto&f:shared->frames)p011_hw::take(f.state,p011_hw::Ready,p011_hw::Free);
        bool accepted=gst_element_send_event(p.pipe,event);
        output({{"seek_event",2},{"seek_requests",seek_requests},{"seek_target",to},{"seek_accepted",accepted},{"seek_call_us",g_get_monotonic_time()-began}});
        if(!accepted)return false;seeking=true;return true;
    };
    while(!stopping&&!ended&&g_get_monotonic_time()-boot<int64_t(limit)*G_USEC_PER_SEC){
        char bytes[8192];ssize_t n;while((n=read(0,bytes,sizeof(bytes)))>0){input.append(bytes,n);if(input.size()>32768)throw 44;}if(n==0)break;
        size_t line;while((line=input.find('\n'))!=input.npos){J cmd=J::parse(input.substr(0,line));input.erase(0,line+1);std::string op=cmd.value("op","");
            if(op=="stop"){stopping=1;break;}
            if(op=="pause"){paused=cmd.value("value",false);if(ready)gst_element_set_state(p.pipe,paused?GST_STATE_PAUSED:GST_STATE_PLAYING);}
            if(op=="volume"){volume=std::clamp(cmd.value("value",100.)/100.,0.,1.);g_object_set(p.vol,"volume",volume,nullptr);}
            if(op=="seek"&&ready){if(!seek(cmd.value("value",0.)))output({{"seek_failed",true}});}
        }
        while(auto*message=gst_bus_pop(p.bus)){
            auto type=GST_MESSAGE_TYPE(message);
            if(type==GST_MESSAGE_ERROR){auto detail=safe_error(p.pipe,message,ready,paused,seeking);gst_message_unref(message);output(detail);return 45;}
            if(type==GST_MESSAGE_ASYNC_DONE){
                if(!ready){ready=true;hardware=hw_library();device=vsp();if(!hardware||!device){gst_message_unref(message);throw 46;}}
                if(startup_seek){startup_seek=false;seek(target);}else{if(seeking)output({{"seek_event",3},{"seek_requests",seek_requests},{"seek_async_done",true},{"seek_async_seq",gst_message_get_seqnum(message)},{"seek_async_from_pipeline",GST_MESSAGE_SRC(message)==GST_OBJECT(p.pipe)}});seeking=false;gst_element_set_state(p.pipe,paused?GST_STATE_PAUSED:GST_STATE_PLAYING);}
            }
            // Sinks/OMX can change their latency after preroll. Propagate the
            // common latency to every branch, as gst-launch does; otherwise
            // the video sink may send false-late QoS upstream to the decoder.
            if(type==GST_MESSAGE_LATENCY)gst_bin_recalculate_latency(GST_BIN(p.pipe));
            if(type==GST_MESSAGE_QOS&&GST_MESSAGE_SRC(message)==GST_OBJECT(p.sink)){GstFormat fmt;guint64 processed=0,dropped=0;gst_message_parse_qos_stats(message,&fmt,&processed,&dropped);if(fmt==GST_FORMAT_BUFFERS)sink_drop=dropped;}
            if(type==GST_MESSAGE_QOS&&GST_MESSAGE_SRC(message)==GST_OBJECT(p.decoder)){GstFormat fmt;guint64 processed=0,dropped=0;gst_message_parse_qos_stats(message,&fmt,&processed,&dropped);if(fmt==GST_FORMAT_BUFFERS)decoder_drop=dropped;}
            // Do not flush/seek the vendor OMX pipeline from its EOS handler.
            // The parent reopens the confirmed story after normal teardown.
            if(type==GST_MESSAGE_EOS){output({{"eof",true}});ended=true;}
            gst_message_unref(message);
        }
        if(!ready&&g_get_monotonic_time()-boot>20000000)throw 47;
        auto pull_at=g_get_monotonic_time();
        GstSample*sample=paused?gst_app_sink_try_pull_preroll(GST_APP_SINK(p.sink),0):gst_app_sink_try_pull_sample(GST_APP_SINK(p.sink),0);
        pull_us+=g_get_monotonic_time()-pull_at;
        if(sample){
            auto*caps=gst_sample_get_caps(sample);auto*shape=caps?gst_caps_get_structure(caps,0):nullptr;int fw=0,fh=0,num=0,den=0;
            if(shape){gst_structure_get_int(shape,"width",&fw);gst_structure_get_int(shape,"height",&fh);if(gst_structure_get_fraction(shape,"framerate",&num,&den)&&den>0)source_fps=double(num)/den;}
            int scale=0,cw=0,ch=0;bool markers=false;
            if(shape){for(const char*name:{"p011-copy-scale","p011-coded-width","p011-coded-height"})markers|=gst_structure_has_field(shape,name);
                gst_structure_get_int(shape,"p011-copy-scale",&scale);gst_structure_get_int(shape,"p011-coded-width",&cw);gst_structure_get_int(shape,"p011-coded-height",&ch);}
            if((fused_half&&(!p011_hw::fused_output_valid(w,h,fw,fh,scale,cw,ch)||
                (std::max(w,h)<=960&&markers)))||(!fused_half&&markers)){
                gst_sample_unref(sample);throw 49;
            }
            output_width=fw;output_height=fh;if(scale==2)fused_half_frames++;
            auto*buffer=gst_sample_get_buffer(sample);GstVideoInfo info;gst_video_info_init(&info);GstVideoFrame mapped{};auto map_at=g_get_monotonic_time();
            if(!buffer||!caps||!gst_video_info_from_caps(&info,caps)||!gst_video_frame_map(&mapped,&info,buffer,GST_MAP_READ)){gst_sample_unref(sample);throw 48;}
            map_us+=g_get_monotonic_time()-map_at;
            if(gst_buffer_get_video_meta(buffer))video_meta_frames++;
            auto*memory=gst_buffer_n_memory(buffer)==1?gst_buffer_peek_memory(buffer,0):nullptr;
            if(memory&&gst_memory_is_type(memory,"openmax"))omx_memory_frames++;
            else if(memory&&gst_memory_is_type(memory,GST_ALLOCATOR_SYSMEM))system_memory_frames++;
            else other_memory_frames++;
            mapped_stride_y=GST_VIDEO_FRAME_PLANE_STRIDE(&mapped,0);
            mapped_offset_uv=GST_VIDEO_INFO_PLANE_OFFSET(&mapped.info,1);mapped_bytes=gst_buffer_get_size(buffer);
            auto format=GST_VIDEO_INFO_FORMAT(&info);bool nv12=format==GST_VIDEO_FORMAT_NV12;
            int shrink=std::max(fw,fh)>960?2:1,tw=fw/shrink/2*2,th=fh/shrink/2*2;
            unsigned size=tw*th*3/2;
            if(!p011_hw::valid(tw,th,size)||(format!=GST_VIDEO_FORMAT_I420&&!nv12)){gst_video_frame_unmap(&mapped);gst_sample_unref(sample);throw 49;}
            pts=seconds(GST_BUFFER_PTS(buffer));bool stored=false;auto copy_at=g_get_monotonic_time();
            for(auto&f:shared->frames)if(p011_hw::take(f.state,p011_hw::Free,p011_hw::Writing)){
                f.serial=++serial;f.width=tw;f.height=th;f.bytes=size;f.pts=pts;f.format=1;
                f.matrix=info.colorimetry.matrix==GST_VIDEO_COLOR_MATRIX_BT709?1:info.colorimetry.matrix==GST_VIDEO_COLOR_MATRIX_BT601?0:(fused_half?h:fh)>576?1:0;
                f.full_range=info.colorimetry.range==GST_VIDEO_COLOR_RANGE_0_255;
                // Copy once into bounded panel-sized I420. The 2x box filter
                // avoids large Mali textures and a full-size RGBA conversion.
                // Official GstVideoFrame component stride/offsets handle both
                // vendor NV12 and I420 without guessing physical addresses.
                unsigned offset=0;for(int component=0;component<3;component++){
                    int rows=component?th/2:th,cols=component?tw/2:tw,stride=GST_VIDEO_FRAME_COMP_STRIDE(&mapped,component),step=GST_VIDEO_FRAME_COMP_PSTRIDE(&mapped,component);
                    auto*data=GST_VIDEO_FRAME_COMP_DATA(&mapped,component);
                    if(stride<cols*shrink*step||(step!=1&&step!=2)){gst_video_frame_unmap(&mapped);gst_sample_unref(sample);throw 49;}
                    p011_hw::pack_plane(f.pixels+offset,data,cols,rows,stride,step,shrink);
                    offset+=rows*cols;
                }
                p011_hw::set(f.state,p011_hw::Ready);stored=true;break;
            }
            copy_us+=g_get_monotonic_time()-copy_at;
            if(!stored)shared_drop++;delivered++;
            gst_video_frame_unmap(&mapped);gst_sample_unref(sample);
        }
        auto now=g_get_monotonic_time();
        if(now-last_status>=100000){
            gint64 value=0;if(gst_element_query_position(p.pipe,GST_FORMAT_TIME,&value)&&value>=0)pos=double(value)/GST_SECOND;
            const uint64_t position_sample_us=g_get_monotonic_time();
            if(gst_element_query_duration(p.pipe,GST_FORMAT_TIME,&value)&&value>0)duration=double(value)/GST_SECOND;
            if(seek_requests){
                GstState state=GST_STATE_VOID_PENDING,pending=GST_STATE_VOID_PENDING;
                auto result=gst_element_get_state(p.pipe,&state,&pending,0);
                J trace={{"seek_event",4},{"seek_requests",seek_requests},{"seek_pipeline_state",int(state)},
                         {"seek_pipeline_pending",int(pending)},{"seek_state_result",int(result)},{"seek_pipeline_position",pos},{"seek_sample_pts",pts},
                         {"seek_video_pull_mode",pull_mode(p.pipe,"vd")},{"seek_audio_pull_mode",pull_mode(p.pipe,"ad")},{"seek_network_ring_bytes",10485760}};
                for(auto entry:{std::make_pair("seek_video_position",p.sink),std::make_pair("seek_audio_position",p.audio)}){
                    gint64 position=0;trace[entry.first]=gst_element_query_position(entry.second,GST_FORMAT_TIME,&position)?double(position)/GST_SECOND:-1.;
                }
                video_trace.snapshot(trace,"seek_video_");audio_trace.snapshot(trace,"seek_audio_");output(trace);
            }
            double cpu=double(clock())/CLOCKS_PER_SEC,percent=(cpu-cpu0)*100000000/std::max<int64_t>(1,now-cpu_at);cpu0=cpu;cpu_at=now;
            J status={{"ready",ready},{"paused",paused},{"seeking",seeking},{"position",pos},{"duration",duration},{"pts",pts},{"source_fps",source_fps},{"source_width",w},{"source_height",h},{"upload_width",ow},{"upload_height",oh},{"delivered",delivered},{"encoded",encoded.load()},{"decoded",decoded.load()},{"decoder_drops",decoder_drop},{"drops",sink_drop+shared_drop},{"hardware_library",hardware},{"vsp_open",device},{"pulse",ready},{"cpu_percent",percent},{"copy_us",copy_us},{"map_us",map_us},{"pull_us",pull_us},
                        {"allocation_queries",allocation.queries.load()},{"allocation_meta_proposals",allocation.proposals.load()},
                        {"video_meta_frames",video_meta_frames},{"omx_memory_frames",omx_memory_frames},{"system_memory_frames",system_memory_frames},{"other_memory_frames",other_memory_frames},
                        {"mapped_stride_y",mapped_stride_y},{"mapped_offset_uv",mapped_offset_uv},{"mapped_bytes",mapped_bytes}};
            status.update({{"fused_half_probe",fused_probe},{"fused_half_copy",fused_half},{"fused_half_frames",fused_half_frames},
                           {"unsynchronized_throughput_probe",throughput_probe},
                           {"diagnostic_decoder_qos_property",diagnostic_decoder_qos_property},
                           {"output_width",output_width},{"output_height",output_height},
                           {"sink_qos_drops",sink_drop},{"shared_slot_drops",shared_drop}});
            guint queued=0,queued_bytes=0,network_bytes=0;guint64 queued_time=0;
            g_object_get(p.video_input,"current-level-buffers",&queued,"current-level-bytes",&queued_bytes,"current-level-time",&queued_time,nullptr);
            g_object_get(p.video_network,"current-level-bytes",&network_bytes,nullptr);
            status.update({{"video_queued_buffers",queued},{"video_queued_bytes",queued_bytes},{"video_queued_ns",queued_time},{"video_network_bytes",network_bytes}});
            guint audio_queued=0;guint64 ahead=0,audio_ahead=0;g_object_get(p.video_network,"current-level-time",&ahead,nullptr);
            if(p.audio_network)g_object_get(p.audio_network,"current-level-bytes",&audio_queued,nullptr);
            if(p.audio_input)g_object_get(p.audio_input,"current-level-time",&audio_ahead,nullptr);
            status["prefetch_safe"]=(network_bytes>=262144||ahead>=2*GST_SECOND||video_download.complete.load())&&
                (!has_audio||audio_queued>=16384||audio_ahead>=GST_SECOND||audio_download.complete.load());
            status["prefetch_video_bytes"]=network_bytes;status["prefetch_audio_bytes"]=audio_queued;
            status["prefetch_video_eof"]=video_download.complete.load();status["prefetch_audio_eof"]=audio_download.complete.load();
            status["cached_media"]=cached_input;
            status["position_sample_us"]=position_sample_us;
            status["rate"]=rate;
            private_profile(p.decoder,status);
#ifdef P011_OUTPUT_CACHE_PROBE
            status.update(cache_snapshot());status["output_cache_probe"]=true;status["output_cache_enabled"]=cache_mode=="cached";
#endif
#ifdef P011_BUNDLED_OUTPUT_CACHE
            status.update(cache_snapshot());status["output_cache_feature"]=true;status["cache_vendor_verified"]=cache_vendor_verified;
            status["output_cache_enabled"]=status.value("cache_active",uint64_t(0))>0;
            // Reuse the existing 100ms snapshot, not a new cache mutex/ioctl on
            // every input frame. Unknown layout/fallback/error disables the
            // extra retention; the next serialized input callback applies it.
            p011_hw::RetentionCacheEvidence retention{cache_vendor_verified,w,h,
                status.value("cache_changed_allocations",uint64_t(0)),status.value("cache_active",uint64_t(0)),
                status.value("cache_read_begin",uint64_t(0)),status.value("cache_fallback_active",uint64_t(0)),
                status.value("cache_sync_errors",uint64_t(1)),status.value("cache_ownership_errors",uint64_t(1))};
            encoded_trace.cached_output_ready.store(retention.ready());
            if(delivered&&status.value("cache_read_begin",uint64_t(0))+status.value("cache_fallback_read_begin",uint64_t(0))==0)throw 56;
#endif
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
            if(status.value("cache_sync_errors",uint64_t(0))||status.value("cache_ownership_errors",uint64_t(0)))throw 56;
#endif
            encoded_trace.snapshot(status);
            if(!output(status))break;
            last_status=now;
        }
        pollfd fd={0,POLLIN,0};poll(&fd,1,4);
    }
    return 0;
}
int main(int argc,char**argv){
    if(argc==2&&std::string(argv[1])=="--preflight"){
        guint major=0,minor=0,micro=0,nano=0;gst_version(&major,&minor,&micro,&nano);
        gst_init(nullptr,nullptr);auto allocation_checks=p011_hw::allocation_selftest();
        auto checks=p011_hw::pack_selftest();bool ok=major==1&&minor==14&&micro==2&&checks>400000&&allocation_checks==6;
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
#ifdef P011_BUNDLED_OUTPUT_CACHE
        std::string cache_plugin=p011_hw::cache_bundle_plugin();bool cache_ok=!cache_plugin.empty();
#else
        bool cache_ok=cache_root_valid();
        std::string cache_plugin=cache_ok?std::string(getenv("P011_CACHE_PROBE_ROOT"))+"/libgstomx.so":"";
#endif
        void*plugin=cache_ok?dlopen(cache_plugin.c_str(),RTLD_NOW|RTLD_LOCAL):nullptr;
        for(auto item:{std::make_pair("p011_omx_copy_selftest",17408u),std::make_pair("p011_omx_profile_selftest",8u),
                       std::make_pair("p011_omx_parallel_selftest",1620u),std::make_pair("p011_omx_half_selftest",2016u),
                       std::make_pair("p011_omx_copy_mode",4u)}){
            auto fn=plugin?reinterpret_cast<unsigned(*)()>(dlsym(plugin,item.first)):nullptr;
            if(!fn||fn()!=item.second)cache_ok=false;
        }
        if(plugin)dlclose(plugin);ok=ok&&cache_ok;
#endif
#ifdef __ARM_NEON
        bool neon=true;
#else
        bool neon=false;
#endif
        std::string data=J{{"ok",ok},{"gstreamer_major",major},{"gstreamer_minor",minor},{"gstreamer_micro",micro},{"window_opened",false},{"audio_played",false},{"shared_bytes",sizeof(p011_hw::Shared)},{"pack_checks",checks},{"allocation_checks",allocation_checks},{"neon",neon}}.dump()+"\n";
        write(1,data.data(),data.size());return ok?0:2;
    }
    if(argc!=2)return 2;pid_t parent=atoi(argv[1]);prctl(PR_SET_PDEATHSIG,SIGTERM);if(parent<=1||getppid()!=parent)return 90;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGALRM,stop);signal(SIGPIPE,SIG_IGN);
    // fd4 is a private protocol pipe. All vendor stdout/stderr is discarded.
    int nullfd=open("/dev/null",O_WRONLY);if(nullfd<0)return 2;dup2(nullfd,1);dup2(nullfd,2);if(nullfd>4)close(nullfd);
    int code=50;try{code=run();}catch(int c){code=c;}catch(...){}
#if defined(P011_OUTPUT_CACHE_PROBE) || defined(P011_BUNDLED_OUTPUT_CACHE)
    // run()'s Pipeline destructor has joined all streaming threads and freed
    // the OMX buffers before this final ownership report is emitted.
    J final=cache_snapshot();final["cache_final"]=true;
    if(final.value("cache_active",uint64_t(1))||final.value("cache_sync_errors",uint64_t(1))||
       final.value("cache_ownership_errors",uint64_t(1))||
       final.value("cache_registered",uint64_t(0))!=final.value("cache_forgotten",uint64_t(1))||
       final.value("cache_read_begin",uint64_t(0))!=final.value("cache_read_end",uint64_t(1))||
       final.value("cache_fallback_active",uint64_t(1))||
       final.value("cache_fallback_registered",uint64_t(0))!=final.value("cache_fallback_forgotten",uint64_t(1))||
       final.value("cache_fallback_read_begin",uint64_t(0))!=final.value("cache_fallback_read_end",uint64_t(1)))code=56;
    if(!output(final)&&!code)code=57;
#endif
    if(code)output({{"error",code}});return code;
}
