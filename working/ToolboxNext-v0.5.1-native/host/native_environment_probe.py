"""Read-only P011 native-UI/environment inventory; never changes the pen."""
import ast
import base64
import datetime
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import zlib

BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
CODE=r'''
import os,sys,hashlib,signal,glob
signal.alarm(20)
pins={'/usr/bin/Z03':'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a','/usr/bin/control_engine':'364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d','/usr/bin/zyb_z03_launch.sh':'7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b'}
def identities():
 rows=[]
 for pid in os.listdir('/proc'):
  if not pid.isdigit():continue
  try:
   raw=open('/proc/'+pid+'/stat').read();end=raw.rindex(')');name=raw[raw.index('(')+1:end];f=raw[end+2:].split()
   if name in ('Z03','control_engine','weston','connmand','bluetoothd'):
    rows.append({'pid':int(pid),'name':name,'state':f[0],'parent':int(f[1]),'starttime':f[19],'exe':os.readlink('/proc/'+pid+'/exe')})
  except OSError:pass
 return rows
before={p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in pins}
assert before==pins,'Firmware identity differs; stop for new baseline'
procs=identities()
assert not os.path.lexists('/mnt/data/p011-menu'),'Existing temporary menu requires inspection'
mods={}
for name in ('ctypes','resource','PyQt5.QtCore','PySide2.QtCore','gi','json','socketserver','fcntl'):
 try:
  m=__import__(name,fromlist=['*']);mods[name]=getattr(m,'QT_VERSION_STR','available')
 except Exception as e:mods[name]=type(e).__name__+':'+str(e)
paths={}
try:
 import ctypes
 qt=ctypes.CDLL('/usr/lib/libQt5QuickTest.so.5')
 fn=getattr(qt,'_Z15quick_test_mainiPPcPKcS2_')
 mods['QtQuickTest.entry']='available'
except Exception as e:mods['QtQuickTest.entry']=type(e).__name__+':'+str(e)
for pattern in ('/usr/bin/qml*','/usr/bin/qt*','/usr/bin/weston*','/usr/bin/gst-play*','/usr/lib/libQt5*.so*','/usr/lib/qt5/plugins/*','/usr/lib/qt5/qml/*','/usr/share/fonts/*','/usr/share/fonts/*/*','/run/user/0/wayland*'):
 paths[pattern]=glob.glob(pattern)[:120]
env={}
for row in procs:
 if row['name']=='Z03':
  for entry in open('/proc/'+str(row['pid'])+'/environ','rb').read(65536).split(b'\x00'):
   key,sep,value=entry.partition(b'=')
   if key in (b'QT_QPA_PLATFORM',b'QT_QPA_PLATFORM_PLUGIN_PATH',b'QML2_IMPORT_PATH',b'QT_PLUGIN_PATH',b'XDG_RUNTIME_DIR',b'WAYLAND_DISPLAY',b'QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS'):
    env[key.decode()]=value.decode('utf-8','replace')
free={}
for path in ('/tmp','/mnt/data'):
 s=os.statvfs(path);free[path]={'available':s.f_bavail*s.f_frsize,'total':s.f_blocks*s.f_frsize}
version=open('/usr/share/version.txt').read(2048)
assert {p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in pins}==before
def stable(rows):return sorted((r['pid'],r['name'],r['parent'],r['starttime'],r['exe']) for r in rows if r['name'] in ('Z03','control_engine'))
assert stable(identities())==stable(procs),'Original process identity changed'
print('RESULT='+repr({'python':sys.version.split()[0],'version':version,'processes':procs,'modules':mods,'paths':paths,'qt_environment':env,'disk':free,'stock_unchanged':True}))
'''


def main():
    adb=shutil.which('adb');assert adb
    check=subprocess.run([adb,'devices'],capture_output=True,timeout=10)
    serials=re.findall(rb'^(\S+)\s+device\s*$',check.stdout,re.M)
    assert check.returncode==0 and len(serials)==1,'Expected exactly one connected ready device'
    packed=base64.b64encode(zlib.compress(CODE.encode(),9)).decode()
    loader='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
    command='(python3 -B -c '+shlex.quote(loader)+'); rc=$?; printf "\n__REMOTE_EXIT__=%s\n" "$rc"'
    assert len(command.encode())<4096
    out=ROOT/'logs'/('ToolboxNative-Environment-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    try:p=subprocess.run([adb,'-s',serials[0].decode(),'shell',command],capture_output=True,timeout=30)
    except subprocess.TimeoutExpired as e:
        (out/'stdout.raw').write_bytes(e.stdout or b'');(out/'stderr.raw').write_bytes(e.stderr or b'')
        raise RuntimeError('Read-only probe timed out; see raw logs') from None
    (out/'stdout.raw').write_bytes(p.stdout);(out/'stderr.raw').write_bytes(p.stderr)
    clean=p.stdout.decode('utf-8','replace').replace('\r\r\n','\n').replace('\r\n','\n')
    exits=re.findall(r'^__REMOTE_EXIT__=(\d+)\s*$',clean,re.M)
    status={'host_exit':p.returncode,'remote_exit':int(exits[-1]) if exits else None,'device_writes':False}
    (out/'status.json').write_text(json.dumps(status,indent=2))
    assert p.returncode==0 and exits==['0'],clean
    result=ast.literal_eval(re.search(r'^RESULT=(.+)$',clean,re.M).group(1))
    (out/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False));print('LOG_DIR='+str(out))


if __name__=='__main__':main()
