"""Existing pen session, read-only. Export counts/schema, never account content."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True,type=pathlib.Path);a=p.parse_args()
    meta,_=check_bundle(a.bundle)
    out=ROOT/'logs'/('BiliP011-AccountReadOnly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True)
    code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import os,sys,signal,hashlib
sys.path.insert(0,ROOT)
import service,awake_trial
from native_safety import stock_snapshot,require_stock
signal.alarm(110);awake_trial.verify();before=stock_snapshot();require_stock(before)
account='/mnt/data/p011-toolbox/bili-account';path=account+'/cookies.txt'
def cookie_hash():
 if not os.path.isfile(path):return None
 if os.path.islink(path):raise RuntimeError('Account path is not private')
 with open(path,'rb') as f:return hashlib.sha256(f.read(65537)).hexdigest()
original=cookie_hash();env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for key in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):env.pop(key,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',account,env,automation=True,lifetime=100)
report={'account_writes':False,'account_screenshots':False,'checks':{}}
try:
 d=b.dispatch('status',{},0);report['logged_in']=d.get('logged_in') is True
 if report['logged_in']:
  try:
   detail=b.helper('detail',{'kind':'video','bvid':'BV1Da411Y7U4'});part=detail['parts'][0]
   d=b.dispatch('danmaku_context',service.safe_args('danmaku_context',dict(bvid=part['bvid'],cid=part['cid'],position=0)),b.qr_generation)
   report['checks']['timed_message_context']={'ok':type(d.get('duration')) is int and d['duration']>0 and bool(d.get('intent'))}
  except service.Failure as e:report['checks']['timed_message_context']=service.error_result(e)
  for op,args in [('relation',{'bvid':'BV1Da411Y7U4'}),('season_relation',{'season':'41410'}),('favorites',{'bvid':'BV1Da411Y7U4'}),('account_history',{})]:
   try:
    d=b.dispatch(op,service.safe_args(op,args),0);entry={'ok':True}
    if op=='relation':entry['state_types_valid']=all(type(d.get(k)) is bool for k in ('like','favorite')) and type(d.get('coin')) is int
    elif op=='season_relation':entry['state_type_valid']=type(d.get('following')) is bool
    else:entry['items']=len(d['items'])
    if op=='account_history':
     entry['source']=d['source'];entry['more']=d['more']
     if d['more']:
      page=b.dispatch(op,d['cursor'],0);entry['next_page_items']=len(page['items'])
    report['checks'][op]=entry
   except service.Failure as e:report['checks'][op]=service.error_result(e)
finally:
 b.close();after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after;report['credentials_unchanged']=original==cookie_hash()
report['passed']=bool(report.get('logged_in') and all(report['checks'].get(k,{}).get('ok') for k in ('timed_message_context','relation','season_relation','favorites','account_history')) and report['stock_unchanged'] and report['credentials_unchanged'])
print('RESULT='+repr(report))
'''
    report=result_from(Adb(out).python('private-schema-only',code,timeout=120))
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
