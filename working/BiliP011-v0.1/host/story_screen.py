"""One read-only physical output capture during the frozen Story hold stage."""
import argparse,datetime,json,pathlib,time
from awake_trial import Adb,ROOT,check_bundle,result_from
from scanout_alignment import STATE,capture

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args();meta,_=check_bundle(a.bundle)
    if not meta.get('story_probe') or not meta.get('ui_automation'):raise ValueError('Explicit muted Story probe required')
    out=ROOT/'logs'/('BiliP011-StoryScreen-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();print('LOG_DIR='+str(out),flush=True)
    adb=Adb(out);probe='ROOT='+repr(meta['remote'])+'\n'+STATE
    marker='ROOT='+repr(meta['remote'])+r'''
import re,os
stages=[]
for name in ('candidate.stdout.raw','candidate.stderr.raw'):
 try:
  with open(ROOT+'/'+name,'rb') as f:raw=f.read(8*1024*1024)
  stages.extend(int(x) for x in re.findall(br'P011_STORY_STAGE ([0-9]{1,2})(?=\s)',raw))
 except OSError:pass
print('RESULT='+repr({'stage':stages[-1] if stages else -1,'complete':os.path.isfile(ROOT+'/result.json')}))
'''
    until=time.monotonic()+150;report={'passed':False,'physical_touch_tested':False,'profile':'single Story landscape output, not full regression'}
    while time.monotonic()<until:
        progress=result_from(adb.python('stage',marker))
        if progress['complete']:break
        if progress['stage']==17:
            before=result_from(adb.python('before',probe));p=before.get('player-state.json',{})
            if not(before.get('player_running') and p.get('active') and p.get('loaded') and not p.get('portrait') and not p.get('menu') and not p.get('switch_pending')):continue
            sample=capture(adb,out,'00',dict(session=meta['session'],generation=p.get('generation'),portrait=False,muted=True))
            after=result_from(adb.python('after',probe));q=after.get('player-state.json',{})
            stable=all(p.get(k)==q.get(k) for k in ('generation','portrait','menu')) and q.get('active') and after.get('player_running') and after.get('player_pid')==before.get('player_pid')
            report.update(passed=bool(stable and sample['passed']),state_stable=bool(stable),sample=sample);break
        time.sleep(1)
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
