"""Finite synthetic 60fps decoder/copy test; NOT Bili playback or panel FPS.

Uses the existing stock gst-launch, no window/audio/network/clock changes.
The only device files are a verified generated clip and private Gst registry.
"""
import argparse,ast,datetime,hashlib,json,pathlib,re,secrets,shutil,subprocess,zipfile

SHAPES={480:270,640:360,1280:720}
FRAMES=900


def parse_output(stdout,width,height):
    if type(stdout) is not bytes or len(stdout)>1048576:raise ValueError('Unbounded pipeline output')
    text=stdout.decode('utf-8','replace').replace('\r','')
    pts=[]
    for line in text.splitlines():
        if '/GstIdentity:p011_count: last-message = chain' not in line:continue
        m=re.search(r'\bpts: (\d+):(\d{2}):(\d{2})\.(\d{9})',line)
        if not m:raise ValueError('Missing frame timestamp')
        h,mi,s,n=map(int,m.groups())
        if mi>=60 or s>=60:raise ValueError('Invalid timestamp')
        pts.append(((h*60+mi)*60+s)*1000000000+n)
    rates=re.findall(r'rendered: (\d+), dropped: (\d+), current: ([0-9.]+), average: ([0-9.]+)',text)
    caps=any('/GstIdentity:p011_count.GstPad:sink: caps = video/x-raw' in line and
             'width=(int)'+str(width) in line and 'height=(int)'+str(height) in line and
             'framerate=(fraction)60/1' in line for line in text.splitlines())
    complete=(len(pts)==FRAMES and all(b>a for a,b in zip(pts,pts[1:])) and
              abs(pts[-1]-pts[0]-(FRAMES-1)*1000000000/60)<1000000)
    drops=max((int(row[1]) for row in rates),default=None)
    return dict(decoded_frames=len(pts),timestamps_complete=bool(complete),caps_verified=caps,
                eos='Got EOS from element' in text,reported_drops=drops,rate_samples=len(rates),
                final_reported_average_fps=float(rates[-1][3]) if rates else None,
                minimum_interval_fps=min((float(row[2]) for row in rates),default=None),
                pts_span_seconds=(pts[-1]-pts[0])/1e9 if len(pts)>1 else None)


PAYLOAD=r'''
import ctypes,glob,subprocess,threading,time
before=stock_snapshot();require_stock(before);require_private_idle();owned_directory(DIRECTORY)
clip=DIRECTORY+'/input.mp4'
if os.path.islink(clip) or digest(clip)!=DIGEST or os.path.getsize(clip)>16777216:raise ValueError('Fixture identity differs')
def any_vsp():
 for fd in glob.glob('/proc/[0-9]*/fd/*'):
  try:
   if 'sprd_vsp' in os.readlink(fd):return True
  except OSError:pass
 return False
if any_vsp():raise ValueError('Decoder already in use')
vendor_paths=('/usr/lib/gstreamer-1.0/libgstomx.so','/usr/lib/libomx_avcdec_hw_sprd.so')
vendor={p:digest(p) for p in vendor_paths}
if vendor[vendor_paths[1]]!='10f78010d85ec6d93fce94e7ddf05fc9a783237aa59dff8bda2df7077badbe14':raise ValueError('Different vendor decoder')
env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_','P011_'))}
env.update(GST_REGISTRY=DIRECTORY+'/gst-registry.bin',GST_REGISTRY_FORK='no',GST_DEBUG='0',GST_DEBUG_NO_COLOR='1')
args=['/usr/bin/gst-launch-1.0','-v','filesrc','location='+clip,'!','qtdemux','!','h264parse','!','omxh264dec','!',
      'identity','name=p011_count','silent=false','!','fpsdisplaysink','video-sink=fakesink','text-overlay=false',
      'silent=false','fps-update-interval=500','sync=true']
parent=os.getpid()
def limits():
 # This firmware omits Python resource; use the existing ARM libc limit ABI.
 # Linux RLIMIT_CORE=4, RLIMIT_CPU=0, unsigned-long rlim_t on this ARMv7 ABI.
 class Limit(ctypes.Structure):_fields_=[('cur',ctypes.c_ulong),('max',ctypes.c_ulong)]
 libc=ctypes.CDLL(None)
 if libc.setrlimit(4,ctypes.byref(Limit(0,0))) or libc.setrlimit(0,ctypes.byref(Limit(30,35))) or libc.prctl(1,15,0,0,0):os._exit(98)
 if os.getppid()!=parent:os._exit(99)
child=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,preexec_fn=limits)
identity_start=None;samples=[];hardware=False;vsp=False;sampling_errors=0;sampling_error_details=[];finished=threading.Event()
def sample():
 global identity_start,hardware,vsp,sampling_errors
 while not finished.wait(.2):
  try:
   p='/proc/'+str(child.pid);ident=identity(child.pid)
   if ident['exe']!='/usr/bin/gst-launch-1.0':raise ValueError('Unexpected process')
   if identity_start is None:identity_start=ident['starttime']
   if ident['starttime']!=identity_start:raise ValueError('PID reused')
   fields=open(p+'/stat').read(4096).rsplit(')',1)[1].split()
   samples.append((time.monotonic(),int(fields[11])+int(fields[12]),int(fields[21])*os.sysconf('SC_PAGE_SIZE')//1024))
   maps=open(p+'/maps').read(262144)
   hardware=hardware or all(name in maps for name in vendor_paths)
   for fd in glob.glob(p+'/fd/*'):
    try:vsp=vsp or 'sprd_vsp' in os.readlink(fd)
    except OSError:pass
  except (OSError,ValueError) as error:
   if child.poll() is None:
    sampling_errors+=1
    if len(sampling_error_details)<8:
     sampling_error_details.append(dict(kind=type(error).__name__,errno=getattr(error,'errno',None),after_samples=len(samples)))
thread=threading.Thread(target=sample);thread.start();began=time.monotonic();timed_out=False;forced=False
try:
 try:o,e=child.communicate(timeout=24)
 except subprocess.TimeoutExpired:
  timed_out=True;child.terminate()
  try:o,e=child.communicate(timeout=3)
  except subprocess.TimeoutExpired:forced=True;child.kill();o,e=child.communicate(timeout=3)
finally:finished.set();thread.join(2)
elapsed=time.monotonic()-began
# Vendor printf is very verbose even with GST_DEBUG=0. Preserve complete raw
# stdout/stderr within an explicit 8 MiB export bound and keep measurement
# lines separately. Do not mistake vendor text for FPS evidence.
if len(o)>8388608 or len(e)>8388608:raise ValueError('Excess raw pipeline output')
selected=b'\n'.join(line for line in o.splitlines() if b'/GstIdentity:p011_count' in line or
                    b'/GstFPSDisplaySink:' in line and b'last-message = ' in line or b'Got EOS from element' in line)
if len(selected)>1048576:raise ValueError('Excess measurement output')
after=stock_snapshot();require_stock(after);require_private_idle()
span=samples[-1][0]-samples[0][0] if len(samples)>1 else 0
cpu=(samples[-1][1]-samples[0][1])/os.sysconf('SC_CLK_TCK')/span*100 if span>0 else None
print('RESULT='+repr(dict(exit=child.returncode,timeout=timed_out,forced=forced,elapsed_seconds=elapsed,
 stdout_raw=o,stderr_raw=e,selected_stdout=selected,
 stdout_bytes=len(o),stderr_bytes=len(e),stdout_sha256=hashlib.sha256(o).hexdigest(),stderr_sha256=hashlib.sha256(e).hexdigest(),
 stdout_prefix_only=False,stderr_prefix_only=False,
 stock_unchanged=before==after,vendor_unchanged=vendor=={p:digest(p) for p in vendor_paths},
 decoder_library_observed=hardware,vsp_fd_observed=vsp,decoder_idle_after=not any_vsp(),sample_count=len(samples),
 sampling_errors=sampling_errors,sampling_error_details=sampling_error_details,sampler_joined=not thread.is_alive(),mean_cpu_percent=cpu,
 peak_rss_kb=max([v[2] for v in samples]+[0]))))
'''


def assess(report):
    p=report['pipeline'];fps=p.get('final_reported_average_fps')
    return bool(report.get('exit')==0 and not report.get('timeout') and not report.get('forced') and
                all(report.get(k) is True for k in ('stock_unchanged','vendor_unchanged','decoder_library_observed',
                    'vsp_fd_observed','decoder_idle_after','sampler_joined','temporary_directory_removed')) and
                report.get('sampling_errors')==0 and report.get('sample_count',0)>=40 and
                all(p.get(k) is True for k in ('timestamps_complete','caps_verified','eos')) and
                p.get('reported_drops')==0 and p.get('rate_samples',0)>=15 and
                type(fps) in (int,float) and 57<=fps<=63 and 14<=report.get('elapsed_seconds',0)<=18)


def main():
    from awake_trial import Adb,BASE,ROOT,NATIVE,result_from
    from ion_copy_trial import IDLE_GATE
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,choices=tuple(SHAPES),required=True);a=p.parse_args()
    w,h=a.width,SHAPES[a.width]
    out=ROOT/'logs'/('BiliP011-ScreenRate-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True)
    fixture=out/'input.mp4';ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:raise ValueError('Host video tools missing')
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'testsrc2=size='+str(w)+'x'+str(h)+':rate=60','-frames:v',str(FRAMES),'-an','-c:v','libx264',
                    '-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-bf','2','-g','60','-keyint_min','60',
                    '-sc_threshold','0','-movflags','+faststart',str(fixture)],check=True,timeout=60)
    raw=fixture.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    streams=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_streams','-of','json',str(fixture)],timeout=10))['streams']
    s=streams[0]
    if len(streams)!=1 or (s.get('codec_name'),s.get('width'),s.get('height'),s.get('r_frame_rate'),s.get('nb_frames'))!=('h264',w,h,'60/1',str(FRAMES)) or len(raw)>16777216:raise ValueError('Unexpected generated fixture')
    report=dict(width=w,height=h,source_fps=60,fixture_sha256=digest,fixture_bytes=len(raw),synthetic=True,
                screen_display_tested=False,audio_tested=False,bili_stream_tested=False,frequency_changed=False,
                source_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest())
    directory='/mnt/data/p011-toolbox/screen-rate-probe-'+secrets.token_hex(12);adb=Adb(out)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE
    prefix='DIRECTORY='+repr(directory)+'\nDIGEST='+repr(digest)+'\n'
    helper=out/'probe-helper.py';helper.write_bytes((safety+'\n'+prefix+PAYLOAD).encode('utf-8'))
    helper_sha=hashlib.sha256(helper.read_bytes()).hexdigest()
    try:
        result_from(adb.python('prepare',safety+'\n'+prefix+'\nrequire_stock(stock_snapshot())\nowned_directory("/mnt/data/p011-toolbox")\nassert not os.path.lexists(DIRECTORY)\nos.mkdir(DIRECTORY,0o700)\nprint("RESULT="+repr(dict(prepared=True)))'))
        adb.run('push-generated-fixture',['push',str(fixture),directory+'/input.mp4'])
        adb.run('push-owned-helper',['push',str(helper),directory+'/probe-helper.py'])
        loader=safety+'\n'+prefix+'\nHELPER_SHA='+repr(helper_sha)+r'''
import stat
require_stock(stock_snapshot());owned_directory(DIRECTORY)
path=DIRECTORY+'/probe-helper.py';info=os.lstat(path)
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>65536 or digest(path)!=HELPER_SHA:raise ValueError('Owned helper differs')
exec(compile(open(path,'rb').read(),path,'exec'))
'''
        result=result_from(adb.python('finite-generated-60fps',loader,timeout=38))
        stdout=result.pop('stdout_raw');stderr=result.pop('stderr_raw');selected=result.pop('selected_stdout')
        (out/'pipeline.stdout.raw').write_bytes(stdout);(out/'pipeline.stderr.raw').write_bytes(stderr)
        (out/'pipeline.measurements.raw').write_bytes(selected)
        report.update(result);report['pipeline']=parse_output(selected,w,h)
    except Exception as error:
        report['host_error_kind']=type(error).__name__
        raise
    finally:
        cleanup=safety+'\n'+prefix+'\nHELPER_SHA='+repr(helper_sha)+r'''
import stat
require_stock(stock_snapshot());require_private_idle()
if os.path.lexists(DIRECTORY):
 owned_directory(DIRECTORY)
 for name in os.listdir(DIRECTORY):
  path=DIRECTORY+'/'+name;info=os.lstat(path)
  if name not in ('input.mp4','gst-registry.bin','probe-helper.py') or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>16777216:raise ValueError('Unexpected cleanup file')
  if name=='input.mp4' and digest(path)!=DIGEST:raise ValueError('Fixture changed before cleanup')
  if name=='probe-helper.py' and digest(path)!=HELPER_SHA:raise ValueError('Helper changed before cleanup')
 for name in os.listdir(DIRECTORY):os.unlink(DIRECTORY+'/'+name)
 os.rmdir(DIRECTORY)
print('RESULT='+repr(dict(temporary_directory_removed=not os.path.lexists(DIRECTORY))))
'''
        report.update(result_from(adb.python('exact-owned-cleanup',cleanup)))
        report['passed']=assess(report) if 'pipeline' in report else False
        body=json.dumps(report,indent=2).encode('ascii');(out/'result.json').write_bytes(body)
        archive=out.with_name(out.name+'-safe.zip')
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
            z.writestr('result.json',body);z.writestr('SHA256.json',json.dumps({'result.json':hashlib.sha256(body).hexdigest()}))
        with zipfile.ZipFile(archive) as z:
            if z.testzip() or hashlib.sha256(z.read('result.json')).hexdigest()!=json.loads(z.read('SHA256.json'))['result.json']:raise ValueError('Archive verification failed')
        print(json.dumps(report,indent=2));print('SAFE_RESULT_ZIP='+str(archive));print('ZIP_SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
