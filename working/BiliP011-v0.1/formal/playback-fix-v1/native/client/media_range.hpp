// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <string>
#include <regex>
#include <algorithm>
namespace p011_media {
struct RangeReply {
    int status=0;uint64_t first=0,last=0,total=0;bool ranged=false;
    void line(std::string s){
        std::smatch m;
        if(s.rfind("HTTP/",0)==0){*this={};if(std::regex_search(s,m,std::regex("^HTTP/[^ ]+ ([0-9]{3})")))status=std::stoi(m[1]);}
        std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return char(std::tolower(c));});
        if(std::regex_match(s,m,std::regex("content-range: *bytes ([0-9]{1,12})-([0-9]{1,12})/([0-9]{1,12})\\r?\\n?"))){
            first=std::stoull(m[1]);last=std::stoull(m[2]);total=std::stoull(m[3]);ranged=first<=last&&last<total&&total<=uint64_t(8)*1024*1024*1024;
        }
    }
    bool valid(uint64_t start,uint64_t end,uint64_t expected=0)const{
        return status==206&&ranged&&first==start&&last==std::min(end,total-1)&&(!expected||total==expected);
    }
};
inline uint32_t be32(const unsigned char*p){return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];}
// ISO BMFF sidx: initialization/index plus one COMPLETE media segment.
// Nested/oversized indexes fall back to streaming; never pass a partial file
// to filesrc as a complete movie. Input is bounded to the first 64 KiB.
inline uint64_t opening_segment(const std::string&bytes,uint64_t cap){
    const auto*p=reinterpret_cast<const unsigned char*>(bytes.data());size_t at=0;
    while(at+8<=bytes.size()){
        uint64_t size=be32(p+at);size_t header=8;
        if(size==1){if(at+16>bytes.size())return 0;size=uint64_t(be32(p+at+8))<<32|be32(p+at+12);header=16;}
        if(size<header||size>65536||size>bytes.size()-at)return 0;
        if(bytes.compare(at+4,4,"sidx")==0){
            size_t b=at+header,e=at+size;if(b+24>e)return 0;unsigned version=p[b];
            if(version>1)return 0;size_t q=b+(version?20:16);if(q+(version?8:4)+4>e)return 0;
            uint64_t offset=version?(uint64_t(be32(p+q))<<32|be32(p+q+4)):be32(p+q);q+=version?8:4;
            unsigned count=unsigned(p[q+2])<<8|p[q+3];q+=4;
            if(!count||q+12>e)return 0;uint32_t reference=be32(p+q);
            if(reference&0x80000000u||!reference||offset>cap)return 0;
            uint64_t end=at+size+offset+reference;return end<=cap?end:0;
        }
        at+=size;
    }
    return 0;
}
}
