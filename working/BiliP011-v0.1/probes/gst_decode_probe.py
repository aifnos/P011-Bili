"""Finite stock-GStreamer decode-only probe. Private URL arrives on stdin.

No audio sink, window, output file, system setting or factory process changes.
Vendor diagnostics may contain the URL: caller must discard all raw output
except the explicitly prefixed numerical/boolean report.
"""
import ctypes as c
import os
import signal
import sys
import time


def main():
    signal.alarm(18)
    report_fd=int(sys.argv[1])
    codec=int(sys.argv[5])
    if codec not in (7,12):return 2
    def output(value):os.write(report_fd,(repr(value)+'\n').encode('ascii'))
    url=sys.stdin.buffer.readline(32769).strip()
    import re
    if len(url)>32768 or not re.match(br'^https://(?:[A-Za-z0-9-]+\.)*(?:bilivideo\.com|bilivideo\.cn|acgvideo\.com|biliapi\.net)(?::443)?/[^\r\n]+$',url):return 2
    gst=c.CDLL('libgstreamer-1.0.so.0');obj=c.CDLL('libgobject-2.0.so.0')
    def bind(lib,name,restype,args):
        f=getattr(lib,name);f.restype=restype;f.argtypes=args;return f
    ptr=c.c_void_p;char=c.c_char_p;integer=c.c_int
    bind(gst,'gst_init',None,[ptr,ptr])(None,None)
    parse=bind(gst,'gst_parse_launch',ptr,[char,c.POINTER(ptr)])
    get=bind(gst,'gst_bin_get_by_name',ptr,[ptr,char])
    state=bind(gst,'gst_element_set_state',integer,[ptr,integer])
    unref=bind(gst,'gst_object_unref',None,[ptr])
    bus_get=bind(gst,'gst_element_get_bus',ptr,[ptr])
    bus_poll=bind(gst,'gst_bus_timed_pop_filtered',ptr,[ptr,c.c_uint64,c.c_uint])
    mini_unref=bind(gst,'gst_mini_object_unref',None,[ptr])
    static_pad=bind(gst,'gst_element_get_static_pad',ptr,[ptr,char])
    current_caps=bind(gst,'gst_pad_get_current_caps',ptr,[ptr])
    caps_structure=bind(gst,'gst_caps_get_structure',ptr,[ptr,c.c_uint])
    fraction=bind(gst,'gst_structure_get_fraction',integer,[ptr,char,c.POINTER(integer),c.POINTER(integer)])
    # Variadic functions: fixed arguments carry explicit pointer types.
    setprop=bind(obj,'g_object_set',None,[ptr,char])
    connect=bind(obj,'g_signal_connect_data',c.c_ulong,[ptr,char,ptr,ptr,ptr,c.c_int])
    structure=bind(gst,'gst_structure_new_empty',ptr,[char])
    structure_set=bind(gst,'gst_structure_set',None,[ptr,char])
    structure_free=bind(gst,'gst_structure_free',None,[ptr])
    chain=b'h264parse ! omxh264dec' if codec==7 else b'h265parse ! omxh265dec'
    error=ptr();pipe=parse(b'souphttpsrc name=src ssl-strict=true user-agent=wiliwili timeout=8 ! qtdemux name=d d.video_0 ! queue max-size-buffers=8 ! '+chain+b' ! fakesink name=sink sync=false num-buffers=240 signal-handoffs=true',c.byref(error))
    report={'frames':0,'hw_library_loaded':False,'vsp_open':False,'bus_error':False,'parse_error':bool(error),'elapsed_ms':0,'cpu_ms':0}
    if not pipe or error:
        output(report);return 3
    src=get(pipe,b'src');sink=get(pipe,b'sink');bus=bus_get(pipe)
    callback=c.CFUNCTYPE(None,ptr,ptr,ptr,ptr)
    timings=[]
    @callback
    def handoff(element,buffer,pad,data):
        report['frames']+=1;timings.append(time.monotonic())
    connect(sink,b'handoff',c.cast(handoff,ptr),None,None,0)
    setprop(src,b'location',char(url),None)
    headers=structure(b'headers')
    # G_TYPE_STRING = fundamental type 16 << 2.
    structure_set(headers,b'Referer',c.c_ulong(64),char(b'https://www.bilibili.com/'),None)
    setprop(src,b'extra-headers',ptr(headers),None);structure_free(headers)
    start=time.monotonic();cpu=time.process_time()
    try:
        report['state_result']=state(pipe,4)
        while report['frames']<240 and time.monotonic()-start<12:
            msg=bus_poll(bus,50000000,2) # GST_MESSAGE_ERROR only; never print its body.
            if msg:report['bus_error']=True;mini_unref(msg);break
        report['elapsed_ms']=int((time.monotonic()-start)*1000)
        report['cpu_ms']=int((time.process_time()-cpu)*1000)
        if len(timings)>31:
            report['warm_frames']=len(timings)-31
            report['warm_elapsed_ms']=int((timings[-1]-timings[30])*1000)
        pad=static_pad(sink,b'sink')
        if pad:
            caps=current_caps(pad)
            if caps:
                shape=caps_structure(caps,0);numerator=integer();denominator=integer()
                if fraction(shape,b'framerate',c.byref(numerator),c.byref(denominator)) and denominator.value>0:
                    report['source_fps']=float(numerator.value)/denominator.value
                mini_unref(caps)
            unref(pad)
        with open('/proc/self/maps') as f:
            maps=f.read();names=('libomx_avcdec_hw_sprd.so',) if codec==7 else ('libomx_hevcdec_hw_sprd.so','libomx_h265dec_hw_sprd.so')
            report['hw_library_loaded']=any(name in maps for name in names)
        for fd in os.listdir('/proc/self/fd'):
            try:report['vsp_open']=report['vsp_open'] or os.readlink('/proc/self/fd/'+fd)=='/dev/sprd_vsp'
            except OSError:pass
        output(report)
    finally:
        state(pipe,1)
        for item in (bus,sink,src,pipe):unref(item)
    report['cleanup_finished']=True;output(report)
    return 0 if report['frames']==240 and not report['bus_error'] else 4


if __name__=='__main__':sys.exit(main())
