"""PC-only audit of real-stream cache experiments, including failed rates.

Only numerical remote records and verified derived JSON enter the ZIP. An
evidence-valid failure stays a failure; this script does not operate ADB.
"""
import argparse,ast,datetime,hashlib,json,math,pathlib,re,zipfile
from cached_compat_evidence import evaluate as evaluate_compat

ROOT=pathlib.Path(__file__).resolve().parents[3]
KINDS={'seek','rate','throughput'}
MODES={'cached','uncached'}
BVIDS={'BV1Da411Y7U4','BV1gi4y1V7Xx'}
BINS={'bili-hw','hardware-seek-probe','libgstomx.so'}

def numeric(value):
    if isinstance(value,bool):return
    if isinstance(value,(int,float)) and math.isfinite(value):return
    if isinstance(value,dict) and all(isinstance(k,str) and re.fullmatch('[a-z_][a-z_0-9]*',k) for k in value):
        for item in value.values():numeric(item)
        return
    if isinstance(value,list):
        for item in value:numeric(item)
        return
    raise ValueError('Non-numerical private protocol value')

def audit_row(row,compat=False):
    if row.get('kind') not in KINDS or row.get('cache_mode') not in MODES or row.get('bvid') not in BVIDS:
        raise ValueError('Unexpected stream or diagnostic kind')
    if not re.fullmatch('cached-worker-[a-f0-9]{16}',row.get('artifact','')):
        raise ValueError('Not a frozen cached worker')
    binaries=row.get('binaries',{})
    if set(binaries)!=BINS or any(not re.fullmatch('[a-f0-9]{64}',v) for v in binaries.values()):
        raise ValueError('Missing binary identity')
    if row.get('passed_scope')!='no_window_cached_worker_'+row['kind']+'_only':
        raise ValueError('Scope differs')
    numeric({k:v for k,v in row.items() if k not in ('kind','cache_mode','bvid','artifact','binaries','passed_scope')})
    for key in ('stock_unchanged','factory_config_unchanged','cache_vendor_unchanged',
                'owned_probe_directory_removed','cache_worker_preflight'):
        if row.get(key) is not True:raise ValueError('Unverified restoration or preflight')
    for key in ('playback_passed','physical_acceptance','window_opened','stock_ui_replaced','audible_audio_requested'):
        if row.get(key) is not False:raise ValueError('Scope expanded into playback acceptance')
    if row.get('leftover_workers')!=0 or row.get('timeout') or row.get('width')!=1920 or row.get('height')!=1080:
        raise ValueError('Invalid geometry or incomplete cleanup')
    probe=row['probe'];status=probe['worker_status'];cache=probe['cache_final'];life=probe['lifecycle']
    if probe.get('worker_failed') is not False or probe.get('worker_error')!=0 or probe.get('private_plugin_loaded') is not True:
        raise ValueError('Worker or plugin identity failed')
    if life.get('starts')!=1 or life.get('normal_exits')!=1 or life.get('last_exit')!=0 or life.get('forced_kills')!=0 or life.get('abnormal_exits')!=0:
        raise ValueError('Not a clean worker lifecycle')
    enabled=row['cache_mode']=='cached';count=cache.get('cache_registered',0);reads=cache.get('cache_read_begin',0)
    if cache.get('cache_final') is not True or count<=0 or reads<=0 or cache.get('cache_forgotten')!=count or cache.get('cache_read_end')!=reads:
        raise ValueError('Incomplete final cache record')
    if any(cache.get(key)!=0 for key in ('cache_active','cache_sync_errors','cache_ownership_errors')):
        raise ValueError('Cache lifetime or synchronization error')
    if cache.get('cache_changed_allocations')!=(count if enabled else 0) or cache.get('cache_control_allocations')!=(0 if enabled else count):
        raise ValueError('Allocation mode differs')
    if status.get('output_cache_enabled')!=enabled or status.get('output_cache_probe') is not True:
        raise ValueError('Unverified mode or hidden frame skipping')
    if compat:
        period=row.get('compat_keep_every')
        if row.get('compat_probe_requested') is not True or type(period) is not int or period not in (0,2,3) or not enabled or row['kind']=='throughput' or status.get('cached_compat_probe') is not True or status.get('nonref_probe_active') is not True or status.get('high_fps_compat') is not True or status.get('nonref_keep_every')!=period or status.get('encoded_nonref_skipped',0)<=0:
            raise ValueError('Incomplete explicit compatibility identity')
    elif row.get('compat_probe_requested') or status.get('cached_compat_probe') or status.get('encoded_nonref_skipped')!=0:
        raise ValueError('Full-source evidence cannot include hidden frame skipping')
    if not all(status.get(k) is True for k in ('hardware_library','vsp_open','omx_private_plugin','fused_half_copy')):
        raise ValueError('Hardware path not observed')
    if status.get('unsynchronized_throughput_probe')!=(row['kind']=='throughput'):
        raise ValueError('Synchronization mode differs')
    if (row['passed'] is True)!=(probe['passed'] is True) or row.get('child_exit')!=(0 if probe['passed'] else 1):
        raise ValueError('Driver failure was relabelled')
    sample=dict(kind=row['kind'],mode=row['cache_mode'],bvid=row['bvid'],driver_passed=row['passed'],
                cache_registered=count,cache_read_pairs=reads,max_close_ms=life['max_close_ms'])
    if row['kind'] in ('rate','throughput'):
        rate=probe['rate'];elapsed=rate['elapsed_seconds'];fps=rate['source_fps'];copy_count=rate['omx_profile_copy_count']
        if not 11.9<=elapsed<=13 or fps not in (30,50,60) or copy_count<=0:
            raise ValueError('Invalid stable measurement interval')
        if abs(rate['consumed_frames']/elapsed-rate['consumed_fps'])>1e-7 or not compat and rate['encoded_nonref_skipped']!=0:
            raise ValueError('Rate arithmetic or frame policy differs')
        drops=rate['drops']+rate['decoder_drops']
        near_source=bool(not compat and row['passed'] and rate['consumed_fps']>=fps*.95 and drops<=fps*elapsed*.01)
        if row.get('worker_rate_met')!=(near_source and row['kind']=='rate') or row.get('unclocked_rate_meets_source')!=(near_source and row['kind']=='throughput'):
            raise ValueError('Original five-percent diagnostic gate differs')
        sample.update(source_fps=fps,consumed_fps=rate['consumed_fps'],drops=rate['drops'],
                      decoder_drops=rate['decoder_drops'],worker_cpu_percent=rate['mean_reported_worker_cpu_percent'],
                      copy_ms=rate['omx_profile_copy_wall_ns']/copy_count/1e6,
                      fill_ms=rate['omx_profile_fill_wall_ns']/rate['omx_profile_fill_count']/1e6,
                      acquire_seconds=rate['omx_profile_acquire_wall_ns']/1e9,
                      queue_samples=rate['queue_samples'],queue_nonempty_samples=rate['queue_nonempty_samples'],
                      within_five_percent_diagnostic_gate=near_source,
                      measured_at_least_source_rate=rate['consumed_fps']>=fps)
        if compat:
            compared=evaluate_compat(rate,period,row['passed'])
            if row.get('compatibility_rate_met') is not compared['compatibility_rate_met']:
                raise ValueError('Compatibility performance verdict differs')
            sample['compatibility']=compared
    else:
        sample.update(paused_position=probe.get('paused_position',0),paused_frame_pts=probe.get('paused_frame_pts',0),
                      resumed_position=status.get('position',0),resumed_frame_pts=probe['last_frame_pts'])
    return sample

def compare(rows):
    if not 9<=len(rows)<=24:raise ValueError('Incomplete experiment set')
    if len({r['artifact'] for r in rows})!=1 or any(r['binaries']!=rows[0]['binaries'] for r in rows):
        raise ValueError('A/B comparison changed binaries')
    samples=[audit_row(row) for row in rows]
    thirty=[s for s in samples if s['kind']=='rate' and s['source_fps']==30]
    if len(thirty)!=3 or [s['mode'] for s in thirty]!=['uncached','cached','uncached'] or len({s['bvid'] for s in thirty})!=1:
        raise ValueError('Missing same-source thirty-fps A-B-A')
    if any(not s['driver_passed'] or not s['within_five_percent_diagnostic_gate'] or s['drops'] or s['decoder_drops'] for s in thirty):
        raise ValueError('Thirty-fps frame-rate evidence failed')
    rate_high=[s for s in samples if s['kind']=='rate' and s['source_fps']>30 and s['mode']=='cached']
    throughput=[s for s in samples if s['kind']=='throughput']
    if {s['source_fps'] for s in rate_high}!={50,60} or {s['source_fps'] for s in throughput if s['mode']=='cached'}!={50,60}:
        raise ValueError('Missing high-rate controls, including failures')
    if not any(s['mode']=='uncached' and s['source_fps']==60 for s in throughput):
        raise ValueError('Missing uncached sixty-fps throughput control')
    seeks=[s for s in samples if s['kind']=='seek' and s['mode']=='cached']
    if not seeks:raise ValueError('Missing paused-seek result')
    a,b,c=thirty
    return dict(evidence_valid=True,scope='real_stream_private_cache_worker_no_window',
                playback_passed=False,physical_acceptance=False,production_integration_verified=False,
                full_high_rate_playback_passed=False,artifact=rows[0]['artifact'],binaries=rows[0]['binaries'],
                samples=samples,failed_driver_runs=sum(not s['driver_passed'] for s in samples),
                thirty_fps_worker_rate_passed=True,cached_seek_passed=all(s['driver_passed'] for s in seeks),
                cpu_reduction_vs_lower_control_percent=100*(1-b['worker_cpu_percent']/min(a['worker_cpu_percent'],c['worker_cpu_percent'])),
                copy_reduction_vs_lower_control_percent=100*(1-b['copy_ms']/min(a['copy_ms'],c['copy_ms'])),
                power_measured=False,all_cache_lifetimes_balanced=True)

def remote_record(raw):
    # Normalize only for parsing; ZIP retains the exact original bytes.
    lines=raw.decode('ascii').replace('\r\r\n','\n').replace('\r\n','\n').splitlines()
    lines=[line for line in lines if line]
    if len(lines)!=2 or not lines[0].startswith('RESULT=') or lines[1]!='__REMOTE_EXIT__=0':
        raise ValueError('Unexpected remote output or helper exit')
    remote=ast.literal_eval(lines[0][7:]);numeric(remote)
    if not isinstance(remote,dict):raise ValueError('Not a numerical remote record')
    return remote

def read_run(path):
    if path.parent!=ROOT/'logs' or path.is_symlink() or not re.fullmatch('BiliP011-CachedWorker-[0-9]{8}-[0-9]{6}',path.name):
        raise ValueError('Unexpected evidence directory')
    files={}
    for name in ('result.json','cleanup.json','06-bounded-cached-worker.stdout.raw','06-bounded-cached-worker.status.json'):
        file=path/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size>1024*1024:raise ValueError('Invalid evidence file')
        files[path.name+'/'+name]=file.read_bytes()
    row=json.loads(files[path.name+'/result.json']);audit_row(row)
    cleanup=json.loads(files[path.name+'/cleanup.json'])
    if cleanup!=dict(temporary_directory_removed=True,removed_files=[],stock_unchanged=True):
        raise ValueError('Cleanup was not already complete at independent check')
    if json.loads(files[path.name+'/06-bounded-cached-worker.status.json'])!=dict(host_exit=0,remote_exit=0,timeout=False):
        raise ValueError('Host or helper transport failed')
    remote=remote_record(files[path.name+'/06-bounded-cached-worker.stdout.raw'])
    if any(row.get(k)!=v for k,v in remote.items()):raise ValueError('Raw and derived records differ')
    return row,files

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs='+',type=pathlib.Path,required=True)
    paths=[p.resolve() for p in parser.parse_args().runs]
    if paths!=sorted(paths) or len(set(paths))!=len(paths):raise ValueError('Require distinct chronological runs')
    rows=[];files={}
    for path in paths:
        row,parts=read_run(path);rows.append(row);files.update(parts)
    report=compare(rows)
    for sample,path in zip(report['samples'],paths):sample['run']=path.name
    report['files']={name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()) for name,body in files.items()}
    files['SUMMARY.json']=json.dumps(report,indent=2).encode()
    output=ROOT/'logs'/('BiliP011-CachedWorker-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or any(archive.read(name)!=body for name,body in files.items()):raise ValueError('Archive verification failed')
    print(json.dumps({k:v for k,v in report.items() if k not in ('files','samples','binaries')},indent=2))
    print('RESULT_ZIP='+str(output));print('SHA256='+hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
