// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <gst/gst.h>
#include <gst/video/video.h>
#include <atomic>

namespace p011_hw {
// GStreamer 1.14 has no appsink propose-allocation signal. Handle only the
// downstream ALLOCATION query using its public pad API. GstVideoFrame maps
// the advertised video metadata; we do not supply foreign OMX buffers, DMA
// addresses, a GL allocator, or a downstream buffer pool.
struct VideoAllocation {
    std::atomic<unsigned> queries{0},proposals{0};
    static bool propose(GstQuery*query){
        if(!query||GST_QUERY_TYPE(query)!=GST_QUERY_ALLOCATION)return false;
        GstCaps*caps=nullptr;gst_query_parse_allocation(query,&caps,nullptr);
        GstVideoInfo info;gst_video_info_init(&info);
        if(!caps||!gst_caps_is_fixed(caps)||!gst_video_info_from_caps(&info,caps))return false;
        auto*features=gst_caps_get_features(caps,0);
        if(gst_caps_features_is_any(features)||!gst_caps_features_contains(features,GST_CAPS_FEATURE_MEMORY_SYSTEM_MEMORY))return false;
        const auto format=GST_VIDEO_INFO_FORMAT(&info);
        if(format!=GST_VIDEO_FORMAT_NV12&&format!=GST_VIDEO_FORMAT_I420)return false;
        if(!gst_query_find_allocation_meta(query,GST_VIDEO_META_API_TYPE,nullptr))
            gst_query_add_allocation_meta(query,GST_VIDEO_META_API_TYPE,nullptr);
        return true;
    }
    static GstPadProbeReturn probe(GstPad*,GstPadProbeInfo*info,gpointer data){
        auto*query=GST_PAD_PROBE_INFO_QUERY(info);
        if(!query||GST_QUERY_TYPE(query)!=GST_QUERY_ALLOCATION)return GST_PAD_PROBE_OK;
        auto&self=*static_cast<VideoAllocation*>(data);self.queries.fetch_add(1);
        if(!propose(query))return GST_PAD_PROBE_OK;
        self.proposals.fetch_add(1);return GST_PAD_PROBE_HANDLED;
    }
    void attach(GstElement*sink){
        auto*pad=sink?gst_element_get_static_pad(sink,"sink"):nullptr;if(!pad)throw 42;
        auto id=gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_QUERY_DOWNSTREAM|GST_PAD_PROBE_TYPE_PUSH),probe,this,nullptr);
        gst_object_unref(pad);if(!id)throw 42;
    }
};
// Uses synthetic caps/queries only: no pipeline, decoder, network or window.
inline unsigned allocation_selftest(){
    unsigned checks=0;
    for(const char*format:{"NV12","I420","RGBA"}){
        auto*caps=gst_caps_new_simple("video/x-raw","format",G_TYPE_STRING,format,"width",G_TYPE_INT,1920,"height",G_TYPE_INT,1080,nullptr);
        auto*query=gst_query_new_allocation(caps,TRUE);gst_caps_unref(caps);
        const bool supported=std::strcmp(format,"RGBA")!=0;
        bool ok=VideoAllocation::propose(query)==supported;
        ok=ok&&(gst_query_find_allocation_meta(query,GST_VIDEO_META_API_TYPE,nullptr)==supported);
        ok=ok&&gst_query_get_n_allocation_pools(query)==0&&gst_query_get_n_allocation_params(query)==0;
        if(supported)ok=ok&&VideoAllocation::propose(query)&&gst_query_get_n_allocation_metas(query)==1;
        gst_query_unref(query);if(!ok)return 0;checks++;
    }
    auto*empty=gst_query_new_allocation(nullptr,FALSE);
    bool ok=!VideoAllocation::propose(empty);gst_query_unref(empty);if(!ok)return 0;checks++;
    auto*caps=gst_caps_from_string("video/x-raw(memory:GLMemory),format=NV12,width=1920,height=1080");
    auto*foreign=gst_query_new_allocation(caps,TRUE);gst_caps_unref(caps);
    ok=!VideoAllocation::propose(foreign);gst_query_unref(foreign);if(!ok)return 0;checks++;
    auto*duration=gst_query_new_duration(GST_FORMAT_TIME);
    ok=!VideoAllocation::propose(duration);gst_query_unref(duration);return ok?checks+1:0;
}
}
