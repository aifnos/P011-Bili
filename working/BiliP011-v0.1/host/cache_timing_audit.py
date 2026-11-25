"""Numerical-only comparison; an unclocked test is not playback acceptance."""
import argparse,datetime,hashlib,json,pathlib,zipfile
ROOT=pathlib.Path(__file__).resolve().parents[3]

def compare(results):
    if len(results)!=3 or [row.get('mode') for row in results]!=['uncached','cached','uncached']:
        raise ValueError('Require chronological uncached-cached-uncached')
    if len({row['artifact'] for row in results})!=1 or len({row['fixture_sha256'] for row in results})!=1:
        raise ValueError('Artifact or fixture differs')
    samples=[];timestamps=[]
    for row in results:
        for key in ('passed','stock_unchanged','vendor_unchanged','temporary_directory_removed'):
            if row.get(key) is not True:raise ValueError('Unverified device trial')
        if row.get('check')!='timing' or row.get('playback_passed') is not False or row['exit']!=0 or row['timeout']:
            raise ValueError('Timing scope or exit differs')
        p=row['probe'];cache=p['cache'];profile=p['profile']
        if not p['passed'] or not p['hardware_confirmed'] or not p['eos'] or p['stopped'] or p['network_media'] or p['window_opened'] or p['pixels_checked']:
            raise ValueError('Not a completed isolated timing probe')
        if len(p['frames'])!=240 or any(x['sha256'] for x in p['frames']) or p['hash_ms']!=0:
            raise ValueError('Hash work interfered with timing')
        timestamps.append([x['pts_ns'] for x in p['frames']])
        if timestamps[-1]!=sorted(set(timestamps[-1])):raise ValueError('Invalid PTS sequence')
        if cache['active'] or cache['sync_errors'] or cache['ownership_errors'] or cache['registered']!=cache['forgotten'] or cache['registered']<1:
            raise ValueError('Unbalanced buffer lifecycle')
        if cache['read_begin']!=240 or cache['read_end']!=240 or profile['copy_count']!=240 or profile['fill_count']!=240:
            raise ValueError('Incomplete output or timing samples')
        expected=row['mode']=='cached'
        if p['cached']!=expected or cache['changed_allocations']!=(cache['registered'] if expected else 0) or cache['control_allocations']!=(0 if expected else cache['registered']):
            raise ValueError('Allocation mode differs')
        measured=239000.0/p['sample_span_ms']
        if abs(measured-p['unclocked_sample_fps'])>0.0001:raise ValueError('Timing rate arithmetic differs')
        samples.append(dict(mode=row['mode'],copy_ms=profile['copy_wall_ns']/240e6,
                            fill_ms=profile['fill_wall_ns']/240e6,sync_ms=cache['sync_ns']/240e6,
                            unclocked_fps=measured,elapsed_ms=p['elapsed_ms']))
    if timestamps[0]!=timestamps[1] or timestamps[1]!=timestamps[2]:raise ValueError('PTS output differs')
    return dict(passed=True,scope='synthetic_unclocked_hardware_decode_timing',playback_passed=False,
                full_rate_playback_passed=False,artifact=results[0]['artifact'],fixture_sha256=results[0]['fixture_sha256'],
                samples=samples,cache_copy_improvement_observed=samples[1]['copy_ms']<min(samples[0]['copy_ms'],samples[2]['copy_ms'])*0.8,
                cache_throughput_improvement_observed=samples[1]['unclocked_fps']>max(samples[0]['unclocked_fps'],samples[2]['unclocked_fps'])*1.1)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs=3,type=pathlib.Path,required=True)
    paths=[path.resolve() for path in parser.parse_args().runs]
    if len(set(paths))!=3 or paths!=sorted(paths):raise ValueError('Runs are not distinct chronological paths')
    files={};rows=[]
    for path in paths:
        if path.parent!=ROOT/'logs' or not path.name.startswith('BiliP011-CacheDecode-') or path.is_symlink():raise ValueError('Unexpected trial directory')
        for name in ('result.json','identity.json','probe.stdout.raw','probe.stderr.raw','cleanup.json'):
            file=path/name
            if file.is_symlink() or not file.is_file():raise ValueError('Missing evidence')
            files[path.name+'/'+name]=file.read_bytes()
        rows.append(json.loads(files[path.name+'/result.json']))
    summary=compare(rows);summary['files']={name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()) for name,body in files.items()}
    files['SUMMARY.json']=json.dumps(summary,indent=2).encode()
    output=ROOT/'logs'/('BiliP011-CacheTiming-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or any(archive.read(name)!=body for name,body in files.items()):raise ValueError('Archive verification failed')
    print(json.dumps({k:v for k,v in summary.items() if k!='files'},indent=2))
    print('RESULT_ZIP='+str(output));print('SHA256='+hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
