"""Read the requested following feed on the pen; log schema counts only.

Uses the user's already-authorized cookie jar in place. Never copies it, uses
other account endpoints, emits videos/names/IDs, modifies follows, or writes it.
"""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive

parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Following-Schema-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import sys,os,subprocess,signal,stat
sys.path.insert(0,ROOT)
import awake_trial as trial,service
trial.verify();signal.alarm(20)
cookie='/mnt/data/p011-toolbox/bili-account/cookies.txt'
info=os.lstat(cookie)
assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_mode&0o777==0o600
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):env.pop(k,None)
p=subprocess.Popen([MEDIA+'/bin/curl','--silent','--connect-timeout','5','--max-time','12','--proto','=https',
 '-A','wiliwili','-e','https://www.bilibili.com/client','--cookie',cookie,
 'https://api.bilibili.com/x/polymer/web-dynamic/desktop/v1/feed/video?page=1&offset='],
 env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
try:raw,_=p.communicate(timeout=14)
except subprocess.TimeoutExpired:p.kill();raw,_=p.communicate()
report={'transport_exit':p.returncode,'cookie_content_logged':False,'feed_content_logged':False,'account_modified':False}
if p.returncode==0:
 try:
  answer=service.json.loads(raw.decode('utf-8'));d=answer.get('data') or {};rows=d.get('items') or []
  report['api_code']=answer.get('code') if isinstance(answer.get('code'),int) else None
  report['raw_count']=len(rows) if isinstance(rows,list) else -1
  report['flat_video_count']=sum(1 for r in rows if isinstance(r,dict) and isinstance(r.get('bvid'),str) and r['bvid'].startswith('BV'))
  report['wrapped_video_count']=sum(1 for r in rows if isinstance(r,dict) and isinstance(r.get('modules'),dict) and isinstance(r['modules'].get('module_dynamic'),dict) and isinstance(r['modules']['module_dynamic'].get('major'),dict) and isinstance(r['modules']['module_dynamic']['major'].get('archive'),dict))
  report['author_object_count']=sum(1 for r in rows if isinstance(r,dict) and isinstance(r.get('author'),dict))
  report['more']=bool(d.get('has_more'));report['offset_present']=bool(d.get('offset'))
 except (ValueError,TypeError,AttributeError):report['parse_failed']=True
trial.verify()
print('RESULT='+repr(report))
'''
report=result_from(adb.python('following-counts-only',code,timeout=30))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
