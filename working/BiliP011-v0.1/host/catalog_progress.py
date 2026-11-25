"""Read only our exact candidate's counts and QML diagnostic lines."""
import argparse,datetime,json,pathlib
from awake_trial import Adb,ROOT,result_from,check_bundle
def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);p.add_argument('--compact',action='store_true');a=p.parse_args();meta,_=check_bundle(a.bundle)
    out=ROOT/'logs'/('BiliP011-CatalogProgress-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    code="""import os,re,sys
root=REMOTE
sys.path.insert(0,root+'/stdlib-json35.zip')
import json
result={'files':[n for n in os.listdir(root) if n.endswith('.json') or n.endswith('.started')],'qml_errors':[]}
for name in ('media-state.json','player-state.json','play-diagnostic.json','hardware-error.json','hardware-seek.json','hardware-lifecycle.json','live-danmaku-result.json'):
 p=root+'/'+name
 if os.path.isfile(p):
  try:
   value=json.loads(open(p).read(32768));result[name]={k:v for k,v in value.items() if type(v) in (bool,int,float) or k in ('phase','error','reason')}
  except (OSError,ValueError):pass
for name in ('candidate.stderr.raw','client.stderr.raw','service.stderr.raw'):
 p=root+'/'+name
 if os.path.isfile(p):
  text=open(p,encoding='utf-8',errors='replace').read()
  result['qml_errors'] += [line[:300] for line in text.splitlines() if re.search(r'Bili(CatalogAutomation|Library|Panel)\\.qml:[0-9]+|Traceback|service\\.py|catalog_features\\.py|SyntaxError|ImportError',line)][:20]
print('RESULT='+repr(result))
""".replace('REMOTE',repr(meta['remote']))
    result=result_from(Adb(out).python('owned-progress',code));(out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if a.compact:
        keys=('generation','position','active','switch_pending','quality','playback_rate','hold_rate_active','hold_rate_restores','chapter_count','subtitle_cues','preview_images','live_danmaku_authenticated','live_danmaku_received','reason','error','seek_target','seek_accepted','seek_video_buffers','seek_audio_buffers','seek_pipeline_state','seek_pipeline_pending','seek_async_done','seek_video_segment_start','seek_audio_segment_start')
        result={k:({n:v for n,v in value.items() if n in keys} if isinstance(value,dict) else value) for k,value in result.items() if k!='files'}
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
