"""Finite two-minute playback plus idle/restore check, not a permanent install.
Requires the owner to wake the pen before starting. Touch exits the video.
"""
import datetime
import json
import pathlib
import subprocess
import sys
import time

from build_awake_trial import build, BASE, ROOT, NATIVE
from awake_trial import Adb, result_from, command, archive, check_bundle


def main():
    bundle=build(BASE/'out/media-1389ad5e4e4c67ef')
    meta,_=check_bundle(bundle)
    subprocess.run([sys.executable,str(BASE/'host/awake_trial.py'),'stage','--bundle',str(bundle)],check=True)
    out=ROOT/'logs'/('BiliP011-Awake-OneClick-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(); adb=Adb(out); started=False; complete=False
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print('LOG_DIR='+str(out),flush=True)
    try:
        result_from(command(adb,meta,'start',['start'])); started=True
        until=time.monotonic()+30
        while time.monotonic()<until:
            status=result_from(command(adb,meta,'ready',['status']))
            if status['complete']: raise RuntimeError('Trial ended before playback; inspect logs')
            if status['ready']:break
            time.sleep(2)
        else:raise RuntimeError('Bridge not ready within 30 seconds')
        if status['idle']['actual_brightness']==0:
            raise RuntimeError('Screen is off; wake the pen before starting this test')
        print('PLAYING: do not touch for two minutes. Touch exits early.',flush=True)
        result_from(command(adb,meta,'play',['play']))
        until=time.monotonic()+200
        while time.monotonic()<until:
            status=result_from(command(adb,meta,'playing',['status']))
            events=[json.loads(line) for line in status['files'].get('events.jsonl','').splitlines()]
            if status['complete']:raise RuntimeError('Trial ended during playback')
            if any(e['event']=='PLAY_EXIT' for e in events):break
            time.sleep(5)
        else:raise RuntimeError('Playback did not finish within limit')
        print('PLAYBACK_ENDED: checking that normal idle returns (70 seconds).',flush=True)
        until=time.monotonic()+70
        while time.monotonic()<until:
            status=result_from(command(adb,meta,'idle',['status']))
            if status['complete']:raise RuntimeError('Trial ended before idle check')
            time.sleep(5)
    finally:
        if started:
            try:
                result_from(command(adb,meta,'stop',['stop']))
                until=time.monotonic()+90
                while time.monotonic()<until:
                    status=result_from(command(adb,meta,'restoration',['status']))
                    if status['complete']:complete=True;break
                    time.sleep(2)
                if not complete:raise RuntimeError('Restoration not confirmed; inspect pen, do not rerun')
                adb.run('pull',['pull',meta['remote'],str(out/'device')],timeout=45)
                safety=(NATIVE/'runtime/native_safety.py').read_text()
                after=result_from(adb.python('independent-stock',safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'))
                (out/'independent-stock.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
            finally:
                archive(out)
    print('PROCESS_RECOVERY_CONFIRMED. Video/idle evidence and physical acceptance must be reviewed separately.',flush=True)


if __name__=='__main__':main()
