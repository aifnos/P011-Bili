"""Generate one undisplayed QR and poll once, retaining only fixed diagnostics.

No existing account access, QR image/URL/key output, login confirmation or UI.
"""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive

parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Login-Check-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import os,sys,time,signal,re,subprocess
sys.path.insert(0,ROOT)
import awake_trial as trial,service
from native_safety import stock_snapshot,require_stock
trial.verify();signal.alarm(75)
before=stock_snapshot();require_stock(before)
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):env.pop(k,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',ROOT+'/no-anonymous-account',env,lifetime=65)
report={'existing_account_used':False,'qr_displayed':False,'qr_content_logged':False,'login_confirmed':False}
def operation(op):
 key=b.submit(op,{})
 until=time.monotonic()+28
 while time.monotonic()<until:
  result=b.result(key)
  if not result.get('pending'):return result
  time.sleep(.1)
 return {'ok':False,'error':'HELPER_TIMEOUT','code':-1}
try:
 result=operation('qr_new')
 report['generate']={'ok':result.get('ok') is True}
 if result.get('ok'):
  report['generate']['matrix_size']=len(result['data']['matrix'])
  result=None
  poll=operation('qr_poll')
  report['poll']={'ok':poll.get('ok') is True}
  if poll.get('ok'):report['poll']['code']=poll['data'].get('code')
  else:report['poll'].update(error=poll.get('error'),code=poll.get('code'))
 else:
  report['generate'].update(error=result.get('error'),code=result.get('code'))
  # Distinguish native API normalization from the public-service normalizer.
  try:
   native=b.helper('qr_new',{})
   report['native_generate']={'ok':True,'matrix_size':len(native.get('matrix',[])),
      'key_length':len(native.get('qr_key','')),'key_valid':bool(re.match(r'^[0-9A-Za-z_-]{8,128}$',native.get('qr_key','')))}
  except service.Failure as exc:report['native_generate']=service.error_result(exc)
  # Raw response stays in this process. Emit only schema and host categories.
  from urllib.parse import urlsplit
  p=subprocess.Popen([MEDIA+'/bin/curl','--silent','--connect-timeout','5','--max-time','12','--proto','=https',
      '-A','wiliwili','-e','https://www.bilibili.com/client',
      'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  try:raw,_=p.communicate(timeout=14)
  except subprocess.TimeoutExpired:p.kill();raw,_=p.communicate()
  schema={'transport_exit':p.returncode}
  if p.returncode==0:
   try:
    obj=service.json.loads(raw.decode('utf-8'));d=obj.get('data') or {};url=d.get('url','');key=d.get('qrcode_key','')
    parts=urlsplit(url)
    schema.update(api_code=obj.get('code') if isinstance(obj.get('code'),int) else None,
        url_present=isinstance(url,str) and bool(url),key_length=len(key) if isinstance(key,str) else -1,
        url_scheme=parts.scheme if parts.scheme in ('https','http') else 'other',
        url_host=parts.hostname if parts.hostname in ('passport.bilibili.com','www.bilibili.com','b23.tv') else 'other')
    labels=(parts.hostname or '').split('.')
    schema['host_domain']='.'.join(labels[-2:]) if all(re.match(r'^[a-z0-9-]{1,30}$',v) for v in labels[-2:]) else 'unrecognized'
    schema['host_prefix']=labels[0] if len(labels)>2 and re.match(r'^[a-z]{1,16}$',labels[0]) else 'omitted'
   except (ValueError,TypeError,AttributeError):schema['parse_failed']=True
  report['response_schema']=schema
finally:
 b.close();after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
report['passed']=report['generate']['ok'] and report.get('poll',{}).get('ok') and report.get('poll',{}).get('code')==86101 and report['stock_unchanged']
print('RESULT='+repr(report))
'''
report=result_from(adb.python('private-qr-summary',code,timeout=85))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
if not report.get('passed'):raise SystemExit(1)
