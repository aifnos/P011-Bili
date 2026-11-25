"""Exact frozen binaries: no-window player preflight plus offline API selftest."""
import argparse,datetime,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle,archive

parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
out=ROOT/'logs'/('BiliP011-Client-Native-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+'\nEXPECTED_PROTOCOL='+repr(meta.get('player_protocol',1))+r'''
import os,sys,subprocess,signal
sys.path.insert(0,ROOT)
import awake_trial as trial,service,config
from native_safety import stock_snapshot,require_stock
trial.verify();signal.alarm(30)
before=stock_snapshot();require_stock(before)
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for k in ('LD_PRELOAD','P011_CLIENT_ROOT','P011_AWAKE_SESSION','P011_PLAYER_LIMIT','P011_OWNER_PID'):env.pop(k,None)
b=service.Backend(ROOT,MEDIA+'/bin/bili-api','',ROOT+'/no-anonymous-account',env,lifetime=25)
report={'window_opened':False,'audio_played':False,'account_used':False,'network_used':False}
try:
 report['api_selftest']=b.helper('self_test',{})
 p=subprocess.Popen([MEDIA+'/bin/bili-player','--preflight'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
 try:body,_=p.communicate(timeout=12)
 except subprocess.TimeoutExpired:p.kill();p.communicate();raise RuntimeError('preflight timed out')
 value=service.json.loads(body.decode('utf-8'))
 report['player_preflight']={key:value[key] for key in ('ok','exit_code','mpv_code','freetype_init','font_load','window_opened','audio_played')}
 if 'progress_overlay_selftest' in value:report['player_preflight']['progress_overlay_selftest']=value['progress_overlay_selftest'] is True
 report['player_preflight']['protocol_version']=value.get('protocol_version',1)
 if value.get('protocol_version',1)!=EXPECTED_PROTOCOL:raise RuntimeError('Frozen player protocol differs')
 report['player_process_exit']=p.returncode
 if 'bin/bili-hw' in config.MEDIA_FILES:
  hardware_env={k:v for k,v in env.items() if not k.startswith(('LD_','GST_'))}
  hardware_env['GST_REGISTRY']=ROOT+'/gst-hw-preflight-registry.bin'
  hardware_env['GST_REGISTRY_FORK']='no'
  if 'lib/gst/libgstomx.so' in config.MEDIA_FILES:hardware_env['GST_PLUGIN_PATH_1_0']=MEDIA+'/lib/gst'
  p=subprocess.Popen([MEDIA+'/bin/bili-hw','--preflight'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=hardware_env)
  try:body,_=p.communicate(timeout=8)
  except subprocess.TimeoutExpired:p.kill();p.communicate();raise RuntimeError('hardware preflight timed out')
  if p.returncode:raise RuntimeError('hardware loader preflight failed: '+str(p.returncode))
  report['hardware_preflight']=service.json.loads(body.decode('utf-8'))
  if report['hardware_preflight'].get('ok') is not True:raise RuntimeError('hardware ABI preflight failed')
 if getattr(config,'TOOLBOX',False):
  from toolbox_runtime import Toolbox,USER_ROOT
  from native_safety import AREA
  if USER_ROOT!=AREA+'/user':raise RuntimeError('Toolbox user-data compatibility path differs')
  work=ROOT+'/toolbox-preflight-'+os.urandom(4).hex();os.mkdir(work,0o700)
  toolbox=Toolbox(work,automated=True)
  try:
   entries=toolbox.state.store.listing('Text')['entries']
   value=toolbox.state.store.text(entries[0]['path'])['text']
   report['toolbox_preflight']={'utf8_files':len(entries)==1 and value.startswith('\u5c0f\u5c4f\u5e55'),
       'ram_available':toolbox.state.latest['memory'].get('total',0)>0,'lan_opened':toolbox.state.transfer_state()['enabled'],
       'existing_user_root_preserved':USER_ROOT==AREA+'/user'}
   if not report['toolbox_preflight']['utf8_files'] or not report['toolbox_preflight']['ram_available'] or report['toolbox_preflight']['lan_opened']:raise RuntimeError('toolbox preflight failed')
  finally:toolbox.close()
finally:
 b.close();after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
report['passed']=report['player_process_exit']==0 and report['player_preflight']['ok'] and report['api_selftest']['checks']>=13 and report['stock_unchanged']
print('RESULT='+repr(report))
'''
report=result_from(adb.python('offline-native-selftest',code,timeout=40))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
if not report.get('passed'):raise SystemExit(1)
