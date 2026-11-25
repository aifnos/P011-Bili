"""Capture only observed official lazy widget URLs; no account or write calls."""
import datetime,hashlib,json
from official_contract_probe import fetch
from build_awake_trial import ROOT

def main():
    out=ROOT/'logs'/('BiliP011-PlayerContracts-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();print('LOG_DIR='+str(out),flush=True)
    files=('npd.pc-helper.3229da5c.js','npd.community-helper.9b24caeb.js','npd.bangumi-helper.876f15f2.js')
    records=[]
    for filename in files:
        url='https://s1.hdslb.com/bfs/static/player/main/widgets/'+filename
        raw=fetch(url);(out/filename).write_bytes(raw);s=raw.decode('utf-8','replace')
        records.append(dict(url=url,file=filename,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),terms={n:s.count(n) for n in ('sendStore.send','rnd:','fontsize:','progress:')}))
    (out/'sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records))
if __name__=='__main__':main()
