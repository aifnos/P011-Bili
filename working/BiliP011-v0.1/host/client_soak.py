"""Read-only, allowlisted evidence for playback across the 60-second idle period.

Never sends input, changes backlight settings or reads account data. The normal
one-click guardian remains responsible for starting/stopping its own candidate.
"""
import math

PROBE = r'''
import os,sys,time
sys.path.insert(0,ROOT)
sys.path.insert(0,ROOT+'/stdlib-json35.zip')
import json
import awake_trial as trial
row={'time':time.monotonic(),'idle':trial.idle_fields(),'player':{},'lease':{}}
keys=('loaded','active','paused','position','duration','muted','pause_actions','seek_actions','capture_count','drops','pulse_observed')
for name,key,fields in [('player-state.json','player',keys),('lease.json','lease',('active','seq'))]:
 path=ROOT+'/'+name
 try:
  value=json.loads(trial.read(path,16384).decode('utf-8'))
  row[key]={k:value[k] for k in fields if k in value and type(value[k]) in (bool,int,float)}
  row[key+'_age']=max(0,time.time()-os.stat(path).st_mtime)
 except FileNotFoundError:pass
print('RESULT='+repr(row))
'''


def collect(adb, meta):
    from awake_trial import result_from
    return result_from(adb.python('soak-readonly', 'ROOT='+repr(meta['remote'])+'\n'+PROBE))


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def evaluate(samples, minimum_seconds=120):
    longest=[];current=[]
    for row in samples:
        p=row.get('player',{});idle=row.get('idle',{});lease=row.get('lease',{})
        valid=(number(row.get('time')) and number(p.get('position')) and
               p.get('loaded') is True and p.get('active') is True and p.get('muted') is True and
               p.get('paused') is False and p.get('pulse_observed') is True and
               p.get('pause_actions')==0 and p.get('seek_actions')==0 and p.get('capture_count')==0 and
               idle.get('seconds')==60 and idle.get('enabled')==0 and
               number(idle.get('brightness')) and idle['brightness']>0 and
               number(idle.get('actual_brightness')) and idle['actual_brightness']>0 and
               lease.get('active') is True and number(lease.get('seq')) and
               all(number(row.get(key)) and 0<=row[key]<=2.5 for key in ('player_age','lease_age')))
        if not valid:current=[];continue
        if current:
            previous=current[-1];delta=row['time']-previous['time'];advance=p['position']-previous['player']['position']
            if not (0<delta<=10 and delta*.5<=advance<=delta*1.5 and lease['seq']>previous['lease']['seq']):current=[]
        current.append(row)
        span=current[-1]['time']-current[0]['time']
        previous_span=longest[-1]['time']-longest[0]['time'] if longest else -1
        if span>previous_span:longest=list(current)
    span=longest[-1]['time']-longest[0]['time'] if longest else 0
    progress=longest[-1]['player']['position']-longest[0]['player']['position'] if longest else 0
    return dict(passed=span>=minimum_seconds and progress>=minimum_seconds*.85,
                required_seconds=minimum_seconds,continuous_seconds=round(span,3),
                position_advance=round(progress,3),samples=len(samples),continuous_samples=len(longest),
                min_actual_brightness=min((x['idle']['actual_brightness'] for x in longest),default=None),
                idle_setting_seconds=60,muted=True,physical_acceptance=False,
                evidence='Fresh advancing player and lease, idle disabled, actual backlight on; no input during hold')


if __name__=='__main__':
    import argparse,datetime,json,pathlib
    from awake_trial import Adb,ROOT,check_bundle
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
    meta,_=check_bundle(args.bundle)
    out=ROOT/'logs'/('BiliP011-Soak-ReadOnly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    result=collect(Adb(out),meta)
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));print('LOG_DIR='+str(out))
