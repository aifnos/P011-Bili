"""Explicit public-content/muted device evidence; no account screenshots/writes."""
import json,os

CHECKS=('live-catalog','live-detail','video-playing','avc-hardware','comments-in-player',
        'comments-close','listen-audio-only','listen-continues','video-return',
        'first-clean-exit','live-playing','live-no-seek','live-websocket-auth','live-websocket-heartbeat','second-clean-exit','account-writes-blocked')

def handle(b,r,cleanup):
    if not (b.feature_probe and b.automation and b.qa_claimed and b.protocol==2 and not b.qa_finished):raise ValueError('gate')
    if not isinstance(r,dict):raise ValueError('request')
    if r.get('phase')=='checkpoint':
        p=b.state().get('player',{});kind=r.get('kind');fields=('active','muted','loaded','position','listen','live','hardware_backend','hardware_verified','feature_comment_reads','seek_actions','pulse_observed','paused')
        if kind not in ('comments','listen','live','video-return'):raise ValueError('phase')
        if len(b.feature_rounds)>=8:raise ValueError('bound')
        import awake_trial
        row=dict(kind=kind,player={k:p[k] for k in fields if k in p},idle=awake_trial.idle_fields())
        with open(os.path.join(b.root,'lease.json')) as f:row['keep_awake_lease']=json.loads(f.read(1024)).get('active') is True
        if kind=='live':
            row['live_websocket']={k:v for k,v in b.live_danmaku_stats.items() if type(v) in (bool,int)}
            row['live_render']={k:p[k] for k in ('live_danmaku_received','live_danmaku_authenticated','danmaku_frames','danmaku_count') if k in p}
        b.feature_rounds.append(row);return {'ok':True}
    if r.get('phase')!='finish' or type(r.get('passed')) is not bool:raise ValueError('finish')
    checks=r.get('checks');stage=r.get('stage');error=r.get('error','')
    if not isinstance(checks,list) or len(checks)!=len(set(checks)) or any(c not in CHECKS for c in checks) or type(stage) is not int or not 0<=stage<=60 or error not in ('','ASSERTION','TIMEOUT','INPUT_FAILED','QML_EXCEPTION','API_FAILED'):raise ValueError('result')
    environment=r.get('password_environment','pending')
    if environment not in ('pending','component-unavailable','instance-unavailable','load-unavailable','bridge-ready','bridge-timeout'):raise ValueError('environment')
    report={'passed':False,'checks':checks,'stage':stage,'error':error,'rounds':b.feature_rounds,'live_websocket':{k:v for k,v in b.live_danmaku_stats.items() if type(v) in (bool,int)},'physical_acceptance':False,'account_operations_executed':False,'password_login_verified':False,'password_environment':environment,'capture_policy':'public-content-only'}
    if r['passed'] and set(checks)==set(CHECKS):
        def read(name):
            with open(os.path.join(b.root,name)) as f:return json.loads(f.read(32768))
        first=read('player-primary-result.json');last=read('player-result.json')
        passed=(b.play_exit_code==0 and b.player.poll() is not None and first.get('muted') is True and last.get('muted') is True and
            first.get('gl_errors')=={} and last.get('gl_errors')=={} and first.get('reason')=='back' and last.get('reason')=='back' and cleanup(first) and b.env.get('P011_ACCOUNT_WRITES')=='disabled')
        phases={v['kind']:v['player'] for v in b.feature_rounds}
        passed=passed and set(phases)=={'comments','listen','live','video-return'}
        if passed:
            passed=(phases['comments'].get('feature_comment_reads',0)>0 and phases['listen'].get('listen') is True and phases['listen'].get('hardware_backend') is False and phases['listen'].get('active') is True and phases['live'].get('live') is True and phases['live'].get('active') is True and phases['live'].get('seek_actions')==0 and phases['video-return'].get('hardware_backend') is True)
        report['passed']=bool(passed)
    fd=os.open(os.path.join(b.root,'ui-qa-result.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:json.dump(report,f)
    b.qa_finished=True;return {'ok':True,'passed':report['passed']}
