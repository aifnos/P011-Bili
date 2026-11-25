"""Finite isolated candidate acceptance. Only names/counts/numerical state saved."""
import json,os
CHECKS=('public-library','catalog-navigation','catalog-apis','subtitle-playing','subtitle-loaded','subtitle-controls','preview-image','rate-clock','rate-reset','hold-rate-clock','hold-rate-restored','hold-rate-early-release','chapter-list','chapter-jump','clean-exits','writes-blocked','danmaku-write-blocked','cloud-write-blocked')
def handle(b,r,cleanup):
    if not(b.catalog_probe and b.automation and b.qa_claimed and not b.qa_finished):raise ValueError('gate')
    if r.get('phase')=='checkpoint':
        if r.get('kind') not in ('subtitle','rate','chapter','hold-rate') or len(b.catalog_rounds)>=6:raise ValueError('checkpoint')
        p=b.state().get('player',{})
        fields=('active','muted','hardware_backend','hardware_verified','subtitle_tracks','subtitle_cues','subtitle_enabled','chapter_count','playback_rate','position','preview_images','seek_actions','pulse_observed','paused','hold_rate_active','hold_rate_restore_pending','hold_rate_actions','hold_rate_restores')
        b.catalog_rounds.append(dict(kind=r['kind'],player={k:p[k] for k in fields if k in p}));return {'ok':True}
    checks=r.get('checks',[]);error=r.get('error','')
    if r.get('phase')!='finish' or type(r.get('stage')) is not int or not 0<=r['stage']<=80 or error not in ('','ASSERTION','TIMEOUT','API_FAILED','QML_EXCEPTION','INPUT_FAILED'):raise ValueError('finish')
    if not isinstance(checks,list) or any(c not in CHECKS for c in checks) or len(checks)!=len(set(checks)):raise ValueError('checks')
    passed=r.get('passed') is True and set(checks)==set(CHECKS) and b.env.get('P011_ACCOUNT_WRITES')=='disabled' and b.play_exit_code==0
    if passed:
        for name in ('player-primary-result.json','player-result.json'):
            with open(os.path.join(b.root,name)) as f:p=json.loads(f.read(32768))
            passed=passed and cleanup(p) and p.get('gl_errors')=={} and p.get('muted') is True and p.get('reason')=='back'
        phases={x['kind']:x['player'] for x in b.catalog_rounds}
        passed=passed and phases.get('subtitle',{}).get('subtitle_cues',0)>0 and phases.get('subtitle',{}).get('preview_images',0)>0 and phases.get('rate',{}).get('playback_rate')==1.5 and phases.get('chapter',{}).get('chapter_count',0)>0
        passed=passed and phases.get('hold-rate',{}).get('hold_rate_restores')==1 and phases['hold-rate'].get('playback_rate')==1
    result=dict(passed=bool(passed),checks=checks,error=error,stage=r['stage'],api=b.catalog_evidence,rounds=b.catalog_rounds,account_writes=False,account_captures=False,physical_acceptance=False)
    fd=os.open(os.path.join(b.root,'ui-qa-result.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f)
    b.qa_finished=True;return {'ok':True,'passed':result['passed']}
