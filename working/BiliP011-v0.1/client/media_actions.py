"""User-confirmed timed messages and opt-in real playback reporting.

Python 3.5. No account writes in automation, no synthesized viewing duration,
no persisted opt-in, and no transport retry after an uncertain response.
"""
import math
import os
import re
import threading
import time

OPS={'danmaku_context','danmaku_send','cloud_state','cloud_enable'}

def arguments(op,a,fail):
    def bad():raise fail('BAD_INPUT')
    if not isinstance(a,dict):bad()
    r={}
    if op in ('danmaku_context','danmaku_send'):
        for k,pattern in [('bvid',r'^BV[0-9A-Za-z]{10}$'),('cid',r'^[1-9][0-9]{0,19}$')]:
            if not isinstance(a.get(k),str) or not re.match(pattern,a[k]):bad()
            r[k]=a[k]
        p=a.get('position',0)
        if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=86400:bad()
        r['position']=int(p)
    if op in ('danmaku_send','cloud_enable'):
        if not isinstance(a.get('intent'),str) or not re.match(r'^[a-f0-9]{32}$',a['intent']):bad()
        r['intent']=a['intent']
    if op=='danmaku_send':
        v=a.get('message')
        if not isinstance(v,str) or not v.strip() or len(v)>100 or any(ord(c)<32 for c in v):bad()
        if type(a.get('mode')) is not int or a['mode'] not in (1,4,5):bad()
        r.update(message=v,mode=a['mode'])
    if op=='cloud_enable':
        if type(a.get('value')) is not bool:bad()
        r['value']=a['value']
    return r

class WatchClock:
    """Only successive fresh native samples may contribute observed watch time."""
    def __init__(self,now,epoch):
        self.start_ts=int(epoch);self.started=now;self.previous=None;self.sent=now
        self.real=0.;self.media=0.;self.maximum=0.;self.running=False;self.ever=False;self.completed=False
    def sample(self,s,now):
        if not isinstance(s,dict) or not s.get('loaded') or s.get('switch_pending'):self.previous=None;return None
        p=s.get('position');duration=s.get('duration');rate=s.get('rate',1)
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in (p,duration,rate)) or not 0<duration<=86400 or not 0<=p<=duration+2 or not .5<=rate<=2:self.previous=None;return None
        active=not s.get('paused') and not s.get('idle') and not s.get('finished')
        previous=self.previous;self.previous=(now,p,active)
        self.maximum=max(self.maximum,p);kind=None
        if previous:
            dt=now-previous[0];delta=p-previous[1]
            progressing=0<dt<=2.5 and delta>0 and delta<=dt*rate+1.5 and active and previous[2]
            if progressing:
                # Buffer stalls, seeks and gaps cannot accrue synthetic time.
                self.real+=min(dt,delta/rate);self.media+=min(delta,dt*rate)
                if not self.running:kind=3;self.ever=True
                self.running=True
            elif self.running and not active:kind=2;self.running=False
            elif self.ever and 0<dt<=2.5 and abs(delta)>dt*rate+1.5:kind=1
        if s.get('completed') and self.ever and not self.completed:
            kind=4;self.completed=True;self.running=False
        elif kind is None and self.running and now-self.sent>=15 and active:kind=0
        if kind is None or not self.ever:return None
        self.sent=now
        return {'start_ts':self.start_ts,'realtime':int(self.media),'real_played_time':int(self.real),
            'played_time':-1 if kind==4 else int(p),'play_type':kind,'video_duration':int(duration),
            'last_play_progress_time':int(p),'max_play_progress_time':int(self.maximum)}

class Actions:
    def __init__(self,b,fail):
        self.b=b;self.fail=fail;self.intents={};self.enabled=False;self.generation=-1
        self.confirmed=0;self.failure='';self.worker=None;self.clock=None;self.key=None;self.context=None
        self.wake=threading.Event();self.last_dm=0
    def issue(self,identity):
        now=time.monotonic();self.intents={k:v for k,v in self.intents.items() if now-v[0]<120}
        if len(self.intents)>32:self.intents.clear()
        nonce=os.urandom(16).hex();self.intents[nonce]=(now,self.b.qr_generation,identity);return nonce
    def consume(self,nonce,identity):
        value=self.intents.pop(nonce,None)
        if not value or time.monotonic()-value[0]>120 or value[1:]!=(self.b.qr_generation,identity):raise self.fail('ACTION_EXPIRED')
    def state(self):
        if self.generation!=self.b.qr_generation:self.enabled=False
        return {'enabled':self.enabled,'confirmed':self.confirmed,'error':self.failure,'session_only':True}
    def dispatch(self,op,a,generation):
        b=self.b
        if op=='cloud_state':
            with b.lock:d=self.state();d['intent']=self.issue(('cloud',));return d
        if op=='cloud_enable':
            if b.automation:raise self.fail('ACTION_DISABLED')
            with b.lock:
                self.consume(a['intent'],('cloud',))
                if a['value'] and b.helper('status',{}).get('logged_in') is not True:raise self.fail('LOGIN_REQUIRED')
                self.enabled=a['value'];self.generation=b.qr_generation;self.clock=None;self.key=None;self.failure=''
                if self.enabled and (self.worker is None or not self.worker.is_alive()):
                    self.worker=threading.Thread(target=self.run);self.worker.daemon=True;self.worker.start()
                self.wake.set();return self.state()
        identity=(a['bvid'],a['cid'],a['position'])
        if op=='danmaku_context':
            with b.lock:
                account=b.qr_generation;d=b.helper('media_context',a)
                if account!=b.qr_generation:raise self.fail('CANCELED')
                duration=d.get('duration')
                if type(duration) is not int or not 0<duration<=86400 or a['position']>duration:raise self.fail('BAD_INPUT')
                return {'position':a['position'],'duration':duration,'intent':self.issue(identity)}
        if op=='danmaku_send':
            if b.automation:raise self.fail('ACTION_DISABLED')
            with b.lock:
                self.consume(a['intent'],identity)
                if time.monotonic()-self.last_dm<5:raise self.fail('BUSY')
                self.last_dm=time.monotonic()
                try:d=b.helper('danmaku_send',{k:v for k,v in a.items() if k!='intent'})
                except Exception as e:
                    if getattr(e,'error','') in ('HELPER_TIMEOUT','HELPER_FAILED','INTERNAL','CANCELED'):raise self.fail('ACTION_UNCONFIRMED')
                    raise
                if not isinstance(d,dict) or d.get('confirmed') is not True:raise self.fail('ACTION_UNCONFIRMED')
                return {'confirmed':True,'visible':d.get('visible') is True}
        raise self.fail('BAD_INPUT')
    def run(self):
        # No automatic recovery/retry: user must inspect the error and opt in again.
        while not self.b.stopping.is_set():
            self.wake.wait(1);self.wake.clear()
            try:self.observe()
            except Exception as e:
                with self.b.lock:self.enabled=False;self.failure=getattr(e,'error','INTERNAL');self.clock=None;self.key=None
    def observe(self,snapshot=None,final=False):
        b=self.b
        with b.lock:
            if b.automation or not self.enabled or self.generation!=b.qr_generation or b.stopping.is_set():return
            item=b.play_item
            if not item:return
            generation,serial,metadata=item
            if generation!=b.play_generation or metadata.get('kind')!='video' or not metadata.get('bvid') or not metadata.get('cid'):return
            if snapshot is None:
                import json
                path=os.path.join(b.root,'watch-state.json')
                try:
                    if time.time()-os.stat(path).st_mtime>2.5:return
                    with open(path,'r') as f:snapshot=json.loads(f.read(8192))
                except (OSError,ValueError):return
            if not isinstance(snapshot,dict) or snapshot.get('generation')!=generation or snapshot.get('serial')!=serial:return
            if final:snapshot=dict(snapshot,finished=True,paused=True)
            # Stream switches within the same part keep watch accounting; queue
            # changes create a new context. Never use a UI-supplied wall duration.
            key=(generation,metadata['bvid'],metadata['cid'])
            now=time.monotonic()
            if key!=self.key:
                self.context=b.helper('media_context',dict(bvid=metadata['bvid'],cid=metadata['cid']))
                self.key=key;self.clock=WatchClock(now,time.time()) if self.context.get('ordinary') is True else None
            if self.clock is None:return
            report=self.clock.sample(snapshot,now)
            if report:
                report.update(bvid=metadata['bvid'],cid=metadata['cid'])
                # helper/credential mutation is serialized by this account lock.
                result=b.helper('watch_heartbeat',report)
                if not isinstance(result,dict) or result.get('confirmed') is not True:raise self.fail('ACTION_UNCONFIRMED')
                self.confirmed+=1
