"""Exact finite-toolbox child, not a general shell or user command endpoint."""
import ctypes,os,re,signal,sys

def main():
    root=os.environ.get('P011_TOOLBOX_ROOT','')
    if not re.match(r'^/mnt/data/p011-toolbox/bili-awake/[0-9a-f]{24}$',root):return 90
    if len(sys.argv)!=6 or sys.argv[1] not in ('/usr/bin/gst-play-1.0','/bin/gst-play-1.0'):return 90
    if sys.argv[2:4]!=['--no-interactive','--audiosink=pulsesink']:return 90
    if not re.match(r'^--volume=(?:0\.\d{2}|1\.00)$',sys.argv[4]):return 90
    if not sys.argv[5].startswith('file://'):return 90
    parent=int(os.environ.get('P011_AUDIO_OWNER','0'))
    libc=ctypes.CDLL(None)
    if libc.prctl(1,signal.SIGTERM,0,0,0)!=0 or parent<2 or os.getppid()!=parent:return 90
    os.execv(sys.argv[1],sys.argv[1:])

if __name__=='__main__':sys.exit(main())
