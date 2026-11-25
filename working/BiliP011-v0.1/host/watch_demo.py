"""Explicit requested audible 1080P60 demo, finite original-UI recovery."""
import datetime,json,subprocess,sys,time
from build_awake_trial import build,BASE,ROOT,NATIVE
from awake_trial import Adb,result_from,command,check_bundle
from client_results import archive_client
from ion_copy_trial import IDLE_GATE

def main():
    out=ROOT/'logs'/('BiliP011-WatchDemo-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    result_from(adb.python('idle-before',safety+'\n'+IDLE_GATE+'\nrequire_stock(stock_snapshot())\nprint("RESULT="+repr(dict(passed=True)))'))
    bundle=build(BASE/'out/media-e4ccc8fa53004efb',client=True,player_protocol=2,demo_seconds=180)
    meta,_=check_bundle(bundle)
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    subprocess.run([sys.executable,str(BASE/'host/client_native_check.py'),'--bundle',str(bundle)],check=True)
    started=False;complete=False;observed=False
    report={'physical_acceptance':False,'permanent_install':False,'audible_demo_requested':True,'seconds':180}
    probe='ROOT='+repr(meta['remote'])+r'''
import os,sys
sys.path.insert(0,ROOT)
import awake_trial as trial,service
json=service.json
value={}
for name in ('player-state.json','media-state.json'):
 if os.path.isfile(ROOT+'/'+name):
  row=json.loads(trial.read(ROOT+'/'+name,16384).decode('utf-8'))
  for key in ('loaded','active','paused','muted','quality','source_fps','source_width','source_height','position','hardware_verified','hardware_backend','pulse_observed','draws','hardware_decoded','high_fps_compat'):
   if key in row and type(row[key]) in (bool,int,float):value[key]=row[key]
value['actual_brightness']=trial.idle_fields().get('actual_brightness',0)
print('RESULT='+repr(value))
'''
    try:
        started=True;result_from(command(adb,meta,'start',['start']))
        until=time.monotonic()+265
        while time.monotonic()<until:
            status=result_from(command(adb,meta,'observe',['status']))
            if status['complete']:complete=True;break
            sample=result_from(adb.python('player-observation',probe))
            if sample.get('loaded') and sample.get('active'):
                print('PLAYING='+json.dumps(sample,separators=(',',':')),flush=True)
                valid=(sample.get('quality')==116 and sample.get('source_fps')==60 and
                       sample.get('source_width')==1920 and sample.get('source_height')==1080 and
                       sample.get('muted') is False and sample.get('hardware_verified') is True and
                       sample.get('actual_brightness',0)>0)
                observed=observed or valid
                if not valid:raise RuntimeError('Requested audible lit 1080P60 hardware mode not observed')
            time.sleep(10 if observed else 2)
        if not observed:raise RuntimeError('Requested demo did not reach observed playback')
    except Exception as exc:
        report['host_error']=type(exc).__name__+': '+str(exc)
        print('DEMO_ERROR='+report['host_error'],flush=True)
    finally:
        if started:
            try:
                if not complete:result_from(command(adb,meta,'stop',['stop']))
                until=time.monotonic()+60
                while time.monotonic()<until:
                    status=result_from(command(adb,meta,'restoration',['status']))
                    if status['complete']:complete=True;break
                    time.sleep(2)
                if not complete:raise RuntimeError('Restoration not confirmed')
                report['recovery']=json.loads(status['files']['result.json'])
                adb.run('pull',['pull',meta['remote'],str(out/'device')],timeout=45)
                after=result_from(adb.python('independent-stock',safety+'\n'+IDLE_GATE+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'))
                (out/'independent-stock.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
                report['independent_stock_verified']=True
            except Exception as exc:report['recovery_error']=type(exc).__name__+': '+str(exc)
        report['playback_mode_observed']=observed
        report['recovery_passed']=bool(report.get('recovery',{}).get('passed') and report.get('independent_stock_verified'))
        (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        archive_client(out)
    print('RECOVERY_PASSED='+str(report['recovery_passed']),flush=True)
    return 0 if observed and report['recovery_passed'] and not report.get('host_error') else 1

if __name__=='__main__':raise SystemExit(main())
