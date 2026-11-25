"""Offline evidence/PII gate for finite thread-wait observations, including failures."""
import argparse,ast,copy,datetime,hashlib,json,math,pathlib,re,zipfile
from cached_worker_audit import ROOT,audit_row,numeric
from cached_seek_trial import assess
from omx_format_profile import inspect_format
from vsp_readback import evaluate_readback


def histogram(value,pattern):
    if not isinstance(value,dict) or len(value)>512:
        raise ValueError('Unbounded observation histogram')
    for key,count in value.items():
        if not isinstance(key,str) or not re.fullmatch(pattern,key) or type(count) is not int or not 0<=count<=20000:
            raise ValueError('Not a sanitized observation histogram')


def inspect_sample(sample):
    booleans={'enabled','joined','identity_rejected','worker_observed','children_interface'}
    numbers={'elapsed_seconds','samples','process_cpu_seconds','interval_seconds','ticks_per_second',
             'max_samples','read_errors','sampling_wall_seconds'}
    allowed=booleans|numbers|{'threads','clocks'}
    if set(sample)!=allowed:
        # The first failed observer predates the optional children interface.
        if set(sample)!=allowed-{'children_interface'}:
            raise ValueError('Unknown observation fields')
    for name in booleans & set(sample):
        if type(sample[name]) is not bool:raise ValueError('Not boolean observation metadata')
    for name in numbers:
        value=sample[name]
        if type(value) not in (float,int) or not math.isfinite(value) or value<0:raise ValueError('Invalid observation number')
    if not 0<sample['ticks_per_second']<=10000 or not sample['elapsed_seconds']<=55 or not sample['samples']<=200:
        raise ValueError('Observation bound exceeded')
    if not isinstance(sample['threads'],dict) or len(sample['threads'])>256:raise ValueError('Unbounded threads')
    threads=[]
    numeric_keys={'samples','first_user','first_system','first_at','last_user','last_system','last_at','policy','priority'}
    optional_nums={'first_run_ns','first_runqueue_ns','first_slices','last_run_ns','last_runqueue_ns','last_slices'}
    for key,thread in sample['threads'].items():
        if not re.fullmatch('[0-9]+_[0-9]+',key):raise ValueError('Invalid task identity')
        allowed=numeric_keys|optional_nums|{'name','states','waits','stacks','syscalls','wchan_available','schedstat_available'}
        if set(thread)-allowed or not numeric_keys<=set(thread):raise ValueError('Unknown task fields')
        if not re.fullmatch('[A-Za-z0-9_.:-]{1,64}',thread['name']):raise ValueError('Unsanitized thread name')
        numeric({k:v for k,v in thread.items() if k in numeric_keys|optional_nums})
        for field in ('wchan_available','schedstat_available'):
            if field in thread and type(thread[field]) is not bool:raise ValueError('Invalid availability flag')
        for field,pattern in (('states','[RSDZTtXxKWPIN]'),('waits','[A-Za-z0-9_.:-]{1,64}'),
                              ('stacks','[A-Za-z0-9_.:-]{1,64}'),('syscalls','syscall_[0-9]{1,4}|running|unavailable|not_in_syscall|vsp_poll_complete|vsp_acquire|vsp_other_ioctl')):
            histogram(thread.get(field,{}),pattern)
        if sum(thread['states'].values())!=thread['samples'] or sum(thread['waits'].values())!=thread['samples']:
            raise ValueError('Thread histogram count differs')
        if 'syscalls' in thread and sum(thread['syscalls'].values())!=thread['samples']:raise ValueError('Syscall count differs')
        elapsed=thread['last_at']-thread['first_at']
        user=thread['last_user']-thread['first_user'];system=thread['last_system']-thread['first_system']
        if elapsed<0 or user<0 or system<0:raise ValueError('Thread identity/counter went backward')
        threads.append(dict(name=thread['name'],samples=thread['samples'],observed_seconds=elapsed,
                            cpu_seconds=(user+system)/sample['ticks_per_second'],
                            mean_cpu_percent=(user+system)*100/sample['ticks_per_second']/elapsed if elapsed else 0,
                            states=thread['states'],syscalls=thread.get('syscalls',{}),stacks=thread['stacks'],
                            scheduler_wait_available=thread.get('schedstat_available',False)))
    if len(sample['clocks'])>64:raise ValueError('Unbounded clocks')
    for key,value in sample['clocks'].items():
        if not re.fullmatch('cpu[0-3]_khz|clk_[A-Za-z0-9_.:-]{1,64}',key):raise ValueError('Unknown clock key')
        histogram(value,'[0-9]{1,12}')
    valid=sample['joined'] and sample['worker_observed'] and not sample['identity_rejected'] and sample['samples']>=8 and bool(threads)
    return dict(evidence_complete=bool(valid),sample_count=sample['samples'],
                observer_cpu_percent=100*sample['process_cpu_seconds']/sample['elapsed_seconds'] if sample['elapsed_seconds'] else 0,
                includes_startup=True,one_second_snapshot_not_a_function_duration=True,
                kernel_symbols_available=any(t['stacks'] for t in threads),
                scheduler_wait_available=any(t['scheduler_wait_available'] for t in threads),
                specific_syscall_observed=any(any(k not in ('running','syscall_0','unavailable','not_in_syscall') for k in t['syscalls']) for t in threads),
                clocks=sample['clocks'],threads=sorted(threads,key=lambda t:-t['cpu_seconds']))


def inspect_vsp(value):
    keys={'poll_count','poll_wall_ns','poll_cpu_ns','poll_max_ns','poll_lt5ms','poll_5to10ms','poll_10to20ms',
          'poll_20to50ms','poll_ge50ms','acquire_count','acquire_wall_ns','acquire_cpu_ns','acquire_max_ns',
          'stagefright_calls','codec_calls','forward_errors','clock_errors'}
    frequency_keys={'freq_config_calls','freq_config_success','freq_config_failed','freq_null','freq_other',
                    'freq_stagefright_calls','freq_codec_calls'}|{'freq_level'+str(i) for i in range(16)}
    gap_bins=('gap_lt1ms','gap_1to2ms','gap_2to5ms','gap_5to10ms','gap_10to20ms','gap_ge20ms')
    poll_bins=('poll_detail_lt8ms','poll_detail_8to12ms','poll_detail_12to16_667ms','poll_detail_16_667to20ms',
               'poll_detail_20to25ms','poll_detail_25to33_333ms','poll_detail_33_333to50ms','poll_detail_ge50ms')
    timing_keys={'timing_schema','gap_count','gap_wall_ns','gap_max_ns','gap_first_calls','gap_context_resets','gap_clock_errors'}|set(gap_bins)|set(poll_bins)
    cycle_parts=('postpoll','release','outer','acquire','prepare')
    cycle_keys={'cycle_schema','release_count','release_wall_ns','release_cpu_ns','release_max_ns','release_failed',
                'cycle_count','cycle_first_polls','cycle_incomplete_polls','cycle_context_resets','cycle_order_resets',
                'cycle_clock_errors','cycle_gap_wall_ns','cycle_gap_max_ns'}|{'cycle_'+p+'_'+s+'_ns' for p in cycle_parts for s in ('wall','max')}
    sequence_keys={'cycle_extra_pairs','cycle_max_extra_pairs','seq_contexts'}|{'seq_start'+str(i) for i in range(3)}|{'seq_e'+str(i)+str(j) for i in range(3) for j in range(3)}
    result_names=('poll_result_0','poll_result_2','poll_result_4','poll_result_negative','poll_result_other')
    result_keys=set(result_names)|{'poll_result_other_min_u32','poll_result_other_max_u32'}
    if not isinstance(value,dict) or set(value) not in (keys,keys|frequency_keys,keys|frequency_keys|timing_keys,keys|frequency_keys|timing_keys|cycle_keys,keys|frequency_keys|timing_keys|cycle_keys|sequence_keys,keys|frequency_keys|timing_keys|cycle_keys|sequence_keys|result_keys) or any(type(v) is not int or v<0 for v in value.values()):
        raise ValueError('Unexpected VSP timing evidence')
    poll_results=None
    if result_keys<=set(value):
        if sum(value[k] for k in result_names)!=value['poll_count'] or not 0<=value['poll_result_other_min_u32']<=value['poll_result_other_max_u32']<2**31:
            raise ValueError('POLL result counts or bounds differ')
        if not value['poll_result_other'] and any(value[k] for k in ('poll_result_other_min_u32','poll_result_other_max_u32')):
            raise ValueError('Unexpected POLL result range')
        poll_results={k:value[k] for k in sorted(result_keys)}
    frequency=None
    if frequency_keys<=set(value):
        count=value['freq_config_calls']
        levels={str(i):value['freq_level'+str(i)] for i in range(16) if value['freq_level'+str(i)]}
        if count!=value['freq_config_success']+value['freq_config_failed'] or count!=sum(levels.values())+value['freq_null']+value['freq_other'] or count!=value['freq_stagefright_calls']+value['freq_codec_calls']:
            raise ValueError('VSP frequency call count differs')
        frequency=dict(evidence_complete=bool(count and value['freq_config_success']==count and not value['freq_null'] and not value['freq_other']),
                       calls=count,requested_levels=levels,successful_calls=value['freq_config_success'],
                       actual_clock_measured=False,requests_changed=False)
    if sum(value[k] for k in ('poll_lt5ms','poll_5to10ms','poll_10to20ms','poll_20to50ms','poll_ge50ms'))!=value['poll_count']:
        raise ValueError('Timing histogram differs')
    if value['poll_count']+value['acquire_count']+value.get('release_count',0)+value['clock_errors']!=value['stagefright_calls']+value['codec_calls']:
        raise ValueError('VSP call count differs')
    for name in ('poll','acquire')+(('release',) if cycle_keys<=set(value) else ()):
        if value[name+'_wall_ns']<value[name+'_cpu_ns'] or value[name+'_max_ns']>value[name+'_wall_ns']:
            raise ValueError('Invalid VSP clock difference')
    timing=None
    if timing_keys<=set(value):
        if value['timing_schema']!=1 or sum(value[k] for k in gap_bins)!=value['gap_count']:
            raise ValueError('Gap schema or histogram differs')
        if value['gap_count']+value['gap_first_calls']+value['gap_context_resets']+value['gap_clock_errors']!=value['poll_count']:
            raise ValueError('Gap call count differs')
        if sum(value[k] for k in poll_bins)!=value['poll_count'] or sum(value[k] for k in poll_bins[:4])!=value['poll_lt5ms']+value['poll_5to10ms']+value['poll_10to20ms'] or sum(value[k] for k in poll_bins[4:7])!=value['poll_20to50ms'] or value[poll_bins[7]]!=value['poll_ge50ms']:
            raise ValueError('Detailed poll histogram differs')
        if value['gap_max_ns']>value['gap_wall_ns'] or not value['gap_count'] and (value['gap_wall_ns'] or value['gap_max_ns']):
            raise ValueError('Invalid gap duration')
        timing=dict(evidence_complete=bool(value['gap_count'] and not value['gap_clock_errors']),
                    gap_count=value['gap_count'],mean_gap_ms=value['gap_wall_ns']/value['gap_count']/1e6 if value['gap_count'] else 0,
                    max_gap_ms=value['gap_max_ns']/1e6,gap_seconds=value['gap_wall_ns']/1e9,
                    gap_bins={k:value[k] for k in gap_bins},poll_bins={k:value[k] for k in poll_bins},
                    poll_at_least_16_667ms=sum(value[k] for k in poll_bins[3:]),
                    poll_at_least_20ms=sum(value[k] for k in poll_bins[4:]),
                    first_calls=value['gap_first_calls'],context_resets=value['gap_context_resets'],
                    same_thread_same_context_only=True,includes_startup=True,not_per_frame_or_pure_hardware_time=True)
    cycle=None;sequence=None
    if sequence_keys<=set(value):
        roles=('poll','acquire','release')
        for j in range(3):
            if value['seq_start'+str(j)]+sum(value['seq_e'+str(i)+str(j)] for i in range(3))!=value[roles[j]+'_count']:
                raise ValueError('Sequence role counts differ')
        if value['seq_contexts']>sum(value['seq_start'+str(i)] for i in range(3)):
            raise ValueError('Sequence context count differs')
        sequence=dict(evidence_complete=not value['seq_contexts'] and not value['clock_errors'],
                      starts={roles[i]:value['seq_start'+str(i)] for i in range(3)},
                      transitions={roles[i]+'_to_'+roles[j]:value['seq_e'+str(i)+str(j)] for i in range(3) for j in range(3)},
                      includes_startup_and_shutdown=True,context_resets=value['seq_contexts'],
                      numeric_only=True,frame_or_nal_identity_observed=False)
    if cycle_keys<=set(value):
        count=value['cycle_count'];gap=value['cycle_gap_wall_ns'];maximum=value['cycle_gap_max_ns']
        expected_schema=2 if sequence is not None else 1
        extra=value.get('cycle_extra_pairs',0);max_extra=value.get('cycle_max_extra_pairs',0)
        if value['cycle_schema']!=expected_schema or count+value['cycle_first_polls']+value['cycle_incomplete_polls']!=value['poll_count']:
            raise ValueError('Cycle schema or poll count differs')
        if value['release_failed']>value['release_count'] or count>value['gap_count'] or count+extra>min(value['release_count'],value['acquire_count']):
            raise ValueError('Cycle or release call count differs')
        if max_extra>extra or extra>count*max_extra or extra>value.get('seq_e12',0):
            raise ValueError('Unaccounted extra acquisition/release pairs')
        if gap!=sum(value['cycle_'+p+'_wall_ns'] for p in cycle_parts) or maximum>gap or gap>value['gap_wall_ns'] or maximum>value['gap_max_ns'] or not count and gap:
            raise ValueError('Cycle partition duration differs')
        if count==value['gap_count'] and (gap!=value['gap_wall_ns'] or maximum!=value['gap_max_ns']):
            raise ValueError('Complete cycle does not cover gap total')
        for part in cycle_parts:
            total=value['cycle_'+part+'_wall_ns'];peak=value['cycle_'+part+'_max_ns']
            if peak>total or peak>maximum or bool(peak)!=bool(total) or total>count*peak:
                raise ValueError('Invalid cycle component duration')
            if part in ('release','acquire') and (total>value[part+'_wall_ns'] or peak>value[part+'_max_ns']*(1+max_extra)):
                raise ValueError('Cycle subset exceeds call duration')
        cycle=dict(evidence_complete=bool(count and count==value['gap_count'] and value['release_count'] and not value['release_failed'] and not any(value[k] for k in ('cycle_incomplete_polls','cycle_context_resets','cycle_order_resets','cycle_clock_errors'))),
                   count=count,first_polls=value['cycle_first_polls'],incomplete_polls=value['cycle_incomplete_polls'],
                   schema=value['cycle_schema'],extra_pairs=extra,max_extra_pairs=max_extra,single_pair_assumption=expected_schema==1,
                   release_calls=value['release_count'],mean_release_ms=value['release_wall_ns']/value['release_count']/1e6 if value['release_count'] else 0,
                   mean_release_cpu_ms=value['release_cpu_ns']/value['release_count']/1e6 if value['release_count'] else 0,
                   mean_gap_ms=gap/count/1e6 if count else 0,
                   parts={p:dict(mean_ms=value['cycle_'+p+'_wall_ns']/count/1e6 if count else 0,max_ms=value['cycle_'+p+'_max_ns']/1e6) for p in cycle_parts},
                   same_thread_same_context_only=True,includes_startup=True,includes_observer_and_scheduling=True,
                   not_per_frame_or_pure_hardware_time=True,input_copy_not_isolated=True)
    return dict(evidence_complete=bool(value['poll_count'] and value['acquire_count'] and not value['forward_errors'] and not value['clock_errors'] and (frequency is None or frequency['evidence_complete']) and (timing is None or timing['evidence_complete']) and (cycle is None or cycle['evidence_complete']) and (sequence is None or sequence['evidence_complete'])),
                poll_count=value['poll_count'],acquire_count=value['acquire_count'],
                mean_poll_ms=value['poll_wall_ns']/value['poll_count']/1e6 if value['poll_count'] else 0,
                mean_poll_cpu_ms=value['poll_cpu_ns']/value['poll_count']/1e6 if value['poll_count'] else 0,
                mean_acquire_ms=value['acquire_wall_ns']/value['acquire_count']/1e6 if value['acquire_count'] else 0,
                poll_seconds=value['poll_wall_ns']/1e9,acquire_seconds=value['acquire_wall_ns']/1e9,
                includes_startup=True,call_wall_time_includes_scheduling=True,hardware_frequency_measured=False,frequency=frequency,timing=timing,cycle=cycle,sequence=sequence,poll_results=poll_results)


def inspect_result(row):
    original=copy.deepcopy(row)
    readback_summary=original.pop('vsp_readback_summary',None)
    if readback_summary is not None:
        if type(readback_summary) is not dict:raise ValueError('Invalid readback summary')
        allowed={'evidence_complete','driver_reported_levels','calls','maximum_query_ms','mean_query_ms','physical_clock_measured','frequency_changed','sample_point'}
        if set(readback_summary)-allowed:raise ValueError('Unknown readback summary')
        if 'sample_point' in readback_summary and readback_summary['sample_point']!='after_successful_original_frequency_configuration':raise ValueError('Unknown sample point')
        levels=readback_summary.get('driver_reported_levels',{})
        if type(levels) is not dict or any(not re.fullmatch('[0-9]|1[0-5]',k) for k in levels):raise ValueError('Unknown readback level')
        # Level labels are the separately checked decimal keys, not arbitrary
        # protocol field names. Keep the shared private-data gate strict.
        numeric(list(levels.values()))
        numeric({k:v for k,v in readback_summary.items() if k not in ('sample_point','driver_reported_levels')})
    readback=evaluate_readback(row.get('vsp_readback')) if row.get('vsp_readback_requested') else None
    if row.get('vsp_readback',{}).get('schema')==2 and readback_summary!=readback:raise ValueError('Readback derived summary differs')
    observed=original.pop('wait_sample',None)
    sample=inspect_sample(observed) if observed is not None else None
    # Validate the driver on its OWN evidence, while retaining (never updating)
    # the original outer diagnostic verdict and explicitly rejecting empty
    # historic samplers. A successful player is not a successful observer.
    compat=row.get('compat_probe_requested') is True
    driver=audit_row(assess(original,row['cache_mode'],row['kind'],False,
                            compat_keep=row.get('compat_keep_every') if compat else None),compat=compat)
    vsp=inspect_vsp(row['vsp_profile']) if 'vsp_profile' in row else None
    formats=inspect_format(row['format_profile'],row.get('probe',{}).get('rate',{}).get('source_fps')) if 'format_profile' in row else None
    accepted=driver['driver_passed'] and (sample is None or sample['evidence_complete']) and (not row.get('vsp_profile_requested') or vsp is not None and vsp['evidence_complete'])
    accepted=accepted and (not row.get('format_profile_requested') or formats is not None and formats['evidence_complete'])
    accepted=accepted and (not row.get('vsp_readback_requested') or readback is not None and readback['evidence_complete'])
    return dict(run_diagnostic_passed=row['passed'],current_observation_gate_passed=bool(accepted),
                original_verdict_disagrees_with_complete_observation=bool(row['passed'])!=bool(accepted),
                driver=driver,observation=sample,vsp=vsp,formats=formats,readback=readback)


def read_run(path):
    if path.parent!=ROOT/'logs' or path.is_symlink() or not re.fullmatch('BiliP011-CachedWorker-[0-9]{8}-[0-9]{6}',path.name):
        raise ValueError('Unexpected result path')
    files={}
    names=('result.json','cleanup.json','06-bounded-cached-worker.stdout.raw','06-bounded-cached-worker.status.json')
    for name in names:
        file=path/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size>1024*1024:raise ValueError('Unsafe evidence file')
        files[path.name+'/'+name]=file.read_bytes()
    row=json.loads(files[path.name+'/result.json']);summary=inspect_result(row)
    cleanup=json.loads(files[path.name+'/cleanup.json'])
    if cleanup!=dict(temporary_directory_removed=True,removed_files=[],stock_unchanged=True):raise ValueError('Not independently restored')
    if json.loads(files[path.name+'/06-bounded-cached-worker.status.json'])!=dict(host_exit=0,remote_exit=0,timeout=False):raise ValueError('Helper transport failed')
    lines=files[path.name+'/06-bounded-cached-worker.stdout.raw'].decode('ascii').replace('\r\r\n','\n').replace('\r\n','\n').splitlines()
    lines=[line for line in lines if line]
    if len(lines)!=2 or not lines[0].startswith('RESULT=') or lines[1]!='__REMOTE_EXIT__=0':raise ValueError('Unexpected raw output')
    remote=ast.literal_eval(lines[0][7:]);plain=dict(remote);sample=plain.pop('wait_sample',None)
    if sample is not None:inspect_sample(sample)
    numeric(plain)
    if any(row.get(key)!=value for key,value in remote.items()):raise ValueError('Derived and original evidence differ')
    summary['run']=path.name
    return row,summary,files


def main():
    parser=argparse.ArgumentParser();parser.add_argument('runs',nargs='+',type=pathlib.Path)
    args=parser.parse_args();rows=[];summaries=[];files={}
    if not 1<=len(args.runs)<=12:raise ValueError('Unbounded audit')
    for path in args.runs:
        row,summary,entries=read_run(path.resolve());rows.append(row);summaries.append(summary);files.update(entries)
    if any(row['binaries']!=rows[0]['binaries'] for row in rows):raise ValueError('Different executable experiment')
    result=dict(scope='no_window_wait_diagnosis',playback_passed=False,physical_acceptance=False,
                frequency_changed=False,binaries=rows[0]['binaries'],runs=summaries)
    out=ROOT/'logs'/('BiliP011-WorkerWait-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();body=json.dumps(result,ensure_ascii=True,indent=2).encode('ascii')
    (out/'result.json').write_bytes(body);files['audit.json']=body
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name,raw in sorted(files.items()):z.writestr(name,raw)
        z.writestr('SHA256.json',json.dumps({name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},indent=2))
    print('AUDIT='+str(out));print('SAFE_ZIP='+str(archive));print('ZIP_SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__=='__main__':main()
