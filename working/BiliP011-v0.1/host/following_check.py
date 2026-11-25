"""Read-only pen check of UI-normalized followed videos and private pagination.

Uses the existing, user-authorized pen cookie in place. Reports counts only;
never copies cookies, video metadata, cursor values, or raw helper responses.
Requires stock UI, and never starts a window, playback, or a login operation.
"""
import argparse
import ast
import datetime
import json
import pathlib
from awake_trial import ROOT, Adb, result_from, check_bundle, archive


def device_code(meta):
    return 'ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import sys,os,stat,signal
sys.path.insert(0,ROOT)
import awake_trial as trial,service
from native_safety import stock_snapshot,require_stock,owned_directory
trial.verify();signal.alarm(105)
before=stock_snapshot();require_stock(before)
account=owned_directory('/mnt/data/p011-toolbox/bili-account',False)
assert os.lstat(account).st_mode&0o777==0o700
cookie=account+'/cookies.txt'
def cookie_identity():
 info=os.lstat(cookie)
 assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_mode&0o777==0o600
 return (info.st_dev,info.st_ino,info.st_size,info.st_mtime,info.st_mode)
cookie_before=cookie_identity()
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for key in ('LD_PRELOAD','http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):env.pop(key,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',account,env,lifetime=100)
report={'window_opened':False,'audio_played':False,'account_used':True,
 'cookie_content_logged':False,'feed_content_logged':False,'pages':[]}
try:
 cursor=''
 for number in (1,2):
  args=service.safe_args('following',{'page':number,'offset':cursor})
  data=b.dispatch('following',args,0)
  rows=data['items']
  valid=sum(1 for row in rows if row['kind']=='video' and service.identifier(row['bvid'],r'BV[0-9A-Za-z]{10}'))
  report['pages'].append({'page':number,'count':len(rows),'valid_videos':valid,
   'titles_present':sum(1 for row in rows if row['title']),
   'creators_present':sum(1 for row in rows if row['up']),
   'more':data['more'],'cursor_present':bool(data['offset'])})
  if data['more'] and not data['offset']:raise service.Failure('API_SCHEMA')
  if not data['more']:break
  if data['offset']==cursor:raise service.Failure('API_SCHEMA')
  cursor=data['offset']
except service.Failure as exc:
 report['error']=exc.error;report['code']=exc.code
except Exception:
 report['error']='INTERNAL'
finally:
 b.close();after=stock_snapshot();require_stock(after)
 report['stock_unchanged']=before==after
 report['cookie_unchanged']=cookie_before==cookie_identity()
report['pagination_checked']=len(report['pages'])==2
report['passed']=bool(report['pages'] and report['pages'][0]['count']>0 and
 all(page['valid_videos']==page['count'] for page in report['pages']) and
 report['stock_unchanged'] and report['cookie_unchanged'] and 'error' not in report)
print('RESULT='+repr(report))
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',type=pathlib.Path,required=True)
    args=parser.parse_args()
    meta,_=check_bundle(args.bundle)
    code=device_code(meta)
    ast.parse(code,feature_version=(3,5))
    out=ROOT/'logs'/('BiliP011-Following-Check-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    report=result_from(Adb(out).python('following-normalized-counts-only',code,timeout=115))
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));archive(out)
    if not report.get('passed'):raise SystemExit(1)


if __name__=='__main__':main()
