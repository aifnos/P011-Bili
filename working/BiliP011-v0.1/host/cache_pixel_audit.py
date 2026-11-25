"""PC-only A-B-A frame-by-frame audit of finite generated-fixture trials."""
import argparse,datetime,hashlib,json,pathlib,zipfile

ROOT=pathlib.Path(__file__).resolve().parents[3]

def compare(results):
    if len(results)!=3 or [x.get('mode') for x in results]!=['uncached','cached','uncached']:
        raise ValueError('Require uncached-cached-uncached in time order')
    if len({x.get('artifact') for x in results})!=1 or len({x.get('fixture_sha256') for x in results})!=1:
        raise ValueError('Comparison input identities differ')
    frames=[]
    for row in results:
        for field in ('passed','stock_unchanged','vendor_unchanged','temporary_directory_removed'):
            if row.get(field) is not True:raise ValueError('Trial safety or correctness gate failed')
        if row.get('exit')!=0 or row.get('timeout') is not False or row.get('playback_passed') is not False:
            raise ValueError('Trial exit or scope differs')
        probe=row['probe'];cache=probe['cache'];sequence=probe['frames']
        if probe.get('pixels_checked',True) is not True:raise ValueError('Timing-only run cannot prove pixel equivalence')
        if probe.get('passed') is not True or probe.get('hardware_confirmed') is not True or probe.get('eos') is not True:
            raise ValueError('Missing complete real hardware decode')
        if probe.get('window_opened') is not False or probe.get('network_media') is not False or probe.get('stopped') is not False:
            raise ValueError('Trial is not the bounded generated-fixture probe')
        if probe.get('cached')!=(row['mode']=='cached') or len(sequence)!=240 or len({x['sha256'] for x in sequence})<200:
            raise ValueError('Incomplete or repeated frames')
        pts=[x['pts_ns'] for x in sequence]
        if pts!=sorted(set(pts)):raise ValueError('Frame timestamps are not strictly increasing')
        if cache['active'] or cache['sync_errors'] or cache['ownership_errors'] or cache['registered']<1 or cache['registered']!=cache['forgotten']:
            raise ValueError('Cache ownership lifecycle failed')
        if cache['read_begin']!=240 or cache['read_end']!=240:raise ValueError('CPU synchronization pairs differ')
        changed=row['mode']=='cached'
        if cache['changed_allocations']!=(cache['registered'] if changed else 0) or cache['control_allocations']!=(0 if changed else cache['registered']):
            raise ValueError('Allocation mode differs')
        frames.append(sequence)
    if frames[0]!=frames[1] or frames[0]!=frames[2]:raise ValueError('Per-frame pixels or PTS differ')
    return dict(passed=True,scope='generated_avc_hardware_decode_pixel_equivalence',
                playback_passed=False,full_rate_playback_passed=False,frames_per_run=240,
                identical_pts_and_sha256=True,artifact=results[0]['artifact'],
                fixture_sha256=results[0]['fixture_sha256'],
                elapsed_ms=[x['probe']['elapsed_ms'] for x in results],
                sync_ms=[x['probe']['cache']['sync_ns']/1e6 for x in results])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs=3,type=pathlib.Path,required=True)
    args=parser.parse_args();files={};rows=[]
    paths=[path.resolve() for path in args.runs]
    if len(set(paths))!=3 or paths!=sorted(paths):raise ValueError('Runs must be distinct and chronological')
    for path in paths:
        if path.parent!=ROOT/'logs' or not path.name.startswith('BiliP011-CacheDecode-') or path.is_symlink():raise ValueError('Not an owned trial result')
        for name in ('identity.json','result.json','probe.stdout.raw','probe.stderr.raw'):
            file=path/name
            if file.is_symlink() or not file.is_file():raise ValueError('Missing original evidence')
            files[path.name+'/'+name]=file.read_bytes()
        rows.append(json.loads(files[path.name+'/result.json']))
    summary=compare(rows)
    summary['files']={name:dict(bytes=len(body),sha256=hashlib.sha256(body).hexdigest()) for name,body in files.items()}
    files['SUMMARY.json']=json.dumps(summary,indent=2).encode()
    output=ROOT/'logs'/('BiliP011-CachePixels-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or any(archive.read(name)!=body for name,body in files.items()):raise ValueError('Archive content differs')
    print(json.dumps(summary,indent=2));print('RESULT_ZIP='+str(output));print('SHA256='+hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
