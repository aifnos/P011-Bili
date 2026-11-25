// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>

namespace p011_hw {
// Inspect a COMPLETE Annex-B access unit, never a length-prefixed packet or
// arbitrary byte fragment. Unknown/malformed input is not discardable. This
// only classifies NAL headers; it does not claim to validate the H.264 stream.
struct AccessUnit {
    bool valid=false, vcl=false, reference=false, metadata=false;
    bool discardable=false;
    unsigned nals=0;
};
inline bool nonref_eligible(bool requested,int width,int height,int num,int den){
    return requested&&width>0&&height>0&&width<=1920&&height<=1920&&
        int64_t(width)*height>1280*720&&int64_t(width)*height<=1920*1080&&
        den>0&&double(num)/den>45;
}
struct RetentionCacheEvidence {
    bool vendor_verified=false;
    int width=0,height=0;
    uint64_t changed=0,active=0,reads=0,fallback_active=0,sync_errors=0,ownership_errors=0;
    bool ready()const{
        return vendor_verified&&width==1920&&height==1080&&changed&&active&&reads&&
            !fallback_active&&!sync_errors&&!ownership_errors;
    }
};
inline unsigned production_nonref_period(int num,int den,bool verified_cached_output=false){
    if(num<=0||den<=0)return 1; // Unknown rate: unsupported period keeps all.
    const double fps=double(num)/den;
    // Only a verified, actively read cached output can retain half of the
    // disposable pictures. This still is reduced-rate compatibility, NOT
    // full source-rate playback. Startup/fallback retain the old policy.
    if(verified_cached_output&&fps>45&&fps<=60)return 2;
    return double(num)/den>55?0:3;
}
struct NonReferencePolicy {
    unsigned keep_every=3,seen=0;
    void reset(){seen=0;}
    bool drop(const AccessUnit&au,bool enabled){
        if(!enabled||!au.valid||!au.discardable||au.reference||au.metadata)return false;
        if(keep_every!=0&&keep_every!=2&&keep_every!=3)return false;
        // Resetting at the period bounds the counter and avoids wraparound.
        if(keep_every==0)return true;
        seen++;if(seen>=keep_every){seen=0;return false;}return true;
    }
};
inline AccessUnit inspect_annexb(const uint8_t*data,size_t size){
    AccessUnit result;
    if(!data||size<4||size>16*1024*1024)return result;
    auto start=[&](size_t at){
        for(size_t i=at;i+2<size;i++)
            if(!data[i]&&!data[i+1]&&data[i+2]==1)return i;
        return size;
    };
    size_t delimiter=start(0);
    if(delimiter==size)return result;
    for(size_t i=0;i<delimiter;i++)if(data[i])return result;
    bool only_disposable=true;
    while(delimiter<size){
        size_t header=delimiter+3;
        if(header>=size)return result;
        size_t next=start(header),end=next;
        while(end>header&&data[end-1]==0)end--;
        // A header alone is insufficient to classify an intact slice.
        if(end<=header+1||(data[header]&0x80)||++result.nals>256)return result;
        const unsigned type=data[header]&31,ref=(data[header]>>5)&3;
        // Conservatively retain any nonzero reference indication, including
        // one appearing on a malformed or unexpected non-VCL NAL type.
        result.reference|=ref!=0;
        if(type==1||type==5){
            result.vcl=true;result.reference|=ref!=0||type==5;
            only_disposable&=type==1&&ref==0;
        }else if(type==9||type==12){
            // AUD and filler have no reference-picture state.
        }else{
            // Keep SPS/PPS/SEI, end markers, data partitions, extensions and
            // unknown NALs, even if combined with a disposable picture.
            only_disposable=false;
            result.metadata|=type==6||type==7||type==8;
        }
        delimiter=next;
    }
    result.valid=true;
    result.discardable=result.vcl&&only_disposable&&!result.reference;
    return result;
}
}
