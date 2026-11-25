"""No-window/no-audio startup checks; emits only bounded fixed diagnostics.

Uses the exact frozen player with its environment gate deliberately absent.
Never sends media, touches vendor IPC, changes settings or uses an account.
The option comparison uses CURRENT source, not embedded binary options; this
was the historical root-cause probe. Use client_native_check.py for new gates.
"""
import argparse, datetime, json, pathlib, re
from awake_trial import ROOT, BASE, Adb, archive, check_bundle, result_from

parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=pathlib.Path,required=True);args=parser.parse_args()
meta,_=check_bundle(args.bundle)
source=(BASE/'client/player.cpp').read_text(encoding='utf-8')
line=next(line for line in source.splitlines() if 'for(auto pair:' in line)
options=re.findall(r'(?:make_pair\(|\{)"([a-z-]+)","([^"\r\n]+)"',line)
assert len(options)>=25
out=ROOT/'logs'/('BiliP011-Player-Startup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+'\nOPTIONS='+repr(options)+r"""
import os,sys,ctypes,subprocess,signal
sys.path.insert(0,ROOT)
import awake_trial as trial
trial.verify()
import service
from native_safety import require_stock,stock_snapshot
signal.alarm(25)
before=stock_snapshot();require_stock(before)
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib')
for key in ('P011_CLIENT_ROOT','P011_AWAKE_SESSION','P011_PLAYER_LIMIT','P011_OWNER_PID','LD_PRELOAD'):env.pop(key,None)
p=subprocess.Popen([MEDIA+'/bin/bili-player'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
stdout,stderr=p.communicate(timeout=10)
result={'window_opened':False,'audio_played':False,'account_used':False,'gate_exit':p.returncode,
        'loader_error':b'error while loading shared libraries' in stderr,
        'stdout_bytes':len(stdout),'stderr_bytes':len(stderr)}
# Use a child so the private dynamic loader search path takes effect before
# loading libmpv. No initialize/loadfile/SDL_Init calls are made.
probe=r'''
import ctypes,os,sys
sys.path.insert(0,os.environ['P011_CHECK_ROOT'])
import service
mpv=ctypes.CDLL(os.environ['P011_CHECK_MEDIA']+'/lib/libmpv.so.2')
mpv.mpv_create.restype=ctypes.c_void_p
mpv.mpv_set_option_string.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char_p]
mpv.mpv_set_option_string.restype=ctypes.c_int
mpv.mpv_destroy.argtypes=[ctypes.c_void_p]
m=mpv.mpv_create()
bad=[]
for key,value in OPTIONS:
 rc=mpv.mpv_set_option_string(m,key.encode('ascii'),value.encode('ascii'))
 if rc<0:bad.append((key,rc))
mpv.mpv_destroy(m)
ft=ctypes.CDLL(os.environ['P011_CHECK_MEDIA']+'/lib/libfreetype.so.6')
ft.FT_Init_FreeType.argtypes=[ctypes.POINTER(ctypes.c_void_p)]
ft.FT_New_Face.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_long,ctypes.POINTER(ctypes.c_void_p)]
library=ctypes.c_void_p();face=ctypes.c_void_p()
init=ft.FT_Init_FreeType(ctypes.byref(library))
font=b'/usr/share/fonts/ttf/SourceHanSansSC-Normal.OTF'
face_code=ft.FT_New_Face(library,font,0,ctypes.byref(face)) if not init else -1
print('CHECK='+service.json.dumps({'options_checked':len(OPTIONS),'bad_options':bad,'font_exists':os.path.isfile(font),'freetype_init':init,'font_load':face_code}))
'''
env['P011_CHECK_MEDIA']=MEDIA
env['P011_CHECK_ROOT']=ROOT
q=subprocess.Popen(['/usr/bin/python3','-c','OPTIONS='+repr(OPTIONS)+'\n'+probe],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
data,err=q.communicate(timeout=10)
result['option_check_exit']=q.returncode
for line in data.decode('utf-8','replace').splitlines():
 if line.startswith('CHECK='):result['preflight']=service.json.loads(line[6:])
after=stock_snapshot();require_stock(after)
result['stock_unchanged']=before==after
print('RESULT='+repr(result))
"""
# Nested Python literals are inserted separately, not shell interpolated.
report=result_from(adb.python('player-startup-readonly',code,timeout=35))
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
