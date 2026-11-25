"""Finite, muted fixed-content A/B probe. Not a full client acceptance run."""
import argparse,datetime,inspect,json,math,pathlib,statistics,subprocess,sys,time
from build_awake_trial import build,BASE,ROOT,NATIVE
from awake_trial import Adb,result_from,command,check_bundle
from client_results import archive_client
from frame_diagnostics import analyze as frame_diagnostics
from ddr_observation import read_ddr_state,summarize_ddr
from presentation_evidence import analyze as analyze_presentation

PROBE=r'''
import sys,time,os
sys.path.insert(0,ROOT)
import service,awake_trial as trial,config
row={'time':time.monotonic(),'player':{},'process':None,'complete':os.path.isfile(ROOT+'/result.json')}
try:row['actual_brightness']=int(open('/sys/class/backlight/sprd_backlight/actual_brightness').read(64))
except (OSError,ValueError):pass
try:row['cpu_khz']=int(open('/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq').read())
except (OSError,ValueError):pass
for key,path in (('ion_heaps_kb','/sys/kernel/ion/total_heaps_kb'),('ion_pools_kb','/sys/kernel/ion/total_pools_kb')):
 try:row[key]=int(open(path).read())
 except (OSError,ValueError):pass
for name in ('player-state.json','media-state.json'):
 try:
  v=service.json.loads(trial.read(ROOT+'/'+name,16384).decode('utf-8'))
  row['player'].update({k:x for k,x in v.items() if type(x) in (bool,int,float)})
 except (FileNotFoundError,ValueError):pass
for p in trial.procs():
 if p['exe']==config.MEDIA+'/bin/bili-player' and trial.alive(p) and trial.environment(p).get('P011_CLIENT_ROOT')==ROOT:
  fields=open('/proc/%s/stat'%p['pid']).read().rsplit(')',1)[1].split()
  row['process']={'pid':p['pid'],'start':int(fields[19]),'ticks':int(fields[11])+int(fields[12]),'hz':os.sysconf('SC_CLK_TCK'),'rss_kb':int(fields[21])*os.sysconf('SC_PAGE_SIZE')//1024}
  children=[]
  for child in trial.procs():
   if child['exe']==config.MEDIA+'/bin/bili-hw' and child['parent']==p['pid'] and trial.alive(child) and trial.environment(child).get('P011_CLIENT_ROOT')==ROOT:
    cf=open('/proc/%s/stat'%child['pid']).read().rsplit(')',1)[1].split()
    children.append({'pid':child['pid'],'start':int(cf[19]),'ticks':int(cf[11])+int(cf[12]),'rss_kb':int(cf[21])*os.sysconf('SC_PAGE_SIZE')//1024})
  row['process']['children']=children
  row['process']['ticks']+=sum(c['ticks'] for c in children)
  row['process']['rss_kb']+=sum(c['rss_kb'] for c in children)
print('RESULT='+repr(row))
'''


def metrics(samples):
    groups={'playing':[],'paused':[]}
    for a,b in zip(samples,samples[1:]):
        pa,pb=a.get('process'),b.get('process');s=b.get('player',{});dt=b['time']-a['time']
        if not pa or not pb or (pa['pid'],pa['start'])!=(pb['pid'],pb['start']) or not 0<dt<6:continue
        if [(c['pid'],c['start']) for c in pa.get('children',[])]!=[(c['pid'],c['start']) for c in pb.get('children',[])]:continue
        if s.get('position',0)<6 or not s.get('loaded'):continue
        key='paused' if s.get('paused') and a.get('player',{}).get('paused') else 'playing' if s.get('active') and a.get('player',{}).get('active') else None
        if key:groups[key].append({'cpu':(pb['ticks']-pa['ticks'])/pb['hz']/dt*100,'rss_kb':pb['rss_kb'],'drops':s.get('drops',0),'decoder_drops':s.get('decoder_drops',0),'position':s['position'],'time':b['time'],'submitted':s.get('submitted_frames'),'avsync_ms':abs(s.get('avsync',0))*1000,'source_fps':s.get('source_fps'),'cpu_khz':b.get('cpu_khz'),
                                   'compat':s.get('high_fps_compat') is True,'verified':s.get('hardware_verified') is True,'nonref_skipped':s.get('hardware_nonref_skipped',0),
                                   'cached_retention':s.get('hardware_cached_retention_active') is True,
                                   'keep_every':s.get('hardware_nonref_keep_every'),'encoded':s.get('hardware_encoded')})
    return {k:{'samples':len(v),'mean_cpu_percent':round(statistics.mean(x['cpu'] for x in v),2) if v else None,
               'peak_rss_kb':max((x['rss_kb'] for x in v),default=None),
               'dropped_frames_delta':v[-1]['drops']-v[0]['drops'] if v else None,
               'decoder_dropped_frames_delta':v[-1]['decoder_drops']-v[0]['decoder_drops'] if v else None,
               'source_fps':v[-1]['source_fps'] if v else None,
               'submitted_fps':round((v[-1]['submitted']-v[0]['submitted'])/(v[-1]['time']-v[0]['time']),2) if len(v)>1 and v[-1]['submitted'] is not None and v[0]['submitted'] is not None else None,
               'maximum_avsync_ms':round(max((x['avsync_ms'] for x in v),default=0),1),
               'high_fps_compat':bool(v) and all(x['compat'] and x['verified'] for x in v),
               'nonref_skipped_frames_delta':v[-1]['nonref_skipped']-v[0]['nonref_skipped'] if v else 0,
               'cached_retention_active':bool(v) and all(x['cached_retention'] and type(x['keep_every']) is int and x['keep_every']==2 for x in v),
               'encoded_frames_delta':v[-1]['encoded']-v[0]['encoded'] if v and all(type(x['encoded']) is int for x in v) else None,
               'cpu_clock_khz':sorted(set(x['cpu_khz'] for x in v if x['cpu_khz'] is not None)),
               'position_advance':round(v[-1]['position']-v[0]['position'],3) if len(v)>1 else 0,
               'wall_seconds':round(v[-1]['time']-v[0]['time'],3) if len(v)>1 else 0} for k,v in groups.items()}


def compatible_playback(playing,finite_passed):
    # A separate, explicitly reduced-frame-rate tier. NEVER replaces the
    # original >=95% source-rate gate or reclassifies intentional skips as
    # decoded/displayed frames. It is not evidence of physical audio/panel.
    keys=('submitted_fps','source_fps','maximum_avsync_ms','wall_seconds',
          'dropped_frames_delta','decoder_dropped_frames_delta','nonref_skipped_frames_delta')
    if not finite_passed or playing.get('high_fps_compat') is not True:return False
    if any(type(playing.get(k)) not in (int,float) or not math.isfinite(playing[k]) for k in keys):return False
    return bool(playing.get('samples',0)>=5 and playing['wall_seconds']>=10 and playing['source_fps']>45 and
                playing['submitted_fps']>=30 and playing['maximum_avsync_ms']<=150 and playing['nonref_skipped_frames_delta']>0 and
                playing['dropped_frames_delta']>=0 and playing['decoder_dropped_frames_delta']>=0 and
                playing['dropped_frames_delta']+playing['decoder_dropped_frames_delta']<=playing['source_fps']*playing['wall_seconds']*.01)


def paused_capture_policy(samples):
    captured=False
    for row in samples:
        state=row.get('player',{})
        count=state.get('capture_count',0)
        if type(count) is not int or count<0:return False
        if state.get('active') and count:return False
        if state.get('paused') is True and count:captured=True
    return captured


def frame_rate_states_verified(samples):
    # The two status files are individually atomic, not one transaction. Audit
    # stable adjacent samples only; do not interpret a pause-edge read as a
    # playback measurement or require a made-up nonzero rate while paused.
    counts={1:0,3:0}
    for a,b in zip(samples,samples[1:]):
        pa,pb=a.get('process'),b.get('process');sa,sb=a.get('player',{}),b.get('player',{})
        if not pa or not pb or (pa['pid'],pa['start'])!=(pb['pid'],pb['start']):continue
        if not 0<b['time']-a['time']<6:continue
        if any(s.get('loaded') is not True or s.get('switch_pending') is True or
               type(s.get('position')) not in (int,float) or not math.isfinite(s['position']) or s['position']<6 for s in (sa,sb)):continue
        expected=1 if all(s.get('paused') is True and s.get('active') is False for s in (sa,sb)) else \
                 3 if all(s.get('active') is True and s.get('paused') is False for s in (sa,sb)) else None
        if expected is None:continue
        if type(sb.get('stats_rate_state')) is not int or sb['stats_rate_state']!=expected:return False
        counts[expected]+=1
    return counts[1]>=3 and counts[3]>=5


def fused_copy_verified(samples):
    count=0;previous=None
    for row in samples:
        s=row.get('player',{})
        if s.get('active') is not True or s.get('loaded') is not True:continue
        position=s.get('position')
        if type(position) not in (int,float) or not math.isfinite(position):return False
        if position<6:continue
        keys=('source_width','source_height','hardware_output_width','hardware_output_height','hardware_fused_frames')
        if any(type(s.get(k)) is not int or s[k]<=0 for k in keys):return False
        w,h=s['source_width'],s['source_height']
        if max(w,h)<=960 or max(w,h)>1920 or w*h>1920*1080 or (w&1) or (h&1):return False
        if any(s.get(k) is not True for k in ('hardware_verified','hardware_private_plugin','hardware_fused_copy')):return False
        if s['hardware_output_width']!=w//4*2 or s['hardware_output_height']!=h//4*2:return False
        frames=s['hardware_fused_frames']
        # Repeated stale status or a reset counter must not prove that the
        # fixed benchmark really processed new frames through this path.
        if previous and (frames<=previous[0] or position<=previous[1] or (w,h)!=previous[2]):return False
        previous=(frames,position,(w,h))
        count+=1
    return count>=5


def output_cache_verified(samples,mode):
    if mode not in ('cached','fallback'):return False
    observed=0;previous=0
    for row in samples:
        state=row.get('player',{})
        if state.get('active') is not True or state.get('loaded') is not True or state.get('position',0)<6:continue
        if any(state.get(k) is not True for k in ('hardware_verified','hardware_private_plugin','hardware_cache_feature','hardware_cache_vendor_verified')):return False
        if state.get('hardware_output_cache_enabled')!=(mode=='cached'):return False
        for key in ('hardware_cache_sync_errors','hardware_cache_ownership_errors'):
            if state.get(key)!=0:return False
        prefix='hardware_cache_' if mode=='cached' else 'hardware_cache_fallback_'
        reads=state.get(prefix+'read_begin');registered=state.get(prefix+'registered')
        if type(reads) is not int or type(registered) is not int or reads<=previous or registered<=0:return False
        if mode=='fallback' and state.get('hardware_cache_changed_allocations')!=0:return False
        if mode=='cached' and (state.get('source_width'),state.get('source_height'))!=(1920,1080):return False
        previous=reads;observed+=1
    return observed>=5


def cached_retention_verified(samples,playing,finite_passed):
    # Extra candidate gate, not a relaxation of full-source smoothness. Prove
    # both the active cache policy and displayed/submitted retained-frame rate.
    if not compatible_playback(playing,finite_passed) or not output_cache_verified(samples,'cached') or playing.get('cached_retention_active') is not True:
        return False
    encoded=playing.get('encoded_frames_delta');skipped=playing.get('nonref_skipped_frames_delta')
    if type(encoded) is not int or type(skipped) is not int or encoded<=0 or skipped<=0:return False
    fps=playing['source_fps'];seconds=playing['wall_seconds'];total=encoded+skipped
    return bool(45<fps<=60 and .95*fps<=total/seconds<=1.05*fps and
                playing['submitted_fps']>=.95*fps*encoded/total)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--media',type=pathlib.Path,required=True);parser.add_argument('--quality',type=int,default=80);parser.add_argument('--bvid',default='BV1Da411Y7U4');parser.add_argument('--seek-probe',action='store_true');parser.add_argument('--require-fused-copy',action='store_true');parser.add_argument('--require-frame-diagnostics',action='store_true');parser.add_argument('--late-danmaku-probe',action='store_true');parser.add_argument('--require-output-cache',choices=('cached','fallback'));parser.add_argument('--require-cached-retention',action='store_true');parser.add_argument('--require-rate-states',action='store_true');parser.add_argument('--observe-ddr',action='store_true');parser.add_argument('--require-presentation',action='store_true')
    parser.add_argument('--ux-state',action='store_true',help='Include new private state recording with the exact verified current player')
    parser.add_argument('--window-pose',choices=('landscape','portrait'),help='Placement diagnostic only, not a performance comparison; pair two fresh sessions')
    a=parser.parse_args()
    if a.require_rate_states and a.seek_probe:parser.error('Rate-state audit needs stable playing and paused windows')
    if a.observe_ddr and a.seek_probe:parser.error('DDR observation needs stable playing and paused windows')
    if a.require_cached_retention and (a.quality!=116 or a.require_output_cache!='cached' or not a.require_fused_copy or a.seek_probe):parser.error('Cached retention needs q116, cached output, fused copy, and a rate window')
    bundle=build(a.media,client=True,automated=True,player_protocol=2,benchmark_quality=a.quality,benchmark_bvid=a.bvid,benchmark_seek=a.seek_probe,benchmark_danmaku_delay=8 if a.late_danmaku_probe else 0,ux_state=a.ux_state,window_pose=a.window_pose)
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    subprocess.run([sys.executable,str(BASE/'host/client_native_check.py'),'--bundle',str(bundle)],check=True)
    meta,_=check_bundle(bundle);out=ROOT/'logs'/('BiliP011-PerformanceTrial-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True);(out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    adb=Adb(out);samples=[];report={'physical_acceptance':False,'permanent_install':False,'seek_probe':a.seek_probe};started=False
    observer=None
    if a.window_pose:
        from scanout_alignment import Observer
        observer=Observer(adb,meta,out)
    probe=PROBE
    if a.observe_ddr:
        probe=inspect.getsource(read_ddr_state)+'\n'+probe.replace("print('RESULT='+repr(row))","row['ddr']=read_ddr_state()\nprint('RESULT='+repr(row))")
    try:
        started=True;result_from(command(adb,meta,'start',['start']))
        until=time.monotonic()+150
        while time.monotonic()<until:
            row=result_from(adb.python('numeric-profile','ROOT='+repr(meta['remote'])+'\n'+probe));samples.append(row)
            if row['complete']:break
            if observer:observer.poll()
            time.sleep(1)
    except Exception as e:report['host_error']=type(e).__name__+': '+str(e)
    finally:
        if started:
            try:
                result_from(command(adb,meta,'stop',['stop']))
                until=time.monotonic()+80
                while time.monotonic()<until:
                    status=result_from(command(adb,meta,'restore',['status']))
                    if status['complete']:break
                    time.sleep(2)
                if not status['complete']:raise RuntimeError('Independent restore not ready')
                adb.run('pull',['pull',meta['remote'],str(out/'device')],timeout=45)
                safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
                stock=result_from(adb.python('independent-stock',safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'))
                (out/'independent-stock.json').write_text(json.dumps(stock,indent=2),encoding='utf-8')
                report['recovery']=json.loads(status['files']['result.json']);report['recovery_passed']=report['recovery'].get('passed') is True
                report['benchmark']=json.loads((out/'device/performance-qa.json').read_text())
            except Exception as e:report['recovery_or_result_error']=type(e).__name__+': '+str(e)
        report['metrics']=metrics(samples)
        report['frame_diagnostics']=frame_diagnostics(samples)
        if a.observe_ddr:report['ddr_observation']=summarize_ddr(samples)
        report['frame_diagnostics_required']=a.require_frame_diagnostics
        report['late_danmaku_probe_required']=a.late_danmaku_probe
        if a.late_danmaku_probe:
            try:report['late_danmaku_probe']=json.loads((out/'device/dm-delay-probe.json').read_text())
            except (OSError,ValueError):report['late_danmaku_probe']={}
        late=report.get('late_danmaku_probe',{})
        report['late_danmaku_probe_verified']=(late.get('delivered') is True and type(late.get('released_position')) in (int,float) and 8<=late['released_position']<=31 and type(late.get('items')) is int and late['items']>0) if a.late_danmaku_probe else None
        report['capture_policy']=meta.get('benchmark_capture_policy')
        report['capture_policy_passed']=a.seek_probe or report['capture_policy']=='paused_only' and paused_capture_policy(samples)
        report['fused_copy_required']=a.require_fused_copy
        report['fused_copy_verified']=fused_copy_verified(samples) if a.require_fused_copy else None
        report['passed']=report.get('recovery_passed') is True and report.get('benchmark',{}).get('passed') is True and (a.seek_probe or report['metrics']['playing']['samples']>=5 and report['metrics']['paused']['samples']>=3) and report['capture_policy_passed'] and not report.get('host_error') and (not a.require_fused_copy or report['fused_copy_verified']) and (not a.require_frame_diagnostics or report['frame_diagnostics'].get('available') is True)
        if a.late_danmaku_probe:report['passed']=report['passed'] and report['late_danmaku_probe_verified']
        if a.observe_ddr:
            report['ddr_observation_required']=True
            report['passed']=report['passed'] and report['ddr_observation']['observed']
        if a.require_rate_states:
            report['rate_states_required']=True
            report['rate_states_verified']=frame_rate_states_verified(samples)
            report['passed']=report['passed'] and report['rate_states_verified']
        if a.require_presentation:
            report['presentation_required']=True
            try:
                path=out/'device/presentation-feedback.json'
                if path.is_symlink() or path.stat().st_size>8*1024*1024:raise ValueError('Presentation evidence size')
                report['presentation']=analyze_presentation(json.loads(path.read_text(encoding='utf-8')))
            except (OSError,ValueError):report['presentation']={'evidence_complete':False}
            visible=[s for s in samples if s.get('player',{}).get('active') is True and s.get('player',{}).get('position',0)>=6]
            report['presentation']['backlight_on_during_sampled_playback']=bool(visible) and all(type(s.get('actual_brightness')) is int and s['actual_brightness']>0 for s in visible)
            report['passed']=report['passed'] and report['presentation']['evidence_complete']
        if a.require_output_cache:
            report['output_cache_required']=a.require_output_cache
            report['output_cache_verified']=output_cache_verified(samples,a.require_output_cache)
            report['passed']=report['passed'] and report['output_cache_verified']
        playing=report['metrics']['playing'];fps=playing.get('submitted_fps');source=playing.get('source_fps')
        if a.require_cached_retention:
            report['cached_retention_required']=True
            report['cached_retention_verified']=cached_retention_verified(samples,playing,report['passed'])
            report['passed']=report['passed'] and report['cached_retention_verified']
        if observer:
            report['screen_alignment']=observer.result()
            report['passed']=report['passed'] and report['screen_alignment']['passed']
            report['performance_comparison_valid']=False
        report['smoothness_evaluated']=not a.window_pose and not a.seek_probe and fps is not None and bool(source)
        report['smoothness_passed']=(report['passed'] and fps>=source*.95 and playing['maximum_avsync_ms']<=150 and playing['dropped_frames_delta']+playing['decoder_dropped_frames_delta']<=source*playing['wall_seconds']*.01) if report['smoothness_evaluated'] else None
        report['high_fps_compatibility_passed']=compatible_playback(playing,report['passed']) if not a.seek_probe else None
        report['passed_scope']='paused_seek_resume_and_recovery_only' if a.seek_probe else 'finite_probe_and_recovery_only'
        if a.window_pose:report['passed_scope']='single_window_pose_and_recovery_only'
        (out/'performance-samples.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')
        (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');archive_client(out)
    print(json.dumps({k:report[k] for k in ('passed','passed_scope','smoothness_evaluated','smoothness_passed','high_fps_compatibility_passed','cached_retention_verified','fused_copy_verified','rate_states_verified','metrics','recovery_passed') if k in report},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
