"""Finite private-library acceptance. Numeric evidence only; Python 3.5."""
import json
import math
import os
from library import Library, identity

CHECKS=('details','playing','avc-hardware','history-saved','resume-ui','resume-playing',
        'restart-ui','from-start','history-visible','clear-confirm','clear-complete',
        'failed-switch-restored','paused-position-retained')


def read(root,name):
    path=os.path.join(root,name)
    if os.path.islink(path) or os.path.getsize(path)>32768:raise ValueError('probe file')
    with open(path) as f:value=json.loads(f.read(32769))
    if not isinstance(value,dict):raise ValueError('probe object')
    return value


def handle(b,request,clean):
    if not (b.ux_probe and b.automation and b.qa_claimed and not b.qa_finished and b.protocol==2 and b.hardware_required and b.library is not None):raise ValueError('probe gate')
    if os.path.abspath(b.library.directory)!=os.path.join(os.path.abspath(b.root),'library'):raise ValueError('probe isolation')
    if not isinstance(request,dict):raise ValueError('probe request')
    phase=request.get('phase')
    if phase=='observe':
        number=len(b.ux_rounds)+1
        if number>3 or b.play_generation!=number or b.play_exit_code!=0 or b.player is None or b.player.poll() is None:raise ValueError('probe order')
        native=read(b.root,'player-result.json');watch=read(b.root,'watch-state.json');media=read(b.root,'media-state.json')
        perf=read(b.root,'performance-result.json')
        if not (native.get('generation')==number and native.get('reason')=='back' and native.get('loaded') is True and
                native.get('muted') is True and native.get('pulse') is True and native.get('gl_errors')=={} and clean(native) and
                watch.get('generation')==number and watch.get('loaded') is True and watch.get('switch_pending') is False and
                media.get('generation')==number and media.get('hardware_verified') is True and perf.get('submitted_frames',0)>20):raise ValueError('probe playback')
        value=Library(b.library.directory).load()
        if len(value['history'])!=1:raise ValueError('probe history')
        row=value['history'][0];position=watch.get('position');saved=row['position']
        if type(position) not in (int,float) or not math.isfinite(position) or abs(saved-position)>1:raise ValueError('probe position')
        if number==1:
            if not 15<=position<row['duration']-5:raise ValueError('probe first position')
            if not (b.ux_faults==1 and media.get('switch_failures')==1 and media.get('switch_recoveries')==1):raise ValueError('probe recovery')
            b.ux_identity=identity(row)
        elif identity(row)!=b.ux_identity:raise ValueError('probe item changed')
        elif number==2 and not b.ux_rounds[0]['position']-1<=position<=b.ux_rounds[0]['position']+15:raise ValueError('probe resume')
        elif number==3 and not 2<=position<9:raise ValueError('probe restart')
        b.ux_rounds.append(dict(generation=number,position=position,saved_position=saved,
                                submitted_frames=perf['submitted_frames'],hardware= native['hardware'],
                                switch_failures=media.get('switch_failures',0),switch_recoveries=media.get('switch_recoveries',0),
                                muted=True,gl_errors={},disk_reopened=True))
        return {'ok':True,'position':position}
    if phase!='finish' or type(request.get('passed')) is not bool:raise ValueError('probe finish')
    checks=request.get('checks',[]);error=request.get('error','');stage=request.get('stage',0)
    if not isinstance(checks,list) or any(x not in CHECKS for x in checks) or len(set(checks))!=len(checks):raise ValueError('probe checks')
    if error not in ('','TIMEOUT','ASSERTION','CHECKPOINT_FAILED','INPUT_FAILED','QML_EXCEPTION'):raise ValueError('probe error')
    if type(stage) is not int or not 0<=stage<50:raise ValueError('probe stage')
    passed=request['passed'];empty=False
    if passed:
        empty=Library(b.library.directory).load()['history']==[]
        passed=not error and set(checks)==set(CHECKS) and len(b.ux_rounds)==3 and empty and b.play_exit_code==0 and b.play_item is None and b.ux_faults==1 and not b.ux_fault_pending
        if not passed:error='ASSERTION'
    report=dict(passed=passed,error=error,step=stage,checks=checks,player_checks=[],toolbox_checks=[],captures=[],
                layer='P011 isolated local state',rounds=b.ux_rounds,history_clear_verified=empty,
                audio_output_muted=True,physical_touch_verified=False,account_page_captured=False)
    path=os.path.join(b.root,'ui-qa-result.json')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:json.dump(report,f)
    b.qa_finished=True
    return {'ok':True,'passed':passed}
