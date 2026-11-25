"""Decode-only throughput: no SDL/GL, audio, window or raw media on disk."""
import ctypes as c
import os,re,signal,sys,time

def main():
    signal.alarm(18)
    fd=int(sys.argv[1]);threads=int(sys.argv[2]);media=sys.argv[3];seek=int(sys.argv[4])
    if threads not in (4,6,8) or not re.match(r'^/mnt/data/p011-toolbox/bili-media/[a-f0-9]{16}$',media):return 2
    url=sys.stdin.buffer.readline(32769).strip()
    if len(url)>32768 or not re.match(br'^https://(?:[A-Za-z0-9-]+\.)*(?:bilivideo\.com|bilivideo\.cn|acgvideo\.com|biliapi\.net)(?::443)?/[^\r\n]+$',url):return 2
    mpv=c.CDLL(media+'/lib/libmpv.so.2');ptr=c.c_void_p
    def bind(name,restype,args):
        f=getattr(mpv,name);f.restype=restype;f.argtypes=args;return f
    create=bind('mpv_create',ptr,[]);option=bind('mpv_set_option_string',c.c_int,[ptr,c.c_char_p,c.c_char_p]);init=bind('mpv_initialize',c.c_int,[ptr])
    command=bind('mpv_command_async',c.c_int,[ptr,c.c_uint64,c.POINTER(c.c_char_p)])
    class Event(c.Structure):_fields_=[('id',c.c_int),('error',c.c_int),('userdata',c.c_uint64),('data',ptr)]
    wait=bind('mpv_wait_event',c.POINTER(Event),[ptr,c.c_double]);prop=bind('mpv_get_property',c.c_int,[ptr,c.c_char_p,c.c_int,ptr]);destroy=bind('mpv_terminate_destroy',None,[ptr])
    if seek not in (0,10,20):return 2
    report={'frames_requested':240,'threads':threads,'loaded':False,'ended':False,'start_seconds':seek}
    m=create()
    if not m:return 3
    try:
        for key,value in {'config':'no','terminal':'no','msg-level':'all=no','vo':'null','ao':'null','audio':'no','hwdec':'no','untimed':'yes','framedrop':'no','frames':'240','vd-lavc-threads':str(threads),'vd-lavc-o':'max_pixels=36000000','tls-verify':'yes','tls-ca-file':'/etc/ssl/certs/ca-certificates.crt','user-agent':'wiliwili','referrer':'https://www.bilibili.com/','network-timeout':'8','cache':'yes','demuxer-max-bytes':'8388608'}.items():
            if option(m,key.encode('ascii'),value.encode('ascii'))<0:return 4
        if option(m,b'start',str(seek).encode('ascii'))<0:return 4
        if init(m)<0:return 5
        start=time.monotonic();cpu=time.process_time();loaded_at=0
        cmd=(c.c_char_p*3)(b'loadfile',url,None)
        if command(m,1,cmd)<0:return 6
        while time.monotonic()-start<12:
            e=wait(m,.01).contents
            if e.id==8:report['loaded']=True;loaded_at=time.monotonic()
            if e.id==7:report['ended']=True;break
            if report['loaded']:
                for name in ('time-pos','container-fps'):
                    v=c.c_double()
                    if prop(m,name.encode('ascii'),5,c.byref(v))>=0:report[name.replace('-','_')]=v.value
        report['elapsed_ms']=int((time.monotonic()-start)*1000);report['cpu_ms']=int((time.process_time()-cpu)*1000)
        report['after_loaded_ms']=int((time.monotonic()-loaded_at)*1000) if loaded_at else 0
        os.write(fd,(repr(report)+'\n').encode('ascii'))
    finally:destroy(m)
    report['cleanup_finished']=True;os.write(fd,(repr(report)+'\n').encode('ascii'))
    return 0 if report['loaded'] and report['ended'] else 7

if __name__=='__main__':sys.exit(main())
