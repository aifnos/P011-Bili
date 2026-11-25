"""Explicit isolated v2.4.0 backend smoke; never launches a new pen UI.

Source is packed into a unique temporary script (legacy ADB does not forward
stdin EOF reliably). Only owned /tmp files are written; no LAN listener,
player, D-Bus or original process control. A finite
alarm, exact firmware pins, unchanged process identities and explicit owned-file
cleanup are mandatory. Raw stdout/stderr and both exits are retained on the PC.
"""
import ast
import datetime
import hashlib
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import secrets

BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
CHECK=r'''
import os,sys,hashlib,signal,socket,time,types,io
signal.alarm(35)
pins={'/usr/bin/Z03':'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a','/usr/bin/control_engine':'364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d','/usr/bin/zyb_z03_launch.sh':'7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b'}
def identities():
 result={}
 for pid in os.listdir('/proc'):
  if not pid.isdigit():continue
  try:
   raw=open('/proc/'+pid+'/stat').read();name=raw[raw.index('(')+1:raw.rindex(')')]
   if name in ('Z03','control_engine'):
    fields=raw[raw.rindex(')')+2:].split();result[pid]=(name,fields[19])
  except OSError:pass
 return result
def hashes():return {p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in pins}
assert hashes()==pins,'Firmware identity mismatch'
assert not os.path.lexists('/mnt/data/p011-menu'),'Temporary menu already exists'
before=identities()
assert any(v[0]=='Z03' for v in before.values()),'Stock Z03 is not running'
for name,source in SOURCES:
 module=types.ModuleType(name);module.__file__='/nonexistent-p011-smoke/runtime/'+name+'.py'
 sys.modules[name]=module;exec(compile(source,module.__file__,'exec'),module.__dict__)
from server import State,BoundedServer,local_addresses
from storage import FOLDERS
import p011_json as J
import threading
root=os.path.realpath('/tmp')+'/p011-next-smoke-'+os.urandom(8).hex()
os.mkdir(root,0o700)
state=None;http=None;results={};created=[]
try:
 state=State(root)
 assert state.store.fd_mode,'Target must use directory descriptor confinement'
 payload='学习笔后端测试'.encode('utf-8');name='Text/smoke.txt'
 state.store.write_new(name,io.BytesIO(payload),len(payload));created.append(name)
 assert state.store.text(name)['text']=='学习笔后端测试'
 assert state.store.listing('Text')['entries'][0]['path']==name
 results['user_files_roundtrip']=True
 try:state.store.open_file('Text/../../etc/passwd');raise AssertionError('Traversal accepted')
 except ValueError:pass
 results['traversal_rejected']=True
 os.symlink('/etc',root+'/Text/escape');created.append('Text/escape')
 try:state.store.open_file('Text/escape/passwd');raise AssertionError('Symlink accepted')
 except OSError:pass
 results['symlink_rejected']=True
 state.save_score('snake',42);created.append('.toolbox-state/scores.txt')
 state.save_score('snake',3);assert state.scores['snake']==42
 results['scores_persist']=True
 time.sleep(.12)
 with state.lock:state.latest=state.sampler.sample()
 metrics=state.latest
 assert metrics['cpu_percent'] is not None and metrics['memory']['total']>0 and metrics['uptime']>0
 assert metrics['storage']['available']>0 and state.sampler.processes()
 results['live_metrics']=True
 # Only report counts, never IP/MAC, process arguments or user identifiers.
 results['private_interface_count']=len(local_addresses())
 http=BoundedServer(('127.0.0.1',0),state)
 worker=threading.Thread(target=http.serve_forever);worker.daemon=True;worker.start()
 def request(path,token):
  conn=socket.create_connection(http.server_address,timeout=4)
  wire=('GET '+path+' HTTP/1.0\r\nHost: '+http.expected_host+'\r\nX-P011-Token: '+token+'\r\n\r\n').encode('ascii')
  conn.sendall(wire);out=b''
  while True:
   block=conn.recv(65536)
   if not block:break
   out+=block
  conn.close();head,body=out.split(b'\r\n\r\n',1)
  return int(head.split(b' ')[1]),body
 code,body=request('/api/state',state.token)
 assert code==200 and b'"ok":true' in body.replace(b' ',b'')
 assert request('/api/state','invalid')[0]==403
 assert request('/api/download?path=Text/smoke.txt',state.token)[1]==payload
 results['authenticated_loopback_http']=True
 result=state.export('samples');created.append(result['path'])
 handle,info=state.store.open_file(result['path']);handle.close();assert info.st_size>0
 results['sample_export']=True
 assert state.lan is None and state.audio.audio is None
 results['no_lan_or_playback_started']=True
finally:
 if http:http.shutdown();http.server_close()
 if state:state.close()
 # Only exact files created by this test; never recursive deletion/globs.
 for name in reversed(created):
  path=os.path.join(root,name)
  if os.path.lexists(path):os.unlink(path)
 for name in ('.toolbox-state',)+FOLDERS:
  path=os.path.join(root,name)
  if os.path.isdir(path):os.rmdir(path)
 os.rmdir(root)
results['temporary_files_removed']=not os.path.exists(root)
legacy_readers=0
for pid in os.listdir('/proc'):
 if not pid.isdigit():continue
 try:
  if b'<isolated-backend-smoke>' in open('/proc/'+pid+'/cmdline','rb').read(8192):legacy_readers+=1
 except OSError:pass
results['prior_stdin_probe_not_running']=legacy_readers==0
results['owned_temporary_directory_count']=len([p for p in os.listdir(os.path.realpath('/tmp')) if p.startswith('p011-next-smoke-')])
results['stock_hashes_unchanged']=hashes()==pins
results['stock_processes_unchanged']=identities()==before
assert results['stock_hashes_unchanged'] and results['stock_processes_unchanged'] and results['prior_stdin_probe_not_running']
print('RESULT='+repr(results))
'''


def main():
    adb=shutil.which('adb');assert adb,'adb is not available'
    rows=subprocess.run([adb,'devices'],capture_output=True,timeout=10,check=True).stdout
    serials=re.findall(rb'^(\S+)\s+device\s*$',rows,re.M)
    assert len(serials)==1,'Expected exactly one ready device'
    names=('p011_json','storage','metrics','minhttp','audio','server')
    sources=[(name,(BASE/'runtime'/(name+'.py')).read_text(encoding='utf-8')) for name in names]
    payload=('SOURCES='+repr(sources)+'\n'+CHECK).encode('utf-8')
    remote='/tmp/p011-next-bootstrap-'+secrets.token_hex(8)+'.py'
    command='(python3 -B '+shlex.quote(remote)+'); rc=$?; printf "\n__REMOTE_EXIT__=%s\n" "$rc"'
    out=ROOT/'logs'/('ToolboxNext-DeviceBackend-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    artifact=out/'isolated-smoke.generated.py';artifact.write_bytes(payload)
    target=[adb,'-s',serials[0].decode()]
    pushed=subprocess.run(target+['push',str(artifact),remote],capture_output=True,timeout=15)
    (out/'push.stdout.raw').write_bytes(pushed.stdout);(out/'push.stderr.raw').write_bytes(pushed.stderr)
    assert pushed.returncode==0,'Temporary test upload failed (see raw logs)'
    try:
        p=subprocess.run(target+['shell',command],capture_output=True,timeout=45)
    except subprocess.TimeoutExpired as exc:
        (out/'stdout.raw').write_bytes(exc.stdout or b'');(out/'stderr.raw').write_bytes(exc.stderr or b'')
        (out/'status.json').write_text(json.dumps({'host_exit':None,'remote_exit':None,'timeout':True},indent=2))
        raise RuntimeError('Device test timed out; inspect logs and owned temporary path before retry') from None
    finally:
        # Exact single-file cleanup only if its bytes still match this run.
        code='import os,hashlib;p='+repr(remote)+';assert hashlib.sha256(open(p,"rb").read()).hexdigest()=='+repr(hashlib.sha256(payload).hexdigest())+';os.unlink(p);assert not os.path.exists(p);print("BOOTSTRAP_REMOVED=True")'
        cleanup=subprocess.run(target+['shell','python3 -B -c '+shlex.quote(code)],capture_output=True,timeout=10)
        (out/'cleanup.stdout.raw').write_bytes(cleanup.stdout);(out/'cleanup.stderr.raw').write_bytes(cleanup.stderr)
    (out/'stdout.raw').write_bytes(p.stdout);(out/'stderr.raw').write_bytes(p.stderr)
    clean=p.stdout.decode('utf-8','replace').replace('\r\r\n','\n').replace('\r\n','\n')
    exits=re.findall(r'^__REMOTE_EXIT__=(\d+)\s*$',clean,re.M)
    cleanup_verified=cleanup.returncode==0 and b'BOOTSTRAP_REMOVED=True' in cleanup.stdout
    status={'host_exit':p.returncode,'remote_exit':int(exits[-1]) if exits else None,'cleanup_host_exit':cleanup.returncode,'cleanup_remote_verified':cleanup_verified,
            'scope':'unique temporary user files and authenticated loopback only; no pen UI/LAN/audio test'}
    (out/'status.json').write_text(json.dumps(status,indent=2))
    print('LOG_DIR='+str(out))
    assert p.returncode==0 and exits==['0'] and cleanup_verified,clean+p.stderr.decode('utf-8','replace')
    result=ast.literal_eval(re.search(r'^RESULT=(.+)$',clean,re.M).group(1))
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
