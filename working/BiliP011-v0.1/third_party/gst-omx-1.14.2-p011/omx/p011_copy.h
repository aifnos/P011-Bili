/* SPDX-License-Identifier: LGPL-2.1-only
 * P011 private experiment, 2026-09-25. Only OMX output copies use this helper.
 * Does not interpose libc, change buffer ownership or access row padding.
 */
#ifndef P011_OMX_COPY_H
#define P011_OMX_COPY_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#ifdef P011_OMX_NEON_COPY
#include <arm_neon.h>
#endif
static inline void *p011_omx_copy(void *destination,const void *source,size_t size)
{
#ifdef P011_OMX_NEON_COPY
  uint8_t *dst=destination;const uint8_t *src=source;
  while(size>=64){
    uint8x16_t a=vld1q_u8(src),b=vld1q_u8(src+16),c=vld1q_u8(src+32),d=vld1q_u8(src+48);
    vst1q_u8(dst,a);vst1q_u8(dst+16,b);vst1q_u8(dst+32,c);vst1q_u8(dst+48,d);
    src+=64;dst+=64;size-=64;
  }
  while(size>=16){vst1q_u8(dst,vld1q_u8(src));src+=16;dst+=16;size-=16;}
  while(size--)*dst++=*src++;
  return destination;
#else
  return memcpy(destination,source,size);
#endif
}
unsigned p011_omx_copy_mode(void)
{
#ifdef P011_OMX_FUSED_HALF
  return 4;
#elif defined(P011_OMX_THREE_COPY)
  return 3;
#elif defined(P011_OMX_PARALLEL_COPY)
  return 2;
#elif defined(P011_OMX_NEON_COPY)
  return 1;
#else
  return 0;
#endif
}
unsigned p011_omx_copy_selftest(void)
{
  unsigned count=0,a,b,i,n;uint8_t src[4096],dst[4096],expected[4096];
  const unsigned lengths[]={0,1,7,15,16,17,31,32,33,63,64,65,127,128,129,1920,3840};
  for(i=0;i<sizeof(src);i++)src[i]=(i*67+13)&255;
  for(a=0;a<32;a++)for(b=0;b<32;b++)for(n=0;n<sizeof(lengths)/sizeof(lengths[0]);n++){
    memset(dst,0xa5,sizeof(dst));memset(expected,0xa5,sizeof(expected));
    memcpy(expected+32+b,src+32+a,lengths[n]);
    if(p011_omx_copy(dst+32+b,src+32+a,lengths[n])!=dst+32+b)return 0;
    if(memcmp(dst,expected,sizeof(dst)))return 0;
    count++;
  }
  return count;
}
#endif
