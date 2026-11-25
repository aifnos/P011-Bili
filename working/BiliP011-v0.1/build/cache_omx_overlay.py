"""Exact two-file open-source overlay, only in the diagnostic build directory.

Never edits the source baseline or a vendor binary. All anchors must be unique.
"""
def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('Cache overlay anchor changed')
    return source.replace(old,new,1)

def overlay(name,source,fallback=False):
    source=replace_once(source,'#include <gst/gst.h>','#include <gst/gst.h>\n#include "omx_cache_bridge.h"')
    if name=='gstomx.c':
        old='''      err =
          OMX_AllocateBuffer (comp->handle, &buf->omx_buf, port->index, buf,
          port->port_def.nBufferSize);
      buf->eglimage = FALSE;'''
        new='''      gboolean cache_output = port->port_def.eDir == OMX_DirOutput &&
          port->port_def.eDomain == OMX_PortDomainVideo;
      if (cache_output && (port->index != 1 ||
          port->port_def.format.video.nFrameWidth != 1920 ||
          port->port_def.format.video.nFrameHeight != 1080 ||
          port->port_def.format.video.nStride != 1920 ||
          port->port_def.format.video.nSliceHeight != 1088 ||
          port->port_def.format.video.eColorFormat != OMX_COLOR_FormatYUV420SemiPlanar ||
          !p011_cache_allocate_begin (port->port_def.nBufferSize))) {
        err = OMX_ErrorUnsupportedSetting;
      } else {
        err = OMX_AllocateBuffer (comp->handle, &buf->omx_buf, port->index, buf,
            port->port_def.nBufferSize);
        if (cache_output && !p011_cache_allocate_end (
            buf->omx_buf ? buf->omx_buf->pBuffer : NULL,
            buf->omx_buf ? buf->omx_buf->nAllocLen : 0, err == OMX_ErrorNone))
          err = OMX_ErrorUndefined;
      }
      buf->eglimage = FALSE;'''
        if fallback:
            new='''      gboolean cache_output = port->port_def.eDir == OMX_DirOutput &&
          port->port_def.eDomain == OMX_PortDomainVideo;
      gboolean cache_eligible = cache_output && p011_cache_enabled () &&
          port->index == 1 &&
          port->port_def.nBufferSize == 3133440 &&
          port->port_def.format.video.nFrameWidth == 1920 &&
          port->port_def.format.video.nFrameHeight == 1080 &&
          port->port_def.format.video.nStride == 1920 &&
          port->port_def.format.video.nSliceHeight == 1088 &&
          port->port_def.format.video.eColorFormat == OMX_COLOR_FormatYUV420SemiPlanar;
      if (cache_output && !p011_cache_output_begin (port->port_def.nBufferSize, cache_eligible)) {
        err = OMX_ErrorUnsupportedSetting;
      } else {
        err = OMX_AllocateBuffer (comp->handle, &buf->omx_buf, port->index, buf,
            port->port_def.nBufferSize);
        if (cache_output && !p011_cache_allocate_end (
            buf->omx_buf ? buf->omx_buf->pBuffer : NULL,
            buf->omx_buf ? buf->omx_buf->nAllocLen : 0, err == OMX_ErrorNone))
          err = OMX_ErrorUndefined;
      }
      buf->eglimage = FALSE;'''
        source=replace_once(source,old,new)
        source=replace_once(source,'      tmp = OMX_FreeBuffer (comp->handle, port->index, buf->omx_buf);',
            '''      void *cache_base = buf->omx_buf->pBuffer;
      if (p011_cache_can_forget (cache_base)) {
        tmp = OMX_FreeBuffer (comp->handle, port->index, buf->omx_buf);
        if (tmp == OMX_ErrorNone) p011_cache_forget (cache_base);
      } else {
        tmp = OMX_ErrorUndefined;
      }''')
    elif name=='gstomxvideodec.c':
        source=replace_once(source,'  OMX_PARAM_PORTDEFINITIONTYPE *port_def = &self->dec_out_port->port_def;\n  gboolean ret = FALSE;\n  GstVideoFrame frame;',
            '''  OMX_PARAM_PORTDEFINITIONTYPE *port_def = &self->dec_out_port->port_def;
  gboolean ret = FALSE;
  GstVideoFrame frame;
  gboolean cache_reading = p011_cache_read_begin (inbuf->omx_buf->pBuffer,
      inbuf->omx_buf->nAllocLen);
  if (!cache_reading) goto done;''')
        source=replace_once(source,'done:\n  if (ret) {\n    GST_BUFFER_PTS (outbuf)',
            '''done:
  if (cache_reading && !p011_cache_read_end (inbuf->omx_buf->pBuffer)) ret = FALSE;
  if (ret) {
    GST_BUFFER_PTS (outbuf)''')
    else:raise ValueError('Unexpected overlay file')
    return source
