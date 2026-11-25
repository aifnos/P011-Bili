// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/h264_access_unit.hpp"
#include <algorithm>
#include <cassert>
#include <iostream>
#include <vector>
using p011_hw::inspect_annexb;
static unsigned checks=0;
static void checked(bool value,int line){if(!value){std::cerr<<"Failed at line "<<line<<"\n";std::abort();}checks++;}
#define check(value) checked((value),__LINE__)
static std::vector<uint8_t> nal(unsigned header,bool four=false){
    std::vector<uint8_t> v={0,0,1,uint8_t(header),0x80};
    if(four)v.insert(v.begin(),0);return v;
}
int main(){
    check(!inspect_annexb(nullptr,0).discardable);
    for(unsigned h=0;h<256;h++)for(bool four:{false,true}){
        auto bytes=nal(h,four);auto r=inspect_annexb(bytes.data(),bytes.size());
        check(r.valid==(h<128));check(r.discardable==(h==1));
        for(size_t n=0;n<bytes.size();n++)check(!inspect_annexb(bytes.data(),n).discardable);
    }
    for(unsigned h=0;h<128;h++){
        auto bytes=nal(1,true),extra=nal(h);bytes.insert(bytes.end(),extra.begin(),extra.end());
        auto r=inspect_annexb(bytes.data(),bytes.size());
        check(r.valid);check(r.discardable==(h==1||h==9||h==12));
        check(r.nals==2);
    }
    auto bytes=nal(1);
    bytes.insert(bytes.begin(),{2,0});check(!inspect_annexb(bytes.data(),bytes.size()).valid);
    bytes={0,0,1,0,0,1,1,0x80};check(!inspect_annexb(bytes.data(),bytes.size()).valid);
    bytes={0,0,1,1,0x80,0,0,1};check(!inspect_annexb(bytes.data(),bytes.size()).discardable);
    bytes={0,0,1,1,0x80,0,0,3,1,0x80};check(inspect_annexb(bytes.data(),bytes.size()).nals==1);
    bytes={0,0,0,1,1,0x80,0,0,0};check(inspect_annexb(bytes.data(),bytes.size()).discardable);
    bytes.clear();for(unsigned i=0;i<257;i++){auto n=nal(1);bytes.insert(bytes.end(),n.begin(),n.end());}
    check(!inspect_annexb(bytes.data(),bytes.size()).discardable);
    bytes.assign(16*1024*1024+1,0);check(!inspect_annexb(bytes.data(),bytes.size()).valid);
    check(!p011_hw::nonref_eligible(false,1920,1080,60,1));
    check(!p011_hw::nonref_eligible(true,1920,1080,30,1));
    check(!p011_hw::nonref_eligible(true,1280,720,60,1));
    check(!p011_hw::nonref_eligible(true,3840,2160,60,1));
    check(!p011_hw::nonref_eligible(true,1920,1080,60,0));
    check(p011_hw::nonref_eligible(true,1920,1080,60000,1001));
    check(p011_hw::nonref_eligible(true,1080,1920,50,1));
    check(p011_hw::production_nonref_period(60,1)==0);
    check(p011_hw::production_nonref_period(60000,1001)==0);
    check(p011_hw::production_nonref_period(50,1)==3);
    check(p011_hw::production_nonref_period(55,1)==3);
    check(p011_hw::production_nonref_period(55001,1000)==0);
    check(p011_hw::production_nonref_period(0,1)==1);
    check(p011_hw::production_nonref_period(60,0)==1);
    check(p011_hw::production_nonref_period(-60,1)==1);
    check(p011_hw::production_nonref_period(60,1,true)==2);
    check(p011_hw::production_nonref_period(60000,1001,true)==2);
    check(p011_hw::production_nonref_period(50,1,true)==2);
    check(p011_hw::production_nonref_period(45,1,true)==3);
    check(p011_hw::production_nonref_period(120,1,true)==0);
    check(p011_hw::production_nonref_period(60,0,true)==1);
    check(p011_hw::production_nonref_period(0,1,true)==1);
    for(unsigned mask=0;mask<128;mask++)for(int width:{1280,1920,1080})for(int height:{720,1080,1920}){
        p011_hw::RetentionCacheEvidence cache{bool(mask&1),width,height,
            mask&2?20u:0u,mask&4?12u:0u,mask&8?100u:0u,
            mask&16?1u:0u,mask&32?1u:0u,mask&64?1u:0u};
        check(cache.ready()==(mask==15&&width==1920&&height==1080));
    }
    // Warmup -> verified output -> fallback -> verified again must retain
    // references throughout and reset the disposable-picture phase.
    p011_hw::NonReferencePolicy transition;
    for(bool ready:{false,true,false,true}){
        transition.keep_every=p011_hw::production_nonref_period(60,1,ready);transition.reset();
        unsigned dropped=0;
        for(unsigned i=0;i<20;i++){
            auto d=nal(1),ref=nal(0x41);check(!transition.drop(inspect_annexb(ref.data(),ref.size()),true));
            dropped+=transition.drop(inspect_annexb(d.data(),d.size()),true);
        }
        check(dropped==(ready?10:20));
    }
    for(unsigned mode:{0u,1u,2u,3u,4u}){
        p011_hw::NonReferencePolicy policy;policy.keep_every=mode;unsigned skipped=0;
        for(unsigned i=0;i<300;i++){
            auto d=nal(1),ref=nal(0x41),meta=nal(6);
            check(!policy.drop(inspect_annexb(ref.data(),ref.size()),true));
            check(!policy.drop(inspect_annexb(meta.data(),meta.size()),true));
            check(!policy.drop(inspect_annexb(d.data(),d.size()),false));
            skipped+=policy.drop(inspect_annexb(d.data(),d.size()),true);
        }
        check(skipped==(mode==0?300:mode==2?150:mode==3?200:0));
        policy.reset();check(policy.seen==0);
    }
    // Deterministic bounded malformed packets under ASan/UBSan.
    uint32_t rng=12345;
    for(unsigned i=0;i<20000;i++){
        bytes.resize(i%128);for(auto&b:bytes){rng=rng*1664525+1013904223;b=uint8_t(rng>>24);}
        if(i%3==0&&bytes.size()>4){bytes[0]=bytes[1]=0;bytes[2]=1;}
        auto r=inspect_annexb(bytes.data(),bytes.size());
        check(!r.discardable||(r.valid&&r.vcl&&!r.reference&&!r.metadata));
    }
    std::cout<<"H264_ACCESS_UNIT_CHECKS="<<checks<<"\n";
}
