"""35-second muted exact-worker seek/rate test. No window or stock UI replacement."""
import argparse,datetime,hashlib,json,pathlib,re,secrets

PROBE_SOURCES=('probes/hardware_seek_probe.cpp','client/hardware_client.hpp',
               'client/hardware_protocol.hpp','build/build_seek_probe.py','host/hardware_seek_trial.py',
               'probes/gstomx-output-pool.conf','host/private_omx_artifact.py','client/hardware_clock.hpp',
               'host/fused_worker_artifact.py','host/memion_observer_artifact.py')

def probe_sources(base):
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in PROBE_SOURCES}

def validate_probe(base):
    meta=json.loads((base/'out/hardware-seek-probe.build.json').read_text())
    binary=base/'out/hardware-seek-probe'
    if meta.get('schema')!=1 or meta.get('sources')!=probe_sources(base):raise ValueError('Stale probe source')
    raw=binary.read_bytes()
    if binary.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40 or hashlib.sha256(raw).hexdigest()!=meta.get('binary_sha256'):raise ValueError('Stale/non-ARM probe')
    return binary,meta['binary_sha256']

PAYLOAD=r'''
import hashlib,os,stat,sys,subprocess,re
sys.path.insert(0,ROOT)
import service,config,awake_trial as trial
from native_safety import stock_snapshot,require_stock
trial.verify();before=stock_snapshot();require_stock(before)
if any(p['exe'].startswith('/mnt/data/p011-toolbox/') for p in trial.procs()):raise ValueError('Another private native process is running')
for path,pin in OBSERVER_PINS.items():
 if hashlib.sha256(open(path,'rb').read()).hexdigest()!=pin:raise ValueError('Observer vendor ABI differs')
for name,digest in HASHES.items():
 path=DIRECTORY+'/'+name;info=os.lstat(path)
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Unsafe probe file')
 with open(path,'rb') as f:
  if hashlib.sha256(f.read()).hexdigest()!=digest:raise ValueError('Probe identity mismatch')
 os.chmod(path,0o700)
b=service.Backend(ROOT,config.MEDIA+'/bin/bili-api','','/mnt/data/p011-toolbox/bili-account',dict(os.environ,LD_LIBRARY_PATH=config.MEDIA+'/lib'),lifetime=60)
report={'window_opened':False,'stock_ui_replaced':False,'audible_audio_requested':False,'physical_acceptance':False,'output_pool_probe':POOL}
factory={p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in ('/etc/xdg/gstomx.conf','/etc/gstomx.conf') if os.path.isfile(p)}
try:
 if PRIVATE:
  import ctypes
  plugin=ctypes.CDLL(DIRECTORY+'/libgstomx.so');report['copy_checks']=plugin.p011_omx_copy_selftest();report['copy_mode']=plugin.p011_omx_copy_mode()
  report['profile_checks']=plugin.p011_omx_profile_selftest()
  report['parallel_checks']=plugin.p011_omx_parallel_selftest()
  if report['copy_checks']!=17408 or report['profile_checks']!=8 or report['parallel_checks']!=1620 or report['copy_mode']!=MODE:raise ValueError('Private selftest failed')
  if FUSED:
   report['half_checks']=plugin.p011_omx_half_selftest()
   if report['half_checks']!=2016:raise ValueError('Private filter selftest failed')
 if POOL:
  sections=[re.search(r'(?ms)^\[omxh264dec\]\s*\n(.*?)(?=^\[|\Z)',open(p).read()) for p in factory]
  expected=open(DIRECTORY+'/gstomx.conf').read().split('[omxh264dec]\n',1)[1].strip().replace('hacks=','hacks=no-disable-outport;')
  if len(sections)!=1 or not sections[0] or sections[0].group(1).strip()!=expected:raise ValueError('Factory workaround differs')
 d=b.helper('detail',{'kind':'video','bvid':BV})
 stream=b.helper('play',service.safe_args('play',dict(d['parts'][0],quality=QUALITY,codec=7)))
 if stream.get('quality')!=QUALITY or stream.get('codec')!=7:raise ValueError('Requested stream not available')
 report.update({'quality':QUALITY,'width':stream.get('width'),'height':stream.get('height'),'rate_probe':RATE})
 init={k:stream[k] for k in ('video','audio','width','height')}
 init['rate_probe']=RATE
 init['private_omx_probe']=PRIVATE
 init['nonref_probe']=NONREF
 init['nonref_keep_every']=KEEP
 init['fused_half_probe']=FUSED
 init['throughput_probe']=THROUGHPUT
 init['ion_observe']=bool(OBSERVER_PINS)
 env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_'))}
 env['P011_SEEK_PROBE_ROOT']=DIRECTORY
 if POOL:env['XDG_CONFIG_HOME']=DIRECTORY
 parent=os.getpid()
 child=subprocess.Popen([DIRECTORY+'/hardware-seek-probe',str(parent)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,preexec_fn=lambda:trial.child_limits(parent))
 try:o,e=child.communicate(service.json.dumps(init).encode('ascii')+b'\n',timeout=52)
 except subprocess.TimeoutExpired:
  child.kill();o,e=child.communicate();report['timeout']=True
 report['child_exit']=child.returncode
 for line in o.splitlines():
  if line.startswith(b'PROBE='):
   v=service.json.loads(line[6:].decode('ascii'))
   # Only exact worker/probe-generated numerical structures may be exported.
   def numeric(x):
    return type(x) in (bool,int,float) or type(x) is dict and all(type(k) is str and numeric(v) for k,v in x.items())
   if not numeric(v):raise ValueError('Non-numeric probe evidence')
   report['probe']=v
 report['suppressed_stderr_bytes']=len(e)
except Exception as ex:report['error_type']=type(ex).__name__
finally:
 b.close()
 leftovers=[p for p in trial.procs() if p['exe'] in (DIRECTORY+'/bili-hw',DIRECTORY+'/hardware-seek-probe') and trial.environment(p).get('P011_SEEK_PROBE_ROOT')==DIRECTORY]
 report['leftover_workers']=len(leftovers)
 for p in leftovers:trial.terminate(p,kill=True,grace=15)
after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
report['factory_config_unchanged']=all(hashlib.sha256(open(p,'rb').read()).hexdigest()==h for p,h in factory.items())
report['observer_vendor_unchanged']=all(hashlib.sha256(open(p,'rb').read()).hexdigest()==h for p,h in OBSERVER_PINS.items())
left=[]
for name in os.listdir(DIRECTORY):
 path=DIRECTORY+'/'+name
 if name not in ('hardware-seek-probe','bili-hw','gst-hw-registry.bin','gstomx.conf','libgstomx.so','libmemion-observer.so') or not stat.S_ISREG(os.lstat(path).st_mode):left.append(name)
if not left:
 for name in os.listdir(DIRECTORY):os.unlink(DIRECTORY+'/'+name)
 os.rmdir(DIRECTORY)
report['owned_probe_directory_removed']=not os.path.exists(DIRECTORY)
print('RESULT='+ascii(report))
'''

def main():
    from awake_trial import Adb,BASE,ROOT,NATIVE,check_bundle,result_from,archive
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True)
    p.add_argument('--quality',type=int,choices=(16,64,80,116),default=16)
    p.add_argument('--bvid',choices=('BV1Da411Y7U4','BV1gi4y1V7Xx'),default='BV1Da411Y7U4')
    p.add_argument('--rate-probe',action='store_true')
    p.add_argument('--output-pool-probe',action='store_true',help='Explicit private config experiment; never changes factory configuration')
    p.add_argument('--private-omx',type=pathlib.Path,help='Exact private source-only plugin artifact; finite diagnostic only')
    p.add_argument('--nonref-probe',action='store_true',help='Explicit finite high-fps disposable-frame experiment, not a production/default setting')
    p.add_argument('--nonref-keep-every',type=int,choices=(0,2,3),default=0)
    p.add_argument('--worker-artifact',type=pathlib.Path,help='Explicit source-checked diagnostic worker; does not replace the media bundle')
    p.add_argument('--fused-half-probe',action='store_true',help='Explicit private full-frame-count copy/filter experiment')
    p.add_argument('--throughput-probe',action='store_true',help='Muted unclocked no-QoS diagnostic ONLY; never a playback pass')
    p.add_argument('--ion-observer',type=pathlib.Path,help='Pinned read-only MemIon argument observer in this diagnostic child only')
    a=p.parse_args()
    if a.nonref_probe and (not a.private_omx or a.quality!=116):p.error('Non-reference experiment requires private OMX and explicit q116')
    if a.nonref_keep_every and not a.nonref_probe:p.error('Non-reference sample ratio requires the explicit probe')
    if a.worker_artifact and not a.private_omx:p.error('Diagnostic worker requires private OMX')
    if a.fused_half_probe and (not a.private_omx or not a.worker_artifact or a.nonref_probe):p.error('Fused experiment requires private worker/OMX and retains every input frame')
    if a.throughput_probe and (not a.rate_probe or not a.private_omx or not a.worker_artifact or a.nonref_probe or a.output_pool_probe):p.error('Throughput diagnostic requires rate/private worker/OMX without other experiments')
    if a.ion_observer and (not a.private_omx or a.output_pool_probe or a.nonref_probe):p.error('Observer requires isolated private OMX without unrelated experiments')
    binary,digest=validate_probe(BASE);meta,_=check_bundle(a.bundle)
    observer=None;observer_meta=None
    if a.ion_observer:
        from memion_observer_artifact import validate as validate_observer
        observer,observer_meta=validate_observer(BASE,a.ion_observer)
    plugin_path=None;plugin_meta=None
    if a.private_omx:
        if a.output_pool_probe:raise ValueError('Do not combine independent experiments')
        from private_omx_artifact import validate
        plugin_path,plugin_meta=validate(BASE,a.private_omx)
        if plugin_meta['fused_half']!=a.fused_half_probe:raise ValueError('Explicit fused mode does not match plugin')
    media=pathlib.Path(meta['media_local']);manifest=json.loads((media/'manifest.json').read_text())
    worker=media/'bin/bili-hw';worker_sha=hashlib.sha256(worker.read_bytes()).hexdigest()
    if worker.is_symlink() or worker_sha!=manifest['bin/bili-hw']['sha256']:raise ValueError('Worker identity mismatch')
    if a.worker_artifact:
        from fused_worker_artifact import validate as validate_worker
        worker,worker_meta=validate_worker(BASE,a.worker_artifact);worker_sha=worker_meta['sha256']
    out=ROOT/'logs'/('BiliP011-HardwareSeek-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();adb=Adb(out)
    directory='/mnt/data/p011-toolbox/bili-seek-probe-'+secrets.token_hex(12)
    (out/'host-identity.json').write_text(json.dumps({'scratch':directory,'driver_sha256':digest,'worker_sha256':worker_sha,'media':media.name,'worker_artifact':a.worker_artifact.name if a.worker_artifact else None,'private_plugin_sha256':plugin_meta['sha256'] if plugin_meta else None},indent=2),encoding='utf-8')
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    result_from(adb.python('prepare',safety+'\nrequire_stock(stock_snapshot())\nowned_directory("/mnt/data/p011-toolbox",False)\nos.mkdir('+repr(directory)+',0o700)\nprint("RESULT="+repr({"created":True}))'))
    adb.run('push-driver',['push',str(binary),directory+'/hardware-seek-probe'])
    adb.run('push-worker',['push',str(worker),directory+'/bili-hw'])
    hashes={'hardware-seek-probe':digest,'bili-hw':worker_sha}
    if a.output_pool_probe:
        config=BASE/'probes/gstomx-output-pool.conf';hashes['gstomx.conf']=hashlib.sha256(config.read_bytes()).hexdigest()
        adb.run('push-private-config',['push',str(config),directory+'/gstomx.conf'])
    if plugin_path:
        hashes['libgstomx.so']=plugin_meta['sha256'];adb.run('push-private-plugin',['push',str(plugin_path),directory+'/libgstomx.so'])
    if observer:
        hashes['libmemion-observer.so']=observer_meta['sha256'];adb.run('push-observer',['push',str(observer),directory+'/libmemion-observer.so'])
    code='ROOT='+repr(meta['remote'])+'\nDIRECTORY='+repr(directory)+'\nHASHES='+repr(hashes)+'\n'
    code+='OBSERVER_PINS='+repr(observer_meta['pins'] if observer_meta else {})+'\n'
    code+='QUALITY='+repr(a.quality)+'\nBV='+repr(a.bvid)+'\nRATE='+repr(a.rate_probe)+'\nPOOL='+repr(a.output_pool_probe)+'\nPRIVATE='+repr(bool(plugin_path))+'\nMODE='+repr(plugin_meta['copy_mode'] if plugin_meta else 0)+'\nNONREF='+repr(a.nonref_probe)+'\nKEEP='+repr(a.nonref_keep_every)+'\nFUSED='+repr(a.fused_half_probe)+'\nTHROUGHPUT='+repr(a.throughput_probe)+'\n'+PAYLOAD
    report=result_from(adb.python('bounded-no-window-seek',code,timeout=80))
    report['driver_sha256']=digest;report['worker_sha256']=worker_sha;report['media_identity']=media.name;report['nonref_probe']=a.nonref_probe
    report['fused_half_probe']=a.fused_half_probe
    report['unsynchronized_throughput_probe']=a.throughput_probe
    if plugin_meta:report['private_plugin_sha256']=plugin_meta['sha256'];report['private_plugin_neon']=plugin_meta['neon'];report['private_plugin_copy_mode']=plugin_meta['copy_mode']
    report['passed']=report.get('stock_unchanged') is True and report.get('factory_config_unchanged') is True and report.get('child_exit')==0 and report.get('probe',{}).get('passed') is True and report.get('owned_probe_directory_removed') is True and report.get('leftover_workers')==0 and not report.get('timeout')
    if observer:
        report['observer_sha256']=observer_meta['sha256']
        report['read_only_ion_observation']=True
        report['passed']=report['passed'] and report.get('observer_vendor_unchanged') is True and bool(report.get('probe',{}).get('ion_observations'))
    if a.fused_half_probe:
        status=report.get('probe',{}).get('worker_status',{})
        scaled=max(report.get('width',0),report.get('height',0))>960
        report['fused_output_verified']=status.get('fused_half_probe') is True and status.get('encoded_nonref_skipped')==0 and (not scaled or status.get('fused_half_frames',0)>0)
        report['passed']=report['passed'] and report['fused_output_verified']
    report['passed_scope']=('unclocked_maximum_throughput_not_playback' if a.throughput_probe else
                            'no_window_worker_rate_only' if a.rate_probe else 'no_window_paused_seek_resume_only')
    if a.throughput_probe:report['playback_rate_passed']=False
    if a.rate_probe and 'rate' in report.get('probe',{}):
        rate=report['probe']['rate'];source=rate.get('source_fps',0)
        meets_rate=bool(report['passed'] and source>0 and rate['consumed_fps']>=source*.95 and rate['decoder_drops']+rate['drops']<=source*rate['elapsed_seconds']*.01)
        if a.throughput_probe:
            status=report.get('probe',{}).get('worker_status',{})
            report['passed']=report['passed'] and status.get('unsynchronized_throughput_probe') is True and status.get('encoded_nonref_skipped')==0
            report['unclocked_rate_meets_source']=meets_rate and report['passed']
            report['passed_scope']='unclocked_maximum_throughput_not_playback'
            report['playback_rate_passed']=False
        else:report['worker_rate_met']=meets_rate
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));print('LOG_DIR='+str(out));archive(out)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
