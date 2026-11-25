"""Run the anonymous, non-UI client smoke on an already staged exact bundle."""
import argparse
import datetime
import json
import pathlib
from awake_trial import BASE, ROOT, NATIVE, Adb, archive, result_from, check_bundle

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
    meta,names=check_bundle(args.bundle)
    if meta.get('client_adapter')!='v0.2':raise ValueError('Not a client candidate')
    out=ROOT/'logs'/('BiliP011-Client-API-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
    code='import sys\nsys.path.insert(0,'+repr(meta['remote'])+')\nimport awake_trial as t\nt.verify()\nimport smoke\nsmoke.main()\n'
    result=result_from(adb.python('anonymous-client-smoke',code,timeout=135))
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));archive(out)
    if not result.get('passed'):raise SystemExit(1)

if __name__=='__main__':main()
