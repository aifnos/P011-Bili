"""Run only our fixed, hash-identified, 10-second-deadline graphics probe."""
import datetime
import hashlib
import json
import pathlib
import sys

BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
NATIVE=ROOT/'working'/'ToolboxNext-v0.5.1-native'
sys.path.insert(0,str(NATIVE/'host'))
from native_trial import Adb,archive,result_from


def main():
    binary=BASE/'out/gles-probe'
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    remote='/mnt/data/p011-toolbox/bili-probes/'+digest[:16]
    out=ROOT/'logs'/('BiliP011-GLES-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    adb=Adb(out)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    before=result_from(adb.python('before',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
    header='DEST='+repr(remote)+'\nEXPECTED='+repr(digest)+'\n'
    ready=result_from(adb.python('stage-gate',header+safety+"\nrequire_stock(stock_snapshot());owned_directory(DEST,True)\np=DEST+'/gles-probe'\nif os.path.lexists(p):\n assert not os.path.islink(p) and digest(p)==EXPECTED,'Existing probe differs'\nprint('RESULT='+repr({'exists':os.path.isfile(p)}))"))
    if not ready['exists']:
        adb.run('push-own-probe',['push',str(binary),remote+'/gles-probe'])
    result={}
    try:
        result=result_from(adb.python('run',header+safety+r'''
import subprocess,ctypes
require_stock(stock_snapshot());owned_directory(DEST)
binary=DEST+'/gles-probe'
assert not os.path.islink(binary) and digest(binary)==EXPECTED
os.chmod(binary,0o700)
for sub in ['cache','config']:owned_directory(DEST+'/'+sub,True)
env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/0',WAYLAND_DISPLAY='wayland-0',SDL_VIDEODRIVER='wayland',XDG_CACHE_HOME=DEST+'/cache',XDG_CONFIG_HOME=DEST+'/config')
def child_limit():
 class Limit(ctypes.Structure):_fields_=[('cur',ctypes.c_ulong),('max',ctypes.c_ulong)]
 libc=ctypes.CDLL('libc.so.6');lim=Limit(0,0);libc.setrlimit(4,ctypes.byref(lim))
child=subprocess.Popen([binary],env=env,cwd=DEST,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=child_limit)
timed_out=False
try:o,e=child.communicate(timeout=15)
except subprocess.TimeoutExpired:
 timed_out=True;child.kill();o,e=child.communicate()
print('RESULT='+repr({'probe_exit':child.returncode,'timeout':timed_out,'stdout':o,'stderr':e,'own_process_exited':child.poll() is not None}))
''',timeout=25))
        (out/'probe.stdout.raw').write_bytes(result.pop('stdout'))
        (out/'probe.stderr.raw').write_bytes(result.pop('stderr'))
    finally:
        after=result_from(adb.python('after',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
        result.update(binary_sha256=digest,candidate=remote,stock_hashes_unchanged=before['hashes']==after['hashes'],stock_processes_unchanged=before['processes']==after['processes'])
        result['passed']=result.get('probe_exit')==0 and result.get('own_process_exited') and result['stock_hashes_unchanged'] and result['stock_processes_unchanged']
        (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2));print('LOG_DIR='+str(out));archive(out)
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
