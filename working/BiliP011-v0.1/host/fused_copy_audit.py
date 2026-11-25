"""Archive exact copy experiments plus a fresh READ-ONLY stock check.

Does not deploy, start playback, change stock state, or remove anything.
Performance failures stay failures in the combined report.
"""
import argparse,datetime,hashlib,json,pathlib,re,subprocess,sys,zipfile

BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runs',nargs='+',required=True,help='Exact YYYYMMDD-HHMMSS run identifiers')
    args=parser.parse_args()
    if len(set(args.runs))!=len(args.runs) or not all(re.fullmatch(r'\d{8}-\d{6}',x) for x in args.runs):raise ValueError('Invalid run identifiers')
    from awake_trial import Adb,NATIVE,result_from,archive
    from fused_worker_artifact import validate as worker_gate
    from private_omx_artifact import validate as plugin_gate
    from hardware_seek_trial import validate_probe
    driver,driver_sha=validate_probe(BASE)
    inputs={};rows=[];scratches=[];workers=set()
    for run in args.runs:
        name='BiliP011-HardwareSeek-'+run;folder=ROOT/'logs'/name
        raw=(folder/'result.json').read_bytes();r=json.loads(raw)
        identity=json.loads((folder/'host-identity.json').read_text())
        scratch=identity['scratch']
        if not re.fullmatch('/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}',scratch):raise ValueError('Invalid scratch identity')
        if r['driver_sha256']!=driver_sha or identity['driver_sha256']!=driver_sha:raise ValueError('Different driver')
        _,worker=worker_gate(BASE,BASE/'out'/identity['worker_artifact'])
        _,plugin=plugin_gate(BASE,BASE/'out'/('omx-probe-'+r['private_plugin_sha256'][:16]))
        if r['worker_sha256']!=worker['sha256'] or identity['worker_sha256']!=worker['sha256'] or r['private_plugin_sha256']!=plugin['sha256']:raise ValueError('Different artifact')
        if not all(r.get(k) is True for k in ('stock_unchanged','factory_config_unchanged','owned_probe_directory_removed')):raise ValueError('Unverified historical restoration')
        lifecycle=r['probe']['lifecycle']
        if r.get('leftover_workers')!=0 or any(lifecycle[k]!=0 for k in ('forced_kills','abnormal_exits','last_exit')):raise ValueError('Abnormal lifecycle')
        previous=folder.with_suffix('.zip')
        with zipfile.ZipFile(previous) as z:
            if z.testzip() is not None or z.read('result.json')!=raw:raise ValueError('Historical archive differs')
        rate=r['probe'].get('rate',{})
        rows.append({'run':name,'mode':plugin['copy_mode'],'quality':r['quality'],
                     'probe_passed':r['passed'],'full_source_rate_passed':r.get('worker_rate_met'),
                     'fused_output_verified':r.get('fused_output_verified'),
                     'source_fps':rate.get('source_fps'),'consumed_fps':rate.get('consumed_fps'),
                     'worker_cpu_percent':rate.get('mean_reported_worker_cpu_percent'),
                     'decoder_drops':rate.get('decoder_drops'),'other_drops':rate.get('drops'),
                     'intentional_input_skips':r['probe']['worker_status']['encoded_nonref_skipped'],
                     'archive_sha256':hashlib.sha256(previous.read_bytes()).hexdigest()})
        inputs[name+'.json']=raw;workers.add(worker['sha256']);scratches.append(scratch)
    if len(workers)!=1:raise ValueError('Not the same worker')
    out=ROOT/'logs'/('BiliP011-FusedCopy-Audit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-s','host','-p','test_*.py'],cwd=BASE,capture_output=True,timeout=60)
    (out/'host-tests.stdout.raw').write_bytes(tests.stdout);(out/'host-tests.stderr.raw').write_bytes(tests.stderr)
    if tests.returncode:raise ValueError('Host regression failed')
    count=re.search(rb'Ran (\d+) tests',tests.stderr)
    if not count:raise ValueError('Missing host test count')
    code=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    code+='\ns=stock_snapshot();require_stock(s)\nactive=0\n'
    code+='for pid in os.listdir("/proc"):\n try:active+=os.readlink("/proc/"+pid+"/exe").startswith("/mnt/data/p011-toolbox/")\n except OSError:pass\n'
    code+='remaining=sum(os.path.lexists(p) for p in '+repr(scratches)+')\n'
    code+='print("RESULT="+repr(dict(stock=s,active_private_processes=active,owned_scratch_remaining=remaining)))\n'
    live=result_from(Adb(out).python('independent-stock-readonly',code))
    (out/'independent-stock.json').write_text(json.dumps(live,indent=2),encoding='utf-8')
    if live['active_private_processes'] or live['owned_scratch_remaining']:raise ValueError('Private work remains active')
    report={'scope':'muted_no_window_worker_only','production_default_changed':False,
            'physical_acceptance':False,'ui_regression_this_iteration':False,
            'independent_stock_verified':True,'host_tests':int(count.group(1)),
            'worker_sha256':next(iter(workers)),'driver_sha256':driver_sha,'runs':rows}
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'inputs').mkdir()
    for name,raw in inputs.items():(out/'inputs'/name).write_bytes(raw)
    print(json.dumps(report,indent=2));print('AUDIT_DIR='+str(out));archive(out)

if __name__=='__main__':main()
