"""Diagnostic-only observation of existing OMX port updates; no new OMX calls."""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('OMX format observation anchor changed')
    return source.replace(old, new, 1)


def overlay(name, source):
    if name != 'gstomxvideodec.c':
        return source
    source = replace_once(source, '#include "gstomxvideodec.h"',
                          '#include "gstomxvideodec.h"\n#include "omx_format_bridge.h"')
    source = replace_once(source, '''  if (gst_omx_port_update_port_definition (self->dec_in_port,
          &port_def) != OMX_ErrorNone)
    return FALSE;''', '''  {
    OMX_ERRORTYPE p011_format_error;
    p011_omx_format_record (1, &port_def, info->fps_n, info->fps_d,
        OMX_ErrorNone);
    p011_format_error = gst_omx_port_update_port_definition (self->dec_in_port,
        &port_def);
    /* This cached definition was refreshed by the EXISTING GetParameter.
     * A nonzero status is retained, never presented as accepted readback. */
    p011_omx_format_record (2, &self->dec_in_port->port_def,
        info->fps_n, info->fps_d, p011_format_error);
    if (p011_format_error != OMX_ErrorNone)
      return FALSE;
  }''')
    return replace_once(source, '''  if (gst_omx_port_update_port_definition (self->dec_out_port,
          NULL) != OMX_ErrorNone)
    return FALSE;''', '''  {
    OMX_ERRORTYPE p011_format_error;
    p011_format_error = gst_omx_port_update_port_definition (self->dec_out_port,
        NULL);
    p011_omx_format_record (3, &self->dec_out_port->port_def,
        info->fps_n, info->fps_d, p011_format_error);
    if (p011_format_error != OMX_ErrorNone)
      return FALSE;
  }''')
