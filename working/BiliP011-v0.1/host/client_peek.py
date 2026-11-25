"""Read only allowlisted UI markers / numerical player state, not raw factory logs."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle
parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Client-Peek-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
adb=Adb(out)
code='ROOT='+repr(meta['remote'])+r'''
import os,sys,re,time
sys.path.insert(0,ROOT)
import service
import awake_trial as trial,config as config
marker=re.compile(r'P011_(?:AWAKE (?:READY|RELEASE|ACQUIRE)|BILI (?:UI_READY|UI_DESTROYED|SCENE_ENTERED|PLAY_REQUEST|LOGIN_CONFIRMED|PAGE (?:catalog (?:recommend|search|following|bangumi)|detail|searchInput|openInput|account)|LIST (?:recommend|search|following|bangumi) [0-9]{1,3}))(?=\s*$)')
events=[];errors=0
for name in ('candidate.stdout.raw','candidate.stderr.raw'):
 try:
  with open(ROOT+'/'+name,'rb') as f:raw=f.read(8*1024*1024).decode('utf-8','replace')
 except FileNotFoundError:continue
 for line in raw.splitlines():
  line=re.sub(r'\x1b\[[0-9;]*m','',line)
  if 'ReferenceError:' in line or 'TypeError:' in line:errors+=1
  match=marker.search(line)
  if match:events.append(match.group())
players={}
for name in ('player-state.json','media-state.json','player-result.json','play-diagnostic.json','player-startup.json'):
 try:
  with open(ROOT+'/'+name) as f:value=service.json.loads(f.read(8192))
  players[name]={k:v for k,v in value.items() if isinstance(v,(bool,int,float))}
  players[name]['age_seconds']=round(max(0,time.time()-os.stat(ROOT+'/'+name).st_mtime),1)
  if value.get('reason') in ('back','limit','stopped','eof','error'):players[name]['reason']=value['reason']
  if value.get('error') in service.ERRORS:players[name]['error']=value['error']
  if value.get('stage') in ('preparing','spawned','prepare_failed','player_exit'):players[name]['stage']=value['stage']
  if value.get('phase') in ('guard','input','sdl','window','gl','mpv_create','mpv_options','mpv_initialize','mpv_render','painter','playback'):players[name]['phase']=value['phase']
 except FileNotFoundError:pass
running=0
for row in trial.procs():
 if row['exe']==config.MEDIA+'/bin/bili-player':
  try:running+=int(trial.environment(row).get('P011_CLIENT_ROOT')==ROOT and trial.alive(row))
  except (FileNotFoundError,ProcessLookupError):pass
print('RESULT='+repr({'markers':events[-40:],'qml_error_count':errors,'player':players,'owned_players_running':running,'complete':os.path.isfile(ROOT+'/result.json')}))
'''
report=result_from(adb.python('safe-status',code))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));print('LOG_DIR='+str(out))
