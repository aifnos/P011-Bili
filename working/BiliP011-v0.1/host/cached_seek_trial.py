"""Finite real-Bili cache experiment. Reuses the audited worker/stream driver."""
import argparse,datetime,hashlib,json,pathlib,re,secrets
from hardware_seek_trial import PAYLOAD as ORIGINAL_PAYLOAD
from cached_worker_artifact import validate
from ion_copy_trial import IDLE_GATE
from omx_format_profile import inspect_format
from cached_compat_evidence import evaluate as evaluate_compat
from vsp_readback import evaluate_readback

def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('Cached stream controller anchor changed')
    return source.replace(old,new,1)

def payload():
    source=ORIGINAL_PAYLOAD
    source=replace_once(source,'for path,pin in OBSERVER_PINS.items():','for path,pin in VENDOR_PINS.items():')
    start=source.index(' if PRIVATE:\n');end=source.index(' if POOL:\n',start)
    source=source[:start]+r'''
 if not PRIVATE or not FUSED or POOL:raise ValueError('Unexpected cache probe options')
 if COMPAT:
  if THROUGHPUT or CACHE_MODE!='cached' or not NONREF or KEEP not in (0,2,3) or QUALITY!=116:raise ValueError('Unexpected cached compatibility options')
 elif NONREF or KEEP:raise ValueError('Ordinary cache observation retains all input frames')
 pre_env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_','P011_CACHE_'))}
 pre_env.update(P011_SEEK_PROBE_ROOT=DIRECTORY,P011_CACHE_PROBE_ROOT=DIRECTORY,P011_CACHE_PROBE_MODE=CACHE_MODE,
                GST_PLUGIN_PATH_1_0=DIRECTORY,GST_REGISTRY=DIRECTORY+'/gst-hw-registry.bin',GST_REGISTRY_FORK='no',GST_DEBUG='0')
 pre_parent=os.getpid()
 pre=subprocess.Popen([DIRECTORY+'/bili-hw','--preflight'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=pre_env,preexec_fn=lambda:trial.child_limits(pre_parent))
 try:po,pe=pre.communicate(timeout=20)
 except subprocess.TimeoutExpired:
  pre.kill();po,pe=pre.communicate(timeout=3);raise ValueError('Cached worker preflight timed out')
 records=[line for line in po.splitlines() if line.startswith(b'{') and line.endswith(b'}')]
 if pre.returncode or len(records)!=1 or service.json.loads(records[0].decode('ascii')).get('ok') is not True:raise ValueError('Cached worker preflight failed')
 report['cache_worker_preflight']=True
''' +source[end:]
    source=replace_once(source," init['rate_probe']=RATE"," if (init['width'],init['height'])!=(1920,1080):raise ValueError('Stream outside verified cache geometry')\n init['output_cache_mode']=CACHE_MODE\n init['rate_probe']=RATE")
    source=replace_once(source," init['nonref_probe']=NONREF"," init['cached_compat_probe']=COMPAT\n init['nonref_probe']=NONREF\n report['compat_probe_requested']=COMPAT\n if COMPAT:report['compat_keep_every']=KEEP")
    source=replace_once(source,"env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_'))}",
                        "env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_','P011_CACHE_'))}")
    source=replace_once(source,"report['observer_vendor_unchanged']=all(hashlib.sha256(open(p,'rb').read()).hexdigest()==h for p,h in OBSERVER_PINS.items())",
                        "report['cache_vendor_unchanged']=all(hashlib.sha256(open(p,'rb').read()).hexdigest()==h for p,h in VENDOR_PINS.items())")
    source=replace_once(source,"'libgstomx.so','libmemion-observer.so')","'libgstomx.so','libmemion-observer.so','cached-helper.py')")
    sampler=(pathlib.Path(__file__).with_name('worker_wait_sampler.py')).read_text(encoding='utf-8')
    format_checks=(pathlib.Path(__file__).with_name('omx_format_profile.py')).read_text(encoding='utf-8')
    source=format_checks+'\n'+sampler+'\n'+source
    source=replace_once(source,' try:o,e=child.communicate(',
                        " sampler=WorkerWaitSampler(child.pid,DIRECTORY) if SAMPLE_WAITS else None\n try:o,e=child.communicate(")
    source=replace_once(source," report['child_exit']=child.returncode",
                        " finally:\n  if sampler is not None:report['wait_sample']=sampler.finish()\n report['child_exit']=child.returncode")
    source=replace_once(source," env['P011_SEEK_PROBE_ROOT']=DIRECTORY",
                        " env['P011_SEEK_PROBE_ROOT']=DIRECTORY\n env.pop('P011_VSP_WAIT_PROFILE',None)\n env.pop('P011_VSP_CLOCK_READBACK',None)\n if VSP_PROFILE:env['P011_VSP_WAIT_PROFILE']='1'\n if VSP_READBACK:env['P011_VSP_CLOCK_READBACK']='1'")
    source=replace_once(source," report['suppressed_stderr_bytes']=len(e)","""
 report['vsp_profile_requested']=VSP_PROFILE
 profiles=[line[len(b'P011_VSP_PROFILE='):] for line in e.splitlines() if line.startswith(b'P011_VSP_PROFILE=')]
 if profiles:
  if not VSP_PROFILE or len(profiles)!=1:raise ValueError('Unexpected VSP profile records')
  profile=service.json.loads(profiles[0].decode('ascii'))
  if type(profile) is not dict or not all(type(k) is str and type(v) is int and v>=0 for k,v in profile.items()):raise ValueError('Non-numeric VSP profile')
  report['vsp_profile']=profile
 report['format_profile_requested']=VSP_PROFILE
 formats=[line[len(b'P011_OMX_FORMAT='):] for line in e.splitlines() if line.startswith(b'P011_OMX_FORMAT=')]
 if formats:
  if not VSP_PROFILE or len(formats)!=1:raise ValueError('Unexpected OMX format records')
  format_profile=service.json.loads(formats[0].decode('ascii'))
  check_format_shape(format_profile)
 report['format_profile']=format_profile
 report['vsp_readback_requested']=VSP_READBACK
 readbacks=[line[len(b'P011_VSP_READBACK='):] for line in e.splitlines() if line.startswith(b'P011_VSP_READBACK=')]
 if readbacks:
  if not VSP_READBACK or len(readbacks)!=1:raise ValueError('Unexpected VSP readback records')
  readback=service.json.loads(readbacks[0].decode('ascii'))
  if type(readback) is not dict or not all(type(k) is str and type(v) is int and v>=0 for k,v in readback.items()):raise ValueError('Non-numeric VSP readback')
  report['vsp_readback']=readback
 report['suppressed_stderr_bytes']=len(e)
""")
    return source

def cleanup(adb,safety,directory,hashes):
    from awake_trial import result_from
    if not re.fullmatch('/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}',directory):raise ValueError('Unexpected exact scratch path')
    source=safety+'\nDIRECTORY='+repr(directory)+'\nHASHES='+repr(hashes)+r'''
import stat
before=stock_snapshot();require_stock(before);require_private_idle()
removed=[]
if os.path.lexists(DIRECTORY):
 owned_directory(DIRECTORY);names=os.listdir(DIRECTORY)
 for name in names:
  path=DIRECTORY+'/'+name;info=os.lstat(path)
  if name not in list(HASHES)+['gst-hw-registry.bin'] or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Unknown scratch content')
  if name in HASHES and digest(path)!=HASHES[name]:raise ValueError('Changed scratch identity')
 for name in names:os.unlink(DIRECTORY+'/'+name);removed.append(name)
 os.rmdir(DIRECTORY)
after=stock_snapshot();require_stock(after)
print('RESULT='+repr(dict(temporary_directory_removed=not os.path.lexists(DIRECTORY),removed_files=removed,stock_unchanged=before==after)))
'''
    return result_from(adb.python('independent-owned-cleanup',source))

def assess(report,mode,kind,sample_waits=False,vsp_profile=False,format_profile=False,compat_keep=None,vsp_readback=False):
    p=report.get('probe',{});final=p.get('cache_final',{});status=p.get('worker_status',{})
    required=('stock_unchanged','factory_config_unchanged','cache_vendor_unchanged','owned_probe_directory_removed','cache_worker_preflight')
    valid=all(report.get(key) is True for key in required) and report.get('child_exit')==0 and report.get('leftover_workers')==0 and not report.get('timeout') and p.get('passed') is True
    allocations=final.get('cache_registered',0);reads=final.get('cache_read_begin',0)
    valid=bool(valid and allocations>0 and reads>0 and final.get('cache_final') is True and final.get('cache_active')==0 and final.get('cache_sync_errors')==0 and final.get('cache_ownership_errors')==0 and final.get('cache_forgotten')==allocations and final.get('cache_read_end')==reads)
    valid=valid and final.get('cache_changed_allocations')==(allocations if mode=='cached' else 0) and final.get('cache_control_allocations')==(0 if mode=='cached' else allocations)
    valid=valid and status.get('output_cache_probe') is True and status.get('output_cache_enabled')==(mode=='cached')
    if compat_keep is None:
        valid=valid and status.get('encoded_nonref_skipped')==0 and not report.get('compat_probe_requested',False) and not status.get('cached_compat_probe',False)
    else:
        valid=valid and type(compat_keep) is int and compat_keep in (0,2,3) and mode=='cached' and kind in ('seek','rate')
        valid=valid and report.get('compat_probe_requested') is True and report.get('compat_keep_every')==compat_keep
        valid=valid and status.get('cached_compat_probe') is True and status.get('nonref_probe_active') is True and status.get('nonref_keep_every')==compat_keep and status.get('high_fps_compat') is True and status.get('encoded_nonref_skipped',0)>0 and status.get('unsynchronized_throughput_probe') is False
    if sample_waits:
        sample=report.get('wait_sample',{})
        valid=valid and sample.get('joined') is True and sample.get('worker_observed') is True and not sample.get('identity_rejected',True) and sample.get('samples',0)>=8 and bool(sample.get('threads'))
    if vsp_profile:
        v=report.get('vsp_profile',{})
        valid=valid and report.get('vsp_profile_requested') is True and v.get('poll_count',0)>0 and v.get('acquire_count',0)>0 and v.get('forward_errors',1)==0 and v.get('clock_errors',1)==0
        valid=valid and v.get('freq_config_calls',0)>0 and v.get('freq_config_success')==v.get('freq_config_calls') and v.get('freq_config_failed',1)==0 and v.get('freq_null',1)==0 and v.get('freq_other',1)==0
        valid=valid and v.get('timing_schema')==1 and v.get('gap_count',0)>0 and v.get('gap_clock_errors',1)==0
        valid=valid and v.get('cycle_schema')==2 and v.get('release_count',0)>0 and v.get('release_failed',1)==0
        valid=valid and v.get('cycle_count',0)==v.get('gap_count') and all(v.get(k,1)==0 for k in ('cycle_incomplete_polls','cycle_context_resets','cycle_order_resets','cycle_clock_errors'))
        roles=('poll','acquire','release')
        valid=valid and v.get('seq_contexts',1)==0 and all(v.get('seq_start'+str(j),-1)+sum(v.get('seq_e'+str(i)+str(j),-1) for i in range(3))==v.get(roles[j]+'_count') for j in range(3))
        valid=valid and 0<=v.get('cycle_max_extra_pairs',-1)<=v.get('cycle_extra_pairs',-1)<=v.get('seq_e12',-1)
    if format_profile:
        f=inspect_format(report['format_profile'],p.get('rate',{}).get('source_fps')) if 'format_profile' in report else {}
        valid=valid and report.get('format_profile_requested') is True and f.get('evidence_complete') is True
    if vsp_readback:
        r=evaluate_readback(report.get('vsp_readback'))
        report['vsp_readback_summary']=r
        valid=valid and vsp_profile and report.get('vsp_readback_requested') is True and r['evidence_complete'] is True
    report.update(passed=bool(valid),cache_mode=mode,kind=kind,playback_passed=False,physical_acceptance=False,
                  passed_scope='no_window_cached_worker_'+kind+'_only')
    if kind in ('rate','throughput'):
        rate=p.get('rate',{});fps=rate.get('source_fps',0)
        rate_met=bool(valid and compat_keep is None and fps>0 and rate.get('consumed_fps',0)>=fps*.95 and rate.get('drops',1e9)+rate.get('decoder_drops',1e9)<=fps*rate.get('elapsed_seconds',0)*.01)
        report['worker_rate_met']=rate_met if kind=='rate' else False
        report['unclocked_rate_meets_source']=rate_met if kind=='throughput' else False
        if compat_keep is not None:
            try:
                report['compatibility_rate_met']=evaluate_compat(rate,compat_keep,valid)['compatibility_rate_met']
                report['compatibility_evidence_valid']=True
            except ValueError:
                report.update(passed=False,compatibility_rate_met=False,compatibility_evidence_valid=False)
    return report

def main():
    from awake_trial import Adb,BASE,ROOT,NATIVE,check_bundle,result_from,archive
    parser=argparse.ArgumentParser();parser.add_argument('--artifact',type=pathlib.Path,required=True)
    parser.add_argument('--bundle',type=pathlib.Path,required=True);parser.add_argument('--mode',choices=('cached','uncached'),required=True)
    parser.add_argument('--kind',choices=('seek','rate','throughput'),default='seek')
    parser.add_argument('--quality',type=int,choices=(80,116),default=80)
    parser.add_argument('--bvid',choices=('BV1Da411Y7U4','BV1gi4y1V7Xx'),default='BV1Da411Y7U4')
    parser.add_argument('--sample-waits',action='store_true',help='Read-only exact-child scheduler/clock observation; never changes clocks')
    parser.add_argument('--profile-vsp',action='store_true',help='Time existing VSP calls in the private diagnostic executable; never change arguments')
    parser.add_argument('--readback-vsp',action='store_true',help='Opt-in bounded original GET after successful original frequency configuration; never adds frequency writes')
    parser.add_argument('--compat-keep',type=int,choices=(0,2,3),help='Separate explicit synchronized reduced-rate comparison; never a full-rate throughput test')
    args=parser.parse_args()
    if args.readback_vsp and (not args.profile_vsp or args.kind!='throughput'):parser.error('Readback requires explicit VSP-profiled throughput diagnostic')
    if args.compat_keep is not None and (args.kind=='throughput' or args.mode!='cached' or args.quality!=116):parser.error('Compatibility needs cached q116 and synchronized rate/seek')
    artifact=args.artifact.resolve();meta=validate(BASE,artifact);bundle,_=check_bundle(args.bundle)
    log=ROOT/'logs'/('BiliP011-CachedWorker-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));log.mkdir()
    print('LOG_DIR='+str(log),flush=True);adb=Adb(log);directory='/mnt/data/p011-toolbox/bili-seek-probe-'+secrets.token_hex(12)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE
    hashes=dict(meta['binaries'])
    values=dict(ROOT=bundle['remote'],DIRECTORY=directory,HASHES=hashes,VENDOR_PINS=meta['pins'],OBSERVER_PINS={},
                QUALITY=args.quality,BV=args.bvid,RATE=args.kind!='seek',POOL=False,PRIVATE=True,MODE=4,
                NONREF=args.compat_keep is not None,KEEP=args.compat_keep if args.compat_keep is not None else 0,COMPAT=args.compat_keep is not None,
                FUSED=True,THROUGHPUT=args.kind=='throughput',CACHE_MODE=args.mode,SAMPLE_WAITS=args.sample_waits,VSP_PROFILE=args.profile_vsp,VSP_READBACK=args.readback_vsp)
    script='\n'.join(key+'='+repr(value) for key,value in values.items())+'\n'+payload()
    helper=log/'cached-helper.py';helper.write_bytes(script.encode('utf-8'));hashes['cached-helper.py']=hashlib.sha256(helper.read_bytes()).hexdigest()
    (log/'identity.json').write_text(json.dumps(dict(artifact=artifact.name,binaries=meta['binaries'],directory=directory,hashes=hashes,kind=args.kind,mode=args.mode,quality=args.quality,bvid=args.bvid),indent=2))
    try:
        result_from(adb.python('prepare',safety+'\nrequire_stock(stock_snapshot())\nowned_directory("/mnt/data/p011-toolbox")\nassert not os.path.lexists('+repr(directory)+')\nos.mkdir('+repr(directory)+',0o700)\nprint("RESULT="+repr(dict(prepared=True)))'))
        for name in meta['binaries']:adb.run('push-'+name,['push',str(artifact/name),directory+'/'+name])
        adb.run('push-helper',['push',str(helper),directory+'/cached-helper.py'])
        loader=safety+'\nowned_directory('+repr(directory)+')\nHELPER='+repr(directory+'/cached-helper.py')+'\nEXPECTED='+repr(hashes['cached-helper.py'])+r'''
import stat
info=os.lstat(HELPER)
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>65536:raise ValueError('Unsafe helper')
raw=open(HELPER,'rb').read()
if hashlib.sha256(raw).hexdigest()!=EXPECTED:raise ValueError('Helper identity differs')
exec(compile(raw,HELPER,'exec'))
'''
        report=result_from(adb.python('bounded-cached-worker',loader,timeout=90))
        report=assess(report,args.mode,args.kind,args.sample_waits,args.profile_vsp,args.profile_vsp,args.compat_keep,args.readback_vsp);report.update(artifact=artifact.name,binaries=meta['binaries'],bvid=args.bvid)
        (log/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
        if not report['passed']:raise ValueError('Cached worker trial failed; original evidence retained')
    finally:
        try:(log/'cleanup.json').write_text(json.dumps(cleanup(adb,safety,directory,hashes),indent=2),encoding='utf-8')
        finally:archive(log)

if __name__=='__main__':main()
