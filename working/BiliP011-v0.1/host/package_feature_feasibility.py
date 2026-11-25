"""Package only allowlisted, content-free feasibility evidence (no device call)."""
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys
import zipfile
from official_contract_probe import fetch
from awake_trial import ROOT

RUNS = (
    'public-20260926-222039', 'account-20260926-222101',
    'media-20260926-222105', 'live-20260926-222128',
    'followup-20260926-222435', 'subtitles-20260926-222438',
    'pagination-20260926-222441', 'live-20260926-222641',
)
SOURCES = (
    ('https://s1.hdslb.com/bfs/static/bangumi-timeline/bangumi-timeline.f36fa54448d5b0612f257219e9bcf0df5ebc7f9b.js', 'pgc/web/timeline?'),
    ('https://s1.hdslb.com/bfs/static/2233-monorepo/popular/static/js/index.55b42adc.js', '/x/web-interface/popular/series/one'),
)


def main():
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = ROOT/'logs'/('BiliP011-Feasibility-Delivery-'+stamp)
    out.mkdir()
    report = ROOT/'04_Documents/P011-Bili未接入功能可行性核查-20260926.md'
    payloads = {'REPORT.md':report.read_bytes()}
    summaries = []
    for name in RUNS:
        path = ROOT/'logs'/('BiliP011-Feasibility-'+name)/'result.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        if not value['stock_unchanged'] or not value['credentials_unchanged'] or value['account_writes'] or value['player_started']:
            raise ValueError('Unsafe diagnostic result')
        payloads['checks/'+name+'.json'] = path.read_bytes()
        summaries.append({'run':name, 'group':value['group'], 'stock_unchanged':True,
                          'credentials_unchanged':True, 'check_count':len(value['checks'])})
    failed = ROOT/'logs/BiliP011-Feasibility-followup-20260926-222401/host-failure.json'
    payloads['checks/failed-host-preflight.json'] = failed.read_bytes()
    contracts = []
    for url, term in SOURCES:
        row = {'url':url, 'account_used':False}
        try:
            body = fetch(url)
            text = body.decode('utf-8','replace')
            at = text.find(term)
            row.update(sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),term_found=at>=0)
            if at>=0:row['bounded_excerpt']=text[max(0,at-35):at+190]
        except Exception as exc:
            row['fetch_error']=type(exc).__name__
        contracts.append(row)
    manifest = ROOT/'logs/BiliP011-OfficialFeatureSources-20260926-170412/sources.json'
    entry = next(v for v in json.loads(manifest.read_text(encoding='utf-8')) if v.get('file')=='20-be17bc08514f.js')
    text = (manifest.parent/entry['file']).read_text(encoding='utf-8')
    at = text.find('/xlive/web-ucenter/v1/xfetter/GetWebList')
    contracts.append({'url':entry['url'],'sha256':entry['sha256'],'term_found':at>=0,
                      'bounded_excerpt':text[max(0,at-35):at+155], 'source_capture':'20260926-170412'})
    payloads['official-contracts.json']=json.dumps(contracts,ensure_ascii=False,indent=2).encode('utf-8')
    proc = subprocess.run([sys.executable,'-m','unittest','discover','-s','host','-p','test_feature_feasibility_audit.py','-v'],
                          cwd=pathlib.Path(__file__).resolve().parents[1],capture_output=True,timeout=30)
    payloads['host-tests.stdout.txt']=proc.stdout
    payloads['host-tests.stderr.txt']=proc.stderr
    if proc.returncode:raise RuntimeError('Host audit tests failed')
    for name in ('feature_feasibility_audit.py','feature_feasibility_device.py','test_feature_feasibility_audit.py','package_feature_feasibility.py'):
        payloads['diagnostics/'+name]=(pathlib.Path(__file__).parent/name).read_bytes()
    info={'device_runs':summaries,'host_test_exit':proc.returncode,'product_code_changed':False,
          'account_writes':False,'screenshots':False,'raw_logs_included':False,
          'payloads':{name:hashlib.sha256(body).hexdigest() for name,body in payloads.items()}}
    payloads['manifest.json']=json.dumps(info,ensure_ascii=False,indent=2).encode('utf-8')
    for name,body in payloads.items():
        path=out/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(body)
    target=ROOT/'logs'/('BiliP011-Feasibility-'+stamp+'-safe.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as bundle:
        for name,body in payloads.items():bundle.writestr(name,body)
    with zipfile.ZipFile(target) as bundle:
        if bundle.testzip() is not None:raise RuntimeError('ZIP CRC failed')
        for name,body in payloads.items():
            if bundle.read(name)!=body:raise RuntimeError('ZIP readback mismatch')
    print(json.dumps({'directory':str(out),'zip':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                      'entries':len(payloads),'device_runs':len(summaries),'host_test_exit':proc.returncode,
                      'public_contract_fetch_ok':all(r.get('term_found') for r in contracts)},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
