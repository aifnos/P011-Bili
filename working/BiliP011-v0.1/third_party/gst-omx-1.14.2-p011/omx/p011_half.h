/* SPDX-License-Identifier: LGPL-2.1-only
 * Private copy-out experiment. A rounded 2x2 box, byte-identical to the
 * existing panel upload filter; never skips frames or retains OMX memory.
 */
#ifndef P011_HALF_H
#define P011_HALF_H
#include <stdint.h>
#include <stddef.h>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

typedef struct {
  unsigned width, height;
  size_t uv_offset, source_end;
} P011HalfLayout;

static int p011_half_size(unsigned width,unsigned height,unsigned *ow,unsigned *oh)
{
  if(width<4||height<4||width>1920||height>1920||
      (uint64_t)width*height>1920u*1080u||(width&1)||(height&1)||
      (width<=960&&height<=960))return 0;
  *ow=(width/4)*2;*oh=(height/4)*2;return 1;
}
static int p011_half_layout(unsigned width,unsigned height,int stride,unsigned slice,
    size_t offset,size_t filled,size_t allocated,P011HalfLayout *out)
{
  P011HalfLayout v;
  if(!out||!p011_half_size(width,height,&v.width,&v.height)||stride<(int)width||
      stride>16384||slice<height||slice>4096||(slice&1)||
      allocated>67108864||offset>allocated||filled>allocated-offset)return 0;
  v.uv_offset=(size_t)stride*slice;
  /* Both rows of the last chroma box must be within filled/allocated data.
   * Bounds use the actual read span, not an assumed tightly packed frame. */
  v.source_end=v.uv_offset+(size_t)stride*(v.height-1)+v.width*2;
  if(v.source_end>filled)return 0;
  *out=v;return 1;
}
static int p011_half_destination(const P011HalfLayout *v,int ystride,int uvstride,
    size_t uv_offset,size_t bytes)
{
  if(!v||v->width<2||v->height<2||v->width>960||v->height>960||
      (v->width&1)||(v->height&1)||ystride<(int)v->width||uvstride<(int)v->width||
      ystride>16384||uvstride>16384||bytes>67108864||uv_offset>bytes||
      uv_offset<(size_t)ystride*v->height)return 0;
  return (size_t)uvstride*(v->height/2-1)+v->width<=bytes-uv_offset;
}
/* bytes is the DESTINATION row size; step=1 is Y, step=2 interleaved UV.
 * stride is ONE source-row pitch. All vector loads stop before row padding. */
static void p011_half_row(uint8_t *dst,const uint8_t *src,size_t bytes,
    ptrdiff_t stride,unsigned step)
{
  size_t x=0,cols=bytes/step;
#ifdef __ARM_NEON
  for(;x+8<=cols;x+=8){
    if(step==1){
      uint8x16_t a=vld1q_u8(src+2*x),b=vld1q_u8(src+stride+2*x);
      vst1_u8(dst+x,vrshrn_n_u16(vaddq_u16(vpaddlq_u8(a),vpaddlq_u8(b)),2));
    }else{
      uint8x16x2_t a=vld2q_u8(src+4*x),b=vld2q_u8(src+stride+4*x);
      uint8x8x2_t c;
      c.val[0]=vrshrn_n_u16(vaddq_u16(vpaddlq_u8(a.val[0]),vpaddlq_u8(b.val[0])),2);
      c.val[1]=vrshrn_n_u16(vaddq_u16(vpaddlq_u8(a.val[1]),vpaddlq_u8(b.val[1])),2);
      vst2_u8(dst+2*x,c);
    }
  }
#endif
  for(;x<cols;x++){
    unsigned c;for(c=0;c<step;c++){
      size_t at=2*x*step+c;
      dst[x*step+c]=((unsigned)src[at]+src[at+step]+src[at+stride]+src[at+stride+step]+2)/4;
    }
  }
}
#endif
