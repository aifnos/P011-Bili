"""Read-only, numeric Story trial progress. Never expose raw UI/API logs."""
import argparse,datetime,json,pathlib
from awake_trial import Adb,ROOT,check_bundle,result_from
p=argparse.ArgumentParser();p.add_argument('--bundle',required=True,type=pathlib.Path);a=p.parse_args();meta,_=check_bundle(a.bundle)
if not meta.get('story_probe'):raise ValueError('Not an explicit Story probe')
out=ROOT/'logs'/('BiliP011-StoryPeek-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
code='ROOT='+repr(meta['remote'])+r'''
import os,sys,re
sys.path.insert(0,ROOT+'/stdlib-json35.zip');sys.path.insert(0,ROOT)
import json
result={}
for name in ('candidate.stdout.raw','candidate.stderr.raw'):
 try:
  with open(ROOT+'/'+name,'rb') as f:raw=f.read(8*1024*1024).decode('utf-8','replace')
  result.setdefault('stages',[]).extend(int(x) for x in re.findall(r'P011_STORY_STAGE ([0-9]{1,2})(?=\s)',raw))
  result['qml_errors']=result.get('qml_errors',0)+sum(raw.count(x) for x in ('ReferenceError:','TypeError:','SyntaxError:'))
 except OSError:pass
for name in ('media-state.json','player-state.json','prefetch-result.json','ui-qa-result.json','hardware-error.json','hardware-lifecycle.json'):
 try:
  with open(ROOT+'/'+name) as f:value=json.loads(f.read(32768))
  result[name]={k:v for k,v in value.items() if type(v) in (bool,int,float)}
 except (OSError,ValueError):pass
print('RESULT='+repr(result))
'''
r=result_from(Adb(out).python('story-numeric-status',code));(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps({k:({n:v for n,v in row.items() if k.startswith('hardware-') or n in ('position','active','loaded','switch_pending','cached_media','prefetch_safe','prefix_cache_capable','video_switches','switch_total_ms','passed','step','quality')} if isinstance(row,dict) else row) for k,row in r.items()},indent=2))
print('LOG_DIR='+str(out))
