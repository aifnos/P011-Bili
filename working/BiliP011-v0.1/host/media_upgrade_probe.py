"""No-window target probe: official Story and authorized stream matrix only.
No account, URL, title, device address or raw response is returned to the PC.
"""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive
p=argparse.ArgumentParser();p.add_argument('--bundle',required=True,type=pathlib.Path);args=p.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-MediaUpgrade-Probe-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import os,sys,signal
sys.path.insert(0,ROOT)
import awake_trial as trial,service
from native_safety import stock_snapshot,require_stock
trial.verify();signal.alarm(100);before=stock_snapshot();require_stock(before)
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for key in ('LD_PRELOAD','http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):env.pop(key,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',ROOT+'/no-anonymous-account',env,lifetime=90)
report={'account_used':False,'window_opened':False,'audio_played':False}
try:
 report['selftest']=b.helper('self_test',{})
 feed=b.helper('story',{'page':1})
 report['story']={'source':feed.get('source'),'items':len(feed['items']),'cid_present':all(x.get('cid','').isdigit() for x in feed['items'])}
 feed2=b.helper('story',{'page':2,'offset':feed.get('offset','')})
 report['story']['next_items']=len(feed2['items'])
 report['story']['new_items']=len(set(x['bvid'] for x in feed2['items'])-set(x['bvid'] for x in feed['items']))
 detail=b.helper('detail',{'kind':'video','bvid':'BV1Da411Y7U4'})
 target=detail['parts'][0]
 matrix=b.helper('qualities',target)
 report['qualities']=[x['id'] for x in matrix['items']]
 report['codecs']=[x['id'] for x in matrix['codecs']]
 report['streams']={}
 for c in (7,12,13):
  try:
   d=b.helper('play',dict(target,quality=0,codec=c))
   report['streams'][str(c)]={'ok':bool(d.get('video')),'codec':d['codec'],'quality':d['quality'],'width':d['width'],'height':d['height']}
  except service.Failure as e:report['streams'][str(c)]=service.error_result(e)
finally:
 b.close();after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
report['passed']=report['stock_unchanged'] and report['story']['source']=='official-story' and report['story']['items']>0 and report['story']['new_items']>0 and all(x.get('ok') for x in report['streams'].values())
print('RESULT='+repr(report))
'''
adb=Adb(out);report=result_from(adb.python('native-stream-matrix',code,timeout=110))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
if not report.get('passed'):raise SystemExit(1)
