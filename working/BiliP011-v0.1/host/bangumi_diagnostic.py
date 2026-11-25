"""Anonymous season/episode/authorized-stream checks; never plays or logs URLs."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive
parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Bangumi-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import os,sys,signal
sys.path.insert(0,ROOT)
import awake_trial as trial
trial.verify()
import service
signal.alarm(100)
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ['http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD']:env.pop(k,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',ROOT+'/no-anonymous-account',env,lifetime=95)
result={'account_used':False,'played':False,'seasons':[]}
try:
 catalog=b.helper('bangumi',{'page':1})
 rows=[x for x in catalog['items'] if x.get('season') or x.get('ep')]
 result['catalog_count']=len(rows)
 for row in rows[:2]:
  entry={}
  try:
   detail=b.helper('detail',service.safe_args('detail',row));entry['detail_ok']=True;entry['episode_count']=len(detail['parts'])
   if detail['parts']:
    try:
     stream=b.helper('play',service.safe_args('play',detail['parts'][0]))
     entry['stream_ok']=bool(stream.get('video'));entry['separate_audio']=bool(stream.get('audio'));entry['preview']=stream.get('preview') is True
    except service.Failure as exc:entry['stream_error']=service.error_result(exc)
  except service.Failure as exc:entry['detail_error']=service.error_result(exc)
  result['seasons'].append(entry)
finally:b.close()
print('RESULT='+repr(result))
'''
report=result_from(adb.python('anonymous-bangumi',code,timeout=110))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));archive(out)
