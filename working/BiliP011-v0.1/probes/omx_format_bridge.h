/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Public port-definition fields only. Never read a vendor opaque context. */
#ifndef P011_OMX_FORMAT_BRIDGE_H
#define P011_OMX_FORMAT_BRIDGE_H
#include <stdint.h>
#include <OMX_Component.h>
#ifdef __cplusplus
extern "C" {
#endif
extern void p011_omx_format_observe(const uint32_t *) __attribute__((weak));
#ifdef __cplusplus
}
#endif
static inline void p011_omx_format_record(uint32_t stage,
    const OMX_PARAM_PORTDEFINITIONTYPE *def, uint32_t fps_n, uint32_t fps_d,
    OMX_ERRORTYPE error)
{
    if (p011_omx_format_observe) {
        /* Schema 1: stage, port, width, height, stride (unsigned bits), slice,
         * Q16 fps, caps numerator/denominator, compression, color, buffers,
         * buffer bytes, combined SetParameter/GetParameter return status. */
        const uint32_t values[14] = {stage, (uint32_t)def->nPortIndex,
            (uint32_t)def->format.video.nFrameWidth, (uint32_t)def->format.video.nFrameHeight,
            (uint32_t)def->format.video.nStride, (uint32_t)def->format.video.nSliceHeight,
            (uint32_t)def->format.video.xFramerate, fps_n, fps_d,
            (uint32_t)def->format.video.eCompressionFormat,
            (uint32_t)def->format.video.eColorFormat, (uint32_t)def->nBufferCountActual,
            (uint32_t)def->nBufferSize, (uint32_t)error};
        p011_omx_format_observe(values);
    }
}
#endif
