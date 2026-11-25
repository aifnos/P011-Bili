"""Read-only target quality/comment evidence. All content/credentials stay on pen."""
import argparse,ast,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args()
    meta,_=check_bundle(a.bundle)
    code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+r'''
import os,sys,signal,stat,ctypes
sys.path.insert(0,ROOT)
import awake_trial as trial,service
from native_safety import stock_snapshot,require_stock,owned_directory
trial.child_limits();trial.verify();signal.alarm(190)
before=stock_snapshot();require_stock(before)
account=owned_directory('/mnt/data/p011-toolbox/bili-account',False)
assert os.stat(account).st_mode&0o777==0o700
def identity():
 p=account+'/cookies.txt';s=os.lstat(p)
 assert stat.S_ISREG(s.st_mode) and s.st_mode&0o777==0o600
 return (s.st_dev,s.st_ino,s.st_size,s.st_mtime,s.st_mode)
prior=identity()
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ('LD_PRELOAD','http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):env.pop(k,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',account,env,lifetime=180)
report={'audio_played':False,'window_opened':False,'account_used_in_place':True,'private_content_logged':False,'checks':{}}
def execute(name,op,args):
 try:
  d=b.dispatch(op,service.safe_args(op,args),0)
  report['checks'][name]={'ok':True}
  return d
 except service.Failure as e:
  report['checks'][name]={'ok':False,'error':e.error,'code':e.code}
  return None
try:
 report['selftest']=b.helper('self_test',{})
 d=execute('detail','detail',{'kind':'video','bvid':'BV1Da411Y7U4'})
 if d and d['parts']:
  part=d['parts'][0]
  q=execute('qualities','qualities',part)
  if q:
   report['checks']['qualities']['ids']=[r['id'] for r in q['items']]
   requested=next((r['id'] for r in q['items'] if r['id']>0),0)
   value=b.helper('play',dict(service.safe_args('play',dict(part,quality=requested))))
   report['checks']['selected_stream']={'ok':bool(value.get('video')),'requested':requested,
    'actual':value.get('quality'),'width':value.get('width'),'height':value.get('height'),'played':False}
  if meta_protocol==2:
   raw_dm=b.helper('danmaku_xml',{'cid':part['cid']})
   report['checks']['danmaku_wire']={'ok':True,'bytes':len(raw_dm),'first4_hex':raw_dm[:4].hex()}
   dm=service.decode_danmaku(raw_dm)
   report['checks']['danmaku']={'ok':True,'count':len(dm['items']),'truncated':dm.get('truncated') is True,
    'sorted':all(dm['items'][i]['time']<=dm['items'][i+1]['time'] for i in range(max(0,len(dm['items'])-1)))}
  params={'aid':part.get('aid',''),'bvid':part['bvid'],'mode':3,'next':0}
  c=execute('comments_hot','comments',params)
  if c:
   report['checks']['comments_hot'].update(count=len(c['items']),more=c['more'],named=sum(bool(r['author']) for r in c['items']),with_text=sum(bool(r['text']) for r in c['items']))
   if c['more']:
    c2=execute('comments_page2','comments',dict(params,next=c['next']))
    if c2:report['checks']['comments_page2']['count']=len(c2['items'])
   for row in c['items']:
    if row['replies']:
     replies=execute('comment_replies','comments',dict(params,root=row['id']))
     if replies:report['checks']['comment_replies']['count']=len(replies['items'])
     break
  latest=execute('comments_latest','comments',dict(params,mode=2))
  if latest:report['checks']['comments_latest']['count']=len(latest['items'])
except service.Failure as e:report.update(error=e.error,code=e.code)
except Exception:report['error']='INTERNAL'
finally:
 b.close();after=stock_snapshot();require_stock(after)
 report['stock_unchanged']=before==after;report['cookie_unchanged']=prior==identity()
report['passed']=bool(all(report['checks'].get(k,{}).get('ok') for k in ('detail','qualities','selected_stream','comments_hot','comments_latest')) and
 all(v.get('ok') for v in report['checks'].values()) and report['stock_unchanged'] and report['cookie_unchanged'] and 'error' not in report)
print('RESULT='+repr(report))
'''
    code='meta_protocol='+repr(meta.get('player_protocol',1))+'\n'+code
    ast.parse(code,feature_version=(3,5))
    out=ROOT/'logs'/('BiliP011-Extensions-Check-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True)
    report=result_from(Adb(out).python('extensions-counts-only',code,timeout=205))
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));archive(out)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
