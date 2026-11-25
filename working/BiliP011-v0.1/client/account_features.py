"""Official account/live adapters. Credentials and write intent never reach logs.

Every write needs a fresh, one-use intent bound to a video and login generation.
Automated device runs refuse writes, even if a test accidentally clicks a button.
"""
import os
import re
import time

OPS={'relation','favorites','interaction','season_relation','season_follow','account_history','live_catalog','live_detail','feature_capabilities','password_challenge','password_login','password_cancel'}
ERRORS={'ACTION_DISABLED','ACTION_UNCONFIRMED','ACTION_EXPIRED','LIVE_OFFLINE','LIVE_RESTRICTED','FEATURE_UNAVAILABLE','CAPTCHA_UNSUPPORTED','LOGIN_ENCRYPTION_FAILED','LOGIN_SECOND_FACTOR'}

def arguments(op,a,fail):
    def bad():raise fail('BAD_INPUT')
    if not isinstance(a,dict):bad()
    result={}
    if op in ('relation','favorites','interaction'):
        b=a.get('bvid')
        if not isinstance(b,str) or not re.match(r'^BV[0-9A-Za-z]{10}$',b):bad()
        result['bvid']=b
    if op=='interaction':
        action=a.get('action');nonce=a.get('intent')
        if action not in ('like','coin','favorite','triple','watchlater','follow','comment','comment_like') or not isinstance(nonce,str) or not re.match(r'^[a-f0-9]{32}$',nonce):bad()
        result.update(action=action,intent=nonce)
        if action in ('like','favorite','watchlater','follow','comment_like'):
            if type(a.get('value')) is not bool:bad()
            result['value']=a['value']
        if action=='coin':
            if type(a.get('count')) is not int or a['count'] not in (1,2):bad()
            result['count']=a['count']
        if action=='favorite':
            if not isinstance(a.get('folder'),str) or not re.match(r'^[0-9]{1,20}$',a['folder']):bad()
            result['folder']=a['folder']
        if action in ('comment','comment_like'):
            for key in ('root','parent'):
                v=a.get(key,'0')
                if not isinstance(v,str) or not re.match(r'^[0-9]{1,20}$',v):bad()
                result[key]=v
            if action=='comment_like' and result['parent']=='0':bad()
            if (result['root']=='0')!=(result['parent']=='0'):bad()
            if action=='comment':
                text=a.get('message')
                if not isinstance(text,str) or not text.strip() or len(text)>160 or any(ord(c)<32 for c in text):bad()
                result['message']=text
    elif op in ('season_relation','season_follow'):
        v=a.get('season')
        if not isinstance(v,str) or not re.match(r'^[0-9]{1,20}$',v):bad()
        result['season']=v
        if op=='season_follow':
            if type(a.get('value')) is not bool or not isinstance(a.get('intent'),str) or not re.match(r'^[a-f0-9]{32}$',a['intent']):bad()
            result.update(value=a['value'],intent=a['intent'])
    elif op=='account_history':
        for k in ('max','view_at'):
            v=a.get(k,'0')
            if not isinstance(v,str) or not re.match(r'^[0-9]{1,20}$',v):bad()
            result[k]=v
        v=a.get('business','')
        if not isinstance(v,str) or not re.match(r'^[a-z_]{0,32}$',v):bad()
        result['business']=v
    elif op=='live_detail':
        if not isinstance(a.get('room'),str) or not re.match(r'^[0-9]{1,20}$',a['room']):bad()
        result['room']=a['room']
    elif op=='password_login':
        for k,limit in (('username',160),('password',256),('challenge',512),('validate',512),('seccode',512),('nonce',32)):
            v=a.get(k)
            if not isinstance(v,str) or not v or len(v.encode('utf-8'))>limit or any(ord(c)<32 for c in v):bad()
            result[k]=v
        if not re.match(r'^[a-f0-9]{32}$',result['nonce']):bad()
    return result

class Features:
    def __init__(self,backend,fail,short):
        self.b=backend;self.fail=fail;self.short=short;self.intents={};self.last_write={}
        self.login=None;self.login_generation=0
        self.comment_refs={}

    def note_comments(self,bvid,root,rows,generation):
        if not bvid or generation!=self.b.qr_generation:return
        if len(self.comment_refs)>160:self.comment_refs.clear()
        for row in rows:self.comment_refs[(bvid,row['id'])]=(root or row['id'],generation)

    def relation(self,data):
        if not isinstance(data,dict) or type(data.get('like')) is not bool or type(data.get('favorite')) is not bool or type(data.get('coin')) is not int or not 0<=data['coin']<=2:raise self.fail('API_SCHEMA')
        return {k:data[k] for k in ('like','favorite','coin')}

    def dispatch(self,op,args,generation):
        b=self.b
        if op=='feature_capabilities':
            return {'account_writes':not b.automation,'password_login':not b.automation,
                'password_reason':'OFFICIAL_CAPTCHA_REQUIRES_USER','not_interested':False,
                'feedback_reason':'OFFICIAL_RECOMMENDATION_CONTRACT_NOT_VERIFIED','live':True,'listen':True}
        if op=='password_cancel':
            with b.lock:self.login=None;self.login_generation+=1
            return {'canceled':True}
        if op=='password_challenge':
            if b.automation:raise self.fail('ACTION_DISABLED')
            with b.lock:
                self.login=None;self.login_generation+=1;ticket=self.login_generation;account_generation=b.qr_generation
            d=b.helper(op,{})
            if not isinstance(d,dict) or any(not isinstance(d.get(k),str) or not re.match(r'^[a-zA-Z0-9_-]{16,256}$',d[k]) for k in ('token','gt','challenge')):raise self.fail('API_SCHEMA')
            nonce=os.urandom(16).hex()
            with b.lock:
                if ticket!=self.login_generation or account_generation!=b.qr_generation:raise self.fail('CANCELED')
                self.login=dict(d,nonce=nonce,at=time.monotonic(),generation=account_generation,ticket=ticket)
            return {'nonce':nonce,'gt':d['gt'],'challenge':d['challenge']}
        if op=='password_login':
            if b.automation:raise self.fail('ACTION_DISABLED')
            with b.lock:
                saved=self.login;self.login=None
                if not saved or saved['nonce']!=args['nonce'] or saved['generation']!=b.qr_generation or time.monotonic()-saved['at']>180:raise self.fail('ACTION_EXPIRED')
            private=dict(args,token=saved['token']);private.pop('nonce',None)
            try:
                data=b.helper(op,private)
                with b.lock:
                    if saved['generation']!=b.qr_generation or saved['ticket']!=self.login_generation:raise self.fail('CANCELED')
                    b.save_cookies(data.get('cookies'))
                    b.qr_generation+=1;self.login_generation+=1;self.intents.clear()
                return {'logged_in':True}
            finally:private.clear();args.clear()
        if op in ('relation','season_relation'):
            with b.lock:account_generation=b.qr_generation
            raw=b.helper(op,args)
            if op=='relation':data=self.relation(raw);identity=args['bvid']
            else:
                if not isinstance(raw,dict) or type(raw.get('following')) is not bool:raise self.fail('API_SCHEMA')
                data=dict(following=raw['following'],title=self.short(raw.get('title'),100));identity='ss:'+args['season']
            with b.lock:
                if account_generation!=b.qr_generation:raise self.fail('CANCELED')
                now=time.monotonic();self.intents={k:v for k,v in self.intents.items() if now-v[0]<120}
                if len(self.intents)>32:self.intents.clear()
                nonce=os.urandom(16).hex();self.intents[nonce]=(now,identity,b.qr_generation)
                data['intent']=nonce
            return data
        if op=='favorites':
            data=b.helper(op,args);rows=data.get('items')
            if not isinstance(rows,list) or len(rows)>1000:raise self.fail('API_SCHEMA')
            result=[]
            for r in rows:
                if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not re.match(r'^[0-9]{1,20}$',r['id']) or type(r.get('selected')) is not bool:raise self.fail('API_SCHEMA')
                result.append({'id':r['id'],'title':self.short(r.get('title'),80),'selected':r['selected']})
            return {'items':result}
        if op in ('interaction','season_follow'):
            if b.automation:raise self.fail('ACTION_DISABLED')
            identity='ss:'+args['season'] if op=='season_follow' else args['bvid']
            with b.lock:
                intent=self.intents.pop(args['intent'],None)
                if not intent or time.monotonic()-intent[0]>120 or intent[1:]!=(identity,b.qr_generation):raise self.fail('ACTION_EXPIRED')
                if args.get('action') in ('comment','comment_like') and args['parent']!='0':
                    if self.comment_refs.get((args['bvid'],args['parent']))!=(args['root'],b.qr_generation):raise self.fail('ACTION_EXPIRED')
                # Serialize changes to the same video, including coin/triple.
                if self.last_write.get(identity):raise self.fail('BUSY')
                self.last_write[identity]=True
            try:
                native={k:v for k,v in args.items() if k!='intent'}
                data=b.helper(op,native)
                if not isinstance(data,dict) or data.get('confirmed') is not True:raise self.fail('ACTION_UNCONFIRMED')
                result={'confirmed':True,'state_available':data.get('state_available') is True}
                if result['state_available']:result['relation']=self.relation(data.get('relation'))
                if isinstance(data.get('triple'),dict):result['triple']={k:data['triple'].get(k) is True for k in ('like','coin','favorite')}
                return result
            except Exception as exc:
                if getattr(exc,'error','') in ('HELPER_TIMEOUT','HELPER_FAILED','INTERNAL','CANCELED'):raise self.fail('ACTION_UNCONFIRMED')
                raise
            finally:
                with b.lock:self.last_write.pop(identity,None)
        if op=='account_history':
            data=b.helper(op,args);rows=data.get('items');cursor=data.get('cursor')
            if not isinstance(rows,list) or len(rows)>20 or not isinstance(cursor,dict):raise self.fail('API_SCHEMA')
            cursor=arguments(op,cursor,self.fail);result=[]
            for r in rows:
                row=b.card(r);row.update(position=max(0,min(86400,r.get('position',0))),finished=r.get('finished') is True,
                    playable=r.get('playable') is True,business=self.short(r.get('business'),32))
                result.append(row)
            return {'items':result,'cursor':cursor,'more':data.get('more') is True,'source':'official-account'}
        if op=='live_catalog':
            data=b.helper(op,args);rows=data.get('items')
            if not isinstance(rows,list) or len(rows)>60:raise self.fail('API_SCHEMA')
            return {'items':[b.card(r) for r in rows],'more':False,'page':1,'offset':''}
        if op=='live_detail':
            data=b.helper(op,args);row=b.card(data);row.update(live_status=data.get('live_status',0),description=self.short(data.get('description'),1000))
            return row
        raise self.fail('BAD_INPUT')
