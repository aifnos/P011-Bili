"""Anonymous search schema diagnostic. No API bodies, tickets or cookies logged."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,archive,result_from,check_bundle
parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Search-Schema-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import sys,os,subprocess,hashlib,time
sys.path.insert(0,ROOT)
import awake_trial as trial
trial.verify()
import service
from urllib.parse import urlencode
json=service.json
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ['http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD']:env.pop(k,None)
def get(url):
 p=subprocess.Popen([MEDIA+'/bin/curl','--silent','--show-error','--connect-timeout','5','--max-time','12','--proto','=https','-A','wiliwili','-e','https://www.bilibili.com/client',url],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:raw,err=p.communicate(timeout=14)
 except subprocess.TimeoutExpired:p.kill();raw,err=p.communicate()
 if p.returncode:return {'transport_exit':p.returncode}
 try:return json.loads(raw.decode('utf-8'))
 except ValueError:return {'invalid_json':True}
nav=get('https://api.bilibili.com/x/web-interface/nav')
result={}
if 'data' in nav and 'wbi_img' in nav['data']:
 keys=nav['data']['wbi_img'];raw=''.join(keys[k].rsplit('/',1)[1].split('.')[0] for k in ('img_url','sub_url'))
 perm=[46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13]
 mixin=''.join(raw[i] for i in perm)
 for label,query in [('hardware','开源硬件'),('raspberry','树莓派')]:
  params={'keyword':query,'search_type':'video','page':'1','page_size':'20','order':'totalrank','wts':str(int(time.time()))}
  q=urlencode(sorted(params.items()));signature=hashlib.md5((q+mixin).encode('utf-8')).hexdigest()
  answer=get('https://api.bilibili.com/x/web-interface/wbi/search/type?'+q+'&w_rid='+signature)
  data=answer.get('data') or {}
  result[label]={'code':answer.get('code'),'data_keys':sorted(data.keys()) if isinstance(data,dict) else [],'transport_exit':answer.get('transport_exit')}
  if isinstance(data,dict):
   for k in ['numResults','numPages','pagesize']:
    if isinstance(data.get(k),int):result[label][k]=data[k]
   result[label]['result_count']=len(data['result']) if isinstance(data.get('result'),list) else None
   result[label]['verification_required']=bool(data.get('v_voucher'))
  native=service.Backend(ROOT,MEDIA+'/bin/bili-api','',ROOT+'/no-anonymous-account',env,lifetime=30)
  try:
   normalized=native.helper('search',{'query':query,'type':'video','page':1})
   result[label]['native_count']=len(normalized.get('items',[]))
   result[label]['native_more']=normalized.get('more')
  except service.Failure as exc:result[label]['native_error']=service.error_result(exc)
  finally:native.close()
else:result['nav_failed']=True
print('RESULT='+repr(result))
'''
report=result_from(adb.python('search-schema',code,timeout=50))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));archive(out)
