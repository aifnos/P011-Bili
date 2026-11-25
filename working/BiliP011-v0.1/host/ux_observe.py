"""Read-only, numerical observation of one verified UX trial; no account data."""
import argparse
import datetime
import json
from pathlib import Path
from awake_trial import Adb, ROOT, check_bundle, result_from


PROBE = r'''
import os,sys
sys.path.insert(0,ROOT+'/stdlib-json35.zip')
sys.path.insert(0,ROOT)
import json,awake_trial as trial
trial.verify()
def numeric_file(name):
 path=ROOT+'/'+name
 if not os.path.isfile(path):return {}
 if os.path.islink(path) or os.path.getsize(path)>32768:raise ValueError('unexpected state')
 with open(path) as f:value=json.loads(f.read(32769))
 if not isinstance(value,dict):raise ValueError('unexpected state')
 return {k:v for k,v in value.items() if isinstance(v,(bool,int,float)) or k in ('reason','failure') and isinstance(v,str) and len(v)<60}
captures=[]
directory=ROOT+'/screenshots'
if os.path.isdir(directory) and not os.path.islink(directory):
 captures=sorted(n for n in os.listdir(directory) if n.endswith('.png'))
processes={}
for name,ident in (('candidate','candidate'),('worker','worker'),('guardian','guardian'),('client','bili-service')):
 row=trial.refresh(trial.saved(ident))
 processes[name]={'alive':bool(trial.alive(row)),'pid':row['pid'] if row else None,'state':row['state'] if row else None}
qa={}
path=ROOT+'/ui-qa-result.json'
if os.path.isfile(path) and not os.path.islink(path) and os.path.getsize(path)<=32768:
 with open(path) as f:value=json.loads(f.read(32769))
 qa={k:value.get(k) for k in ('passed','error','step','player_stage')}
 qa['check_count']=sum(len(value.get(k,[])) for k in ('checks','toolbox_checks','player_checks'))
print('RESULT='+repr({'read_only':True,'processes':processes,'idle':trial.idle_fields(),
 'player':numeric_file('player-state.json'),'media':numeric_file('media-state.json'),
 'prefetch':numeric_file('prefetch-result.json'),'captures':captures,'qa':qa,
 'complete':os.path.isfile(ROOT+'/result.json')}))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True)
    args=parser.parse_args();meta,_=check_bundle(args.bundle)
    out=ROOT/'logs'/('BiliP011-UXObserve-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    report=result_from(Adb(out).python('numeric-observation','ROOT='+repr(meta['remote'])+'\n'+PROBE))
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
