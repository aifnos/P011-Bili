"""Official Story prefix acceptance. Numerical evidence; no account writes."""
import json
import os

def read(root,name):
    path=os.path.join(root,name)
    if os.path.islink(path) or os.path.getsize(path)>32768:raise ValueError('probe file')
    with open(path) as f:value=json.loads(f.read(32769))
    if not isinstance(value,dict):raise ValueError('probe object')
    return value

CHECKS=('discovery','weekly','story-playing','two-prefixes','cached-next','cached-second','cached-back','tail-continuation','comments','rate-menu','swipe-seek','landscape','exit')

def handle(b,req,clean):
    if not(b.story_probe and b.automation and b.qa_claimed and not b.qa_finished and b.protocol==2):raise ValueError('gate')
    if req.get('phase')=='observe':
        p=b.state().get('player',{})
        if not p.get('active') or p.get('switch_pending') or not p.get('hardware_verified') or not p.get('muted'):raise ValueError('playing')
        if len(b.story_rounds)>=4:raise ValueError('bound')
        if b.story_rounds and not(p.get('cached_media') and p.get('prefetch_media_hits',0)>=len(b.story_rounds)):raise ValueError('cache hit')
        b.story_rounds.append(p)
        with open(os.path.join(b.root,'story-checkpoints.json'),'w') as f:json.dump(b.story_rounds,f)
        return {'ok':True}
    if req.get('phase')!='finish' or type(req.get('passed')) is not bool:raise ValueError('finish')
    checks=req.get('checks',[]);error=req.get('error','');stage=req.get('stage',0)
    if not isinstance(checks,list) or len(set(checks))!=len(checks) or any(x not in CHECKS for x in checks):raise ValueError('checks')
    if error not in ('','TIMEOUT','ASSERTION','INPUT_FAILED','QML_EXCEPTION','CHECKPOINT_FAILED') or type(stage) is not int or not 0<=stage<=30:raise ValueError('error')
    verified=False;cache={}
    if req['passed']:
        native=read(b.root,'player-result.json');cache=read(b.root,'prefetch-result.json')
        verified=(b.play_exit_code==0 and native.get('gl_errors')=={} and clean(native) and cache.get('worker_stopped') is True and
                  len(b.story_rounds)==4 and b.story_rounds[-1].get('relay_tail_bytes',0)>0)
    passed=req['passed'] and verified and not error and set(checks)==set(CHECKS)
    report=dict(passed=bool(passed),error=error if error else '' if passed else 'ASSERTION',step=stage,checks=checks,player_checks=[],toolbox_checks=[],captures=[],last_state=b.state().get('player',{}),
        layer='P011 official Story prefix',rounds=b.story_rounds,cache=cache,physical_acceptance=False,audio_output_muted=True,account_page_captured=False)
    with open(os.path.join(b.root,'ui-qa-result.json'),'x') as f:json.dump(report,f)
    b.qa_finished=True
    return {'ok':True,'passed':bool(passed)}
