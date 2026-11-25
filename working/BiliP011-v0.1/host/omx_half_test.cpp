// SPDX-License-Identifier: LGPL-2.1-only
#include <cassert>
#include <cstdio>
#include <vector>
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_copy.h"
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h"
#include "../client/hardware_pack.hpp"
#include "../client/hardware_output.hpp"

int main(){
    unsigned checks=0;P011HalfLayout layout{};
    auto check=[&](bool ok){assert(ok);++checks;};
    check(p011_omx_half_selftest()==2016);
    for(unsigned width:{962u,1280u,1918u,1920u})for(unsigned height:{4u,538u,720u,1078u,1080u}){
        unsigned stride=(width+63)/64*64,slice=(height+15)/16*16;
        size_t bytes=size_t(stride)*slice*3/2,offset=13;
        check(p011_half_layout(width,height,stride,slice,offset,bytes,bytes+offset,&layout));
        check(layout.width==width/4*2&&layout.height==height/4*2);
        check(!p011_half_layout(width,height,stride,slice,offset,layout.source_end-1,bytes+offset,&layout));
        check(!p011_half_layout(width,height,stride,slice,offset,bytes,bytes+offset-1,&layout));
        check(!p011_half_layout(width,height,-1,slice,offset,bytes,bytes+offset,&layout));
        check(!p011_half_layout(width,height,width-1,slice,offset,bytes,bytes+offset,&layout));
        check(!p011_half_layout(width,height,stride,height-2,offset,bytes,bytes+offset,&layout));
        unsigned ow=layout.width,oh=layout.height;size_t out_size=size_t(ow)*oh*3/2;
        check(p011_half_destination(&layout,ow,ow,ow*oh,out_size));
        check(!p011_half_destination(&layout,ow,ow,ow*oh,out_size-1));
        check(!p011_half_destination(&layout,ow-1,ow,ow*oh,out_size));
        check(!p011_half_destination(&layout,ow,ow,ow*oh-1,out_size));
        check(p011_hw::fused_output_valid(width,height,ow,oh,2,width,height));
        check(!p011_hw::fused_output_valid(width,height,ow/2,oh/2,2,width,height));
        check(!p011_hw::fused_output_valid(width,height,ow,oh,0,width,height));
        check(!p011_hw::fused_output_valid(width,height,ow,oh,2,width+2,height));
        std::vector<uint8_t> src(bytes+offset),dst(out_size),packed(out_size),expected(out_size);
        for(size_t i=0;i<src.size();++i)src[i]=(i*37+i/7+11)&255;
        P011CopyPlane planes[]={
            {dst.data(),src.data()+offset,ow,oh,ow,ptrdiff_t(stride*2),1},
            {dst.data()+ow*oh,src.data()+offset+layout.uv_offset,ow,oh/2,ow,ptrdiff_t(stride*2),2}};
        void*owner=nullptr;p011_copy_planes(&owner,planes,2);p011_copy_worker_free(owner);
        // Convert half-size NV12 to I420 exactly as the unchanged worker does,
        // then compare every byte to the OLD full-size upload/filter path.
        for(int c=0;c<3;c++){
            size_t pos=c?ow*oh+(c-1)*ow*oh/4:0;
            unsigned cols=c?ow/2:ow,rows=c?oh/2:oh;
            auto*s=src.data()+offset+(c?layout.uv_offset+c-1:0);
            auto*d=dst.data()+(c?ow*oh+c-1:0);
            p011_hw::pack_plane(expected.data()+pos,s,cols,rows,stride,c?2:1,2);
            p011_hw::pack_plane(packed.data()+pos,d,cols,rows,ow,c?2:1,1);
        }
        check(expected==packed);
    }
    unsigned ow=0,oh=0;
    for(auto shape:{std::pair<unsigned,unsigned>{0,1080},{1920,1},{1921,1080},{1920,1081},
            {1920,1920},{3840,2160},{960,540},{961,540},{1280,721}})
        check(!p011_half_size(shape.first,shape.second,&ow,&oh));
    check(p011_hw::fused_output_valid(640,360,640,360,0,0,0));
    check(!p011_hw::fused_output_valid(640,360,640,360,2,640,360));
    check(!p011_half_layout(1920,1080,1920,1088,UINT32_MAX,0,1,&layout));
    check(!p011_half_layout(1920,1080,1920,1088,0,0,UINT32_MAX,&layout));
    std::printf("HALF_SELF=2016 HALF_EQUIVALENCE_BOUNDS=%u\n",checks);
    return 0;
}
