"""Read-only display/idle inspection. Does not wake, inhibit, or change settings."""
import datetime,json,pathlib,sys
BASE=pathlib.Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
NATIVE=ROOT/'working/ToolboxNext-v0.5.1-native';sys.path.insert(0,str(NATIVE/'host'))
from native_trial import Adb,result_from,archive

def main():
    out=ROOT/'logs'/('BiliP011-Screen-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    before=result_from(adb.python('before',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
    data=result_from(adb.python('display-state',r'''
import os,glob,re,struct
values={}
for pat in ['/sys/class/backlight/*/brightness','/sys/class/backlight/*/actual_brightness','/sys/class/backlight/*/bl_power','/sys/class/backlight/*/max_brightness','/sys/power/state']:
 for p in glob.glob(pat):
  try:
   with open(p) as f:values[p]=f.read(2048)
  except OSError:pass
config={}
for p in ['/etc/xdg/weston/weston.ini','/etc/xdg/weston.ini','/etc/weston.ini','/usr/share/weston.config']:
 if os.path.isfile(p):
  with open(p) as f:config[p]=[v.strip() for v in f if re.search('idle|sleep|backlight|output|transform',v,re.I)]
process=[]
for p in glob.glob('/proc/[0-9]*'):
 try:
  with open(p+'/comm') as f:name=f.read().strip()
  if name=='weston':
   with open(p+'/cmdline','rb') as f:process.append(f.read(4096).replace(b'\0',b' ').decode('utf-8','replace'))
 except OSError:pass
tools={k:glob.glob('/usr/bin/'+k)+glob.glob('/bin/'+k) for k in ['weston-info','wayland-info','dbus-send','gdbus','busctl','wflinfo']}
idle={};owners={};tcp=[]
for p in glob.glob('/proc/[0-9]*'):
 try:
  exe=os.readlink(p+'/exe')
  if exe not in ['/usr/bin/control_engine','/usr/bin/Z03']:continue
  for fd in glob.glob(p+'/fd/*'):
   try:
    link=os.readlink(fd)
    if link.startswith('socket:['):owners[link[8:-1]]=os.path.basename(exe)
   except OSError:pass
  if exe=='/usr/bin/control_engine':
   # Two exact scalar fields, proven against the gated v2.4.0 ET_EXEC ELF.
   # Read-only /proc/mem, no ptrace attach, process stop, or memory write.
   with open(p+'/mem','rb',buffering=0) as f:
    for name,address in [('screen_off_seconds',0x47728),('auto_screen_off_enabled',0x47748)]:
     f.seek(address);idle[name]=struct.unpack('<I',f.read(4))[0]
 except OSError:pass # Unrelated short-lived /proc entries may disappear.
with open('/proc/net/tcp') as f:
 for line in f:
  row=line.split()
  if len(row)>9 and (row[1].endswith(':1BB4') or row[2].endswith(':1BB4')):
   tcp.append({'state':row[3],'owner':owners.get(row[9],'unknown'),'loopback_local':row[1].startswith('0100007F:'),'loopback_remote':row[2].startswith('0100007F:')})
print('RESULT='+repr({'values':values,'weston_config':config,'weston_command':process,'tools':tools,'vendor_idle_fields':idle,'vendor_ui_tcp7092':tcp}))
'''))
    commands={
        'wayland-registry':['/usr/bin/weston-info'],
        'dbus-system-names':['/usr/bin/dbus-send','--system','--print-reply','--dest=org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus.ListNames'],
        'suspendblocker-introspect':['/usr/bin/dbus-send','--system','--print-reply','--dest=com.unisoc.suspendblocker','/com/unisoc/suspendblocker','org.freedesktop.DBus.Introspectable.Introspect'],
    }
    for name,args in commands.items():
        script='ARGS='+repr(args)+r'''
import os,subprocess
env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/0',WAYLAND_DISPLAY='wayland-0')
p=subprocess.Popen(ARGS,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:o,e=p.communicate(timeout=8)
except subprocess.TimeoutExpired:p.kill();o,e=p.communicate()
print('RESULT='+repr({'exit':p.returncode,'stdout':o,'stderr':e}))
'''
        answer=result_from(adb.python(name,script,timeout=15))
        for stream in ('stdout','stderr'):(out/(name+'.'+stream+'.raw')).write_bytes(answer.pop(stream))
        data[name]=answer
    after=result_from(adb.python('after',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
    data.update(device_writes=False,stock_hashes_unchanged=before['hashes']==after['hashes'],stock_processes_unchanged=before['processes']==after['processes'])
    (out/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(data,ensure_ascii=False,indent=2));print('LOG_DIR='+str(out));archive(out)

if __name__=='__main__':main()
