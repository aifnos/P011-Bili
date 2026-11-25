// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
#include <vector>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif
namespace p011_hw {
// GstVideoFrame supplies the component pointer and stride. The vector path
// has the same rounding as the scalar reference and never reads row padding.
inline void pack_plane(uint8_t*dst,const uint8_t*data,int cols,int rows,int stride,int step,int shrink){
    for(int row=0;row<rows;row++){
        const auto*src=data+row*shrink*stride;auto*out=dst+row*cols;int x=0;
        if(shrink==1&&step==1){std::memcpy(out,src,cols);continue;}
#ifdef __ARM_NEON
        if(shrink==2){
            // A V-component pointer may be one byte past the UV pair start.
            // Leave the last vector to scalar code for interleaved input.
            for(;step==1?x+8<=cols:x+8<cols;x+=8){
                auto a=step==1?vld1q_u8(src+x*2):vld2q_u8(src+x*4).val[0];
                auto b=step==1?vld1q_u8(src+stride+x*2):vld2q_u8(src+stride+x*4).val[0];
                vst1_u8(out+x,vrshrn_n_u16(vaddq_u16(vpaddlq_u8(a),vpaddlq_u8(b)),2));
            }
        }else{
            for(;x+16<cols;x+=16)vst1q_u8(out+x,vld2q_u8(src+x*2).val[0]);
        }
#endif
        for(;x<cols;x++){
            int at=x*shrink*step;
            out[x]=shrink==1?src[at]:(unsigned(src[at])+src[at+step]+src[at+stride]+src[at+stride+step]+2)/4;
        }
    }
}
inline unsigned pack_selftest(){
    unsigned checks=0;uint32_t seed=0x011abc;
    for(int cols:{1,2,7,8,9,15,16,17,31,32,33,65,479,480,481,959,960})
    for(int rows:{1,2,7})for(int step:{1,2})for(int shrink:{1,2})for(int padding:{0,1,7}){
        int stride=cols*shrink*step+padding;
        std::vector<uint8_t>src(stride*rows*shrink+1),out(cols*rows+32,0xcd);
        for(auto&v:src){seed=seed*1664525+1013904223;v=seed>>24;}
        // Includes the offset-one chroma component with no row padding.
        const auto*data=src.data()+(step==2?1:0);
        pack_plane(out.data()+16,data,cols,rows,stride,step,shrink);
        for(int i=0;i<16;i++)if(out[i]!=0xcd||out[out.size()-1-i]!=0xcd)return 0;
        for(int y=0;y<rows;y++)for(int x=0;x<cols;x++){
            auto*p=data+y*shrink*stride+x*shrink*step;
            unsigned expected=shrink==1?p[0]:(unsigned(p[0])+p[step]+p[stride]+p[stride+step]+2)/4;
            if(out[16+y*cols+x]!=expected)return 0;
            checks++;
        }
    }
    return checks;
}
}
