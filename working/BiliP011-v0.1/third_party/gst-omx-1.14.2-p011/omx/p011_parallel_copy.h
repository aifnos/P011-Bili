/* SPDX-License-Identifier: LGPL-2.1-only
 * One or two persistent helpers per decoder. Disjoint stripes of the SAME
 * frame; all complete before the OMX buffer is released or output is pushed.
 */
#ifndef P011_PARALLEL_COPY_H
#define P011_PARALLEL_COPY_H
#include <pthread.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include "p011_half.h"

typedef struct {
  uint8_t *dst; const uint8_t *src;
  size_t bytes, rows;
  ptrdiff_t dst_stride, src_stride;
  unsigned half_step; /* 0=copy; 1=Y box; 2=UV box. src_stride spans TWO rows. */
} P011CopyPlane;
typedef struct P011CopyWorker {
  pthread_t thread; pthread_mutex_t lock; pthread_cond_t cond;
  int busy, stop; unsigned count;
  P011CopyPlane planes[4];
  struct P011CopyWorker *second;
} P011CopyWorker;

static void p011_copy_rows (const P011CopyPlane *planes, unsigned count)
{
  unsigned p; size_t r;
  for (p=0;p<count;p++) for (r=0;r<planes[p].rows;r++) {
    uint8_t *dst=planes[p].dst+(ptrdiff_t)r*planes[p].dst_stride;
    const uint8_t *src=planes[p].src+(ptrdiff_t)r*planes[p].src_stride;
    if(planes[p].half_step)
      p011_half_row(dst,src,planes[p].bytes,planes[p].src_stride/2,planes[p].half_step);
    else p011_omx_copy(dst,src,planes[p].bytes);
  }
}
static void *p011_copy_thread (void *data)
{
  P011CopyWorker *w=(P011CopyWorker*)data;
  prctl(PR_SET_NAME,"p011-copy",0,0,0);
  pthread_mutex_lock(&w->lock);
  for (;;) {
    while (!w->busy&&!w->stop) pthread_cond_wait(&w->cond,&w->lock);
    if (w->stop) break;
    pthread_mutex_unlock(&w->lock);
    p011_copy_rows(w->planes,w->count);
    pthread_mutex_lock(&w->lock);w->busy=0;pthread_cond_broadcast(&w->cond);
  }
  pthread_mutex_unlock(&w->lock);return NULL;
}
static P011CopyWorker *p011_copy_worker_new_single (void)
{
  P011CopyWorker *w=(P011CopyWorker*)calloc(1,sizeof(*w));if(!w)return NULL;
  if(pthread_mutex_init(&w->lock,NULL)){free(w);return NULL;}
  if(pthread_cond_init(&w->cond,NULL)){pthread_mutex_destroy(&w->lock);free(w);return NULL;}
  if(pthread_create(&w->thread,NULL,p011_copy_thread,w)){
    pthread_cond_destroy(&w->cond);pthread_mutex_destroy(&w->lock);free(w);return NULL;
  }
  return w;
}
static P011CopyWorker *p011_copy_worker_new (void)
{
  P011CopyWorker *w=p011_copy_worker_new_single();
#ifdef P011_OMX_THREE_COPY
  /* Allocation failure falls back to the already tested two-thread path. */
  if(w)w->second=p011_copy_worker_new_single();
#endif
  return w;
}
static void p011_copy_worker_free (void *data)
{
  P011CopyWorker *w=(P011CopyWorker*)data;if(!w)return;
  if(w->second)p011_copy_worker_free(w->second);
  pthread_mutex_lock(&w->lock);w->stop=1;pthread_cond_broadcast(&w->cond);pthread_mutex_unlock(&w->lock);
  pthread_join(w->thread,NULL);
  pthread_cond_destroy(&w->cond);pthread_mutex_destroy(&w->lock);free(w);
}
static void p011_copy_dispatch (P011CopyWorker *w, const P011CopyPlane *planes, unsigned count)
{
  unsigned p,i,threads;P011CopyPlane jobs[3][4];P011CopyWorker *helpers[2];
  if(!w){p011_copy_rows(planes,count);return;}
  helpers[0]=w;helpers[1]=w->second;threads=w->second?3:2;
  /* Caller serializes frames. Never leave a frame outstanding across calls. */
  for(p=0;p<count;p++)for(i=0;i<threads;i++){
    jobs[i][p]=planes[p];
    if(planes[p].rows==1&&!planes[p].half_step){
      size_t start=((planes[p].bytes/threads)*i)&~(size_t)63;
      size_t end=i+1==threads?planes[p].bytes:((planes[p].bytes/threads)*(i+1))&~(size_t)63;
      jobs[i][p].bytes=end-start;jobs[i][p].src+=start;jobs[i][p].dst+=start;
    }else{
      size_t start=(planes[p].rows/threads)*i;
      size_t end=i+1==threads?planes[p].rows:(planes[p].rows/threads)*(i+1);
      jobs[i][p].rows=end-start;
      jobs[i][p].src+=(ptrdiff_t)start*jobs[i][p].src_stride;
      jobs[i][p].dst+=(ptrdiff_t)start*jobs[i][p].dst_stride;
    }
  }
  for(i=0;i<threads-1;i++){
    P011CopyWorker *part=helpers[i];pthread_mutex_lock(&part->lock);
    memcpy(part->planes,jobs[i],count*sizeof(P011CopyPlane));part->count=count;part->busy=1;
    pthread_cond_broadcast(&part->cond);pthread_mutex_unlock(&part->lock);
  }
  p011_copy_rows(jobs[threads-1],count);
  for(i=0;i<threads-1;i++){
    P011CopyWorker *part=helpers[i];pthread_mutex_lock(&part->lock);
    while(part->busy)pthread_cond_wait(&part->cond,&part->lock);
    pthread_mutex_unlock(&part->lock);
  }
}
static void p011_copy_planes (void **owner, const P011CopyPlane *planes, unsigned count)
{
#ifdef P011_OMX_PARALLEL_COPY
  size_t bytes=0;unsigned p;for(p=0;p<count;p++)bytes+=planes[p].bytes*planes[p].rows;
  /* Small frames stay serial. No per-frame thread construction. */
  if(bytes>=524288){
    if(!*owner)*owner=p011_copy_worker_new();
    p011_copy_dispatch((P011CopyWorker*)*owner,planes,count);return;
  }
#else
  (void)owner;
#endif
  p011_copy_rows(planes,count);
}
unsigned p011_omx_parallel_selftest (void)
{
  const size_t widths[]={0,1,7,63,64,65,127,128,1920},heights[]={0,1,2,3,9},offsets[]={0,1,15};
  uint8_t src[65536],dst[65536],expected[65536];
  unsigned count=0,i,a,b,n,o,reverse,helper,p;P011CopyPlane jobs[3];
  P011CopyWorker *w=p011_copy_worker_new();if(!w)return 0;
  for(i=0;i<sizeof(src);i++)src[i]=(i*37+11)&255;
  for(a=0;a<9;a++)for(b=0;b<5;b++)for(n=1;n<=3;n++)for(o=0;o<3;o++)
  for(reverse=0;reverse<2;reverse++)for(helper=0;helper<2;helper++){
    memset(dst,0xa5,sizeof(dst));memset(expected,0xa5,sizeof(expected));
    for(p=0;p<n;p++){
      size_t start=64+p*20000+offsets[o],r;ptrdiff_t ss=widths[a]+19,ds=widths[a]+23;
      jobs[p]=(P011CopyPlane){dst+start,src+start,widths[a],heights[b],ds,ss};
      if(reverse&&heights[b]){
        jobs[p].dst+=(heights[b]-1)*ds;jobs[p].src+=(heights[b]-1)*ss;
        jobs[p].dst_stride=-ds;jobs[p].src_stride=-ss;
      }
      for(r=0;r<jobs[p].rows;r++)
        memcpy(expected+(jobs[p].dst-dst)+(ptrdiff_t)r*jobs[p].dst_stride,
            jobs[p].src+(ptrdiff_t)r*jobs[p].src_stride,jobs[p].bytes);
    }
    p011_copy_dispatch(helper?w:NULL,jobs,n);
    if(memcmp(dst,expected,sizeof(dst))){p011_copy_worker_free(w);return 0;}count++;
  }
  p011_copy_worker_free(w);return count;
}
unsigned p011_omx_half_selftest (void)
{
  const unsigned widths[]={1,2,3,7,8,9,15,16,17,479,480,481,959,960};
  const unsigned heights[]={1,2,3,7},offsets[]={0,1,15},padding[]={0,1,7};
  uint8_t *src=(uint8_t*)malloc(65536),*dst=(uint8_t*)malloc(65536),*expected=(uint8_t*)malloc(65536);
  P011CopyWorker *w=p011_copy_worker_new();unsigned count=0,a,b,o,p,step,helper,i;
  if(!src||!dst||!expected||!w)goto done;
  for(i=0;i<65536;i++)src[i]=(i*67+i/19+13)&255;
  for(a=0;a<14;a++)for(b=0;b<4;b++)for(o=0;o<3;o++)for(p=0;p<3;p++)
  for(step=1;step<=2;step++)for(helper=0;helper<2;helper++){
    unsigned bytes=widths[a]*step,rows=heights[b],ss=bytes*2+padding[p],ds=bytes+padding[p];
    size_t start=32+offsets[o],y,x;P011CopyPlane job;
    memset(dst,0xa5,65536);memset(expected,0xa5,65536);
    job=(P011CopyPlane){dst+start,src+start,bytes,rows,ds,ss*2,step};
    for(y=0;y<rows;y++)for(x=0;x<bytes;x++){
      const uint8_t *s=src+start+y*2*ss+(x/step)*2*step+x%step;
      expected[start+y*ds+x]=((unsigned)s[0]+s[step]+s[ss]+s[ss+step]+2)/4;
    }
    p011_copy_dispatch(helper?w:NULL,&job,1);
    if(memcmp(dst,expected,65536)){count=0;goto done;}count++;
  }
done:
  p011_copy_worker_free(w);free(src);free(dst);free(expected);return count;
}
#endif
