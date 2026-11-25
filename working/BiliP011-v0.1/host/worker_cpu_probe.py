"""Read-only 8-second CPU sampling of one identity-checked private worker."""
import argparse,datetime,json,pathlib
from awake_trial import Adb,BASE,ROOT,check_bundle,result_from,archive

PAYLOAD=r'''
import os,re,sys,time
sys.path.insert(0,ROOT)
import awake_trial as t
from native_safety import stock_snapshot,require_stock
t.verify();before=stock_snapshot();require_stock(before)
workers=[p for p in t.procs() if re.match(r'^/mnt/data/p011-toolbox/bili-seek-probe-[a-f0-9]{24}/bili-hw$',p['exe']) and t.environment(p).get('P011_SEEK_PROBE_ROOT')==os.path.dirname(p['exe'])]
if len(workers)!=1:raise ValueError('Expected one exact private worker')
worker=workers[0];hz=os.sysconf('SC_CLK_TCK');initial={};latest={};samples=0
roles={'bili-hw':1,'queue0:src':2,'dec:src':3,'queue1:src':4,'queue2:src':5,'vnet:src':6,'anet:src':7,'vd:sink':8,'ad:sink':9,'vs:src':10,'as:src':11,'gmain':12,'gdbus':13,'p011-copy':14}
started=time.monotonic();complete=True
while time.monotonic()-started<8:
 if not t.alive(worker):complete=False;break
 try:task_ids=os.listdir('/proc/%d/task'%worker['pid'])
 except OSError:complete=False;break
 for tid in task_ids:
  try:
   folder='/proc/%d/task/%s/'%(worker['pid'],tid)
   raw=open(folder+'stat').read();values=raw.rsplit(')',1)[1].split()
   identity=(int(tid),int(values[19]));name=raw.split('(',1)[1].rsplit(')',1)[0]
   row={'role':roles.get(name,0),'user':int(values[11]),'system':int(values[12]),'at':time.monotonic()}
   if identity not in initial:initial[identity]=row
   latest[identity]=row
  except (OSError,ValueError):pass
 samples+=1;time.sleep(.25)
rows=[]
for identity,b in latest.items():
 a=initial[identity];dt=b['at']-a['at']
 if dt<=0:continue
 u=(b['user']-a['user'])/hz/dt*100;s=(b['system']-a['system'])/hz/dt*100
 rows.append({'role':b['role'],'user_cpu_percent':round(u,2),'system_cpu_percent':round(s,2),'elapsed_seconds':round(dt,3)})
rows.sort(key=lambda p:p['user_cpu_percent']+p['system_cpu_percent'],reverse=True)
after=stock_snapshot();require_stock(after)
print('RESULT='+repr({'read_only':True,'window_opened':False,'complete_window':complete,'samples':samples,'hz':hz,'threads':rows,'stock_unchanged':before==after}))
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args()
    meta,_=check_bundle(a.bundle)
    out=ROOT/'logs'/('BiliP011-WorkerCPU-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    result=result_from(Adb(out).python('read-only-worker-cpu','ROOT='+repr(meta['remote'])+'\n'+PAYLOAD,timeout=20))
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2));archive(out)
    return 0 if result.get('stock_unchanged') and result.get('complete_window') else 1

if __name__=='__main__':raise SystemExit(main())
