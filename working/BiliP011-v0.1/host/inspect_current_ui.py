"""Read-only live UI diagnostics; no input, reboot, stop, or account requests."""
import argparse
import datetime
import json
import re
from pathlib import Path
from awake_trial import Adb, ROOT, check_bundle, result_from

PROBE = r'''
import os,sys,glob,re
sys.path.insert(0,ROOT+'/stdlib-json35.zip');sys.path.insert(0,ROOT)
import json,awake_trial as trial
trial.verify()
data={'read_only':True,'session_complete':os.path.isfile(ROOT+'/result.json')}
data['processes']={}
for name in ('candidate','worker','guardian','bili-service'):
 row=trial.refresh(trial.saved(name))
 data['processes'][name]={'alive':bool(trial.alive(row)),'pid':row.get('pid') if row else None,'state':row.get('state') if row else None}
 if name=='candidate' and row and trial.alive(row):
  with open('/proc/'+str(row['pid'])+'/environ','rb') as f:env=f.read(32768).split(b'\0')
  keys=(b'QT_QPA_PLATFORM',b'QT_QPA_PLATFORM_PLUGIN_PATH',b'QT_WAYLAND_FORCE_DPI',b'QT_SCALE_FACTOR',b'QT_SCREEN_SCALE_FACTORS',b'QT_AUTO_SCREEN_SCALE_FACTOR',b'QT_IM_MODULE',b'WAYLAND_DISPLAY',b'XDG_RUNTIME_DIR')
  data['ui_environment']={part.split(b'=',1)[0].decode():part.split(b'=',1)[1].decode('utf-8','replace') for part in env if b'=' in part and part.split(b'=',1)[0] in keys}
data['display']={}
for pat in ('/sys/class/graphics/fb*/virtual_size','/sys/class/graphics/fb*/bits_per_pixel','/sys/class/graphics/fb*/stride','/sys/class/graphics/fb*/name','/sys/class/drm/*/modes','/sys/class/drm/*/status','/sys/class/backlight/*/actual_brightness'):
 for p in glob.glob(pat):
  try:
   with open(p) as f:data['display'][p]=f.read(1024).strip()
  except OSError:pass
data['capture_tools']=[]
for folder in ('/usr/bin','/bin','/usr/sbin'):
 for n in os.listdir(folder):
  if re.search(r'screen|capture|snapshot|fbgrab|drm',n,re.I):data['capture_tools'].append(folder+'/'+n)
data['states']={}
for n in ('player-state.json','surface-info.json','media-state.json','display-prepare.json','window-placement.json','presentation-startup.json'):
 p=ROOT+'/'+n
 if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p)<32768:
  try:
   with open(p) as f:state=json.load(f)
   data['states'][n]={k:v for k,v in state.items() if isinstance(v,(bool,int,float)) or k in ('phase','reason','failure','mode','format','backend') or k=='stage' and v in ('wm-info','handles','registry','registry-listener','clock-event','clock-id')}
  except (OSError,ValueError):pass
print('RESULT='+repr(data))
'''

LOGS = r'''
import os
files={}
for n in ('candidate.stdout.raw','candidate.stderr.raw','bili-service.stderr.raw','bili-service.stdout.raw'):
 p=ROOT+'/'+n
 if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p)<8*1024*1024:
  with open(p,'rb') as f:files[n]=f.read()
print('RESULT='+repr(files))
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True)
    meta,_=check_bundle(parser.parse_args().bundle)
    out=ROOT/'logs'/('BiliP011-UILiveInspect-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
    prefix='ROOT='+repr(meta['remote'])+'\n'
    result=result_from(adb.python('live-state',prefix+PROBE,timeout=15))
    raw=result_from(adb.python('private-ui-logs',prefix+LOGS,timeout=15))
    pages=[];warnings=[]
    for name,blob in raw.items():
        (out/name).write_bytes(blob)
        for line in blob.decode('utf-8','replace').splitlines():
            match=re.search(r'P011_BILI PAGE ([A-Za-z0-9_-]+)',line)
            if match:pages.append(match.group(1))
            if '.qml:' in line and any(x in line for x in ('Error','Cannot','Unable','Binding loop','anchors','undefined','not defined','not a function')):
                warnings.append(line[:600])
    result['recent_pages']=pages[-20:];result['qml_warnings']=warnings[-30:]
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2));print('PRIVATE_RAW_LOGS: do not share without review')

if __name__=='__main__':main()
