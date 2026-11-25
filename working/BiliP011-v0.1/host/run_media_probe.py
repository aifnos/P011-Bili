"""Stage a content-addressed private runtime; never alter a vendor file/process."""
import argparse,datetime,hashlib,json,pathlib,re,sys
BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
NATIVE=ROOT/'working/ToolboxNext-v0.5.1-native'
sys.path.insert(0,str(NATIVE/'host'))
from native_trial import Adb,archive,result_from

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=pathlib.Path,required=True)
    parser.add_argument('--play',action='store_true',help='Play a finite public sample at volume 20; touch exits')
    parser.add_argument('--catalog',action='store_true',help='Read recommendation/search/bangumi APIs without login')
    parser.add_argument('--volume',type=int,choices=range(0,101),metavar='0..100',help='Only recent bundles support this process-only gain; lower system volume before 100')
    parser.add_argument('--check-volume',action='store_true',help='Silent libmpv unity-gain check; no SDL, URL or audio output')
    args=parser.parse_args();bundle=args.bundle.resolve()
    if sum([args.play,args.catalog,args.check_volume])>1:parser.error('Choose one probe mode')
    if bundle.parent!=BASE/'out' or not re.fullmatch('media-[0-9a-f]{16}',bundle.name):raise ValueError('Not an owned exported runtime')
    raw=(bundle/'manifest.json').read_bytes();identity=hashlib.sha256(raw).hexdigest()
    if bundle.name!='media-'+identity[:16]:raise ValueError('Manifest identity differs')
    manifest=json.loads(raw);expected={}
    for name,item in manifest.items():
        if not re.fullmatch(r'(lib|bin)/[A-Za-z0-9_.+-]+',name):raise ValueError('Unexpected runtime path')
        path=bundle/name
        if path.is_symlink() or path.stat().st_size!=item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Export changed')
        expected[name]=(item['bytes'],item['sha256'])
    remote='/mnt/data/p011-toolbox/bili-media/'+identity[:16]
    out=ROOT/'logs'/('BiliP011-Media-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False);print('LOG_DIR='+str(out),flush=True)
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    before=result_from(adb.python('before',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
    header='DEST='+repr(remote)+'\n'
    gate=result_from(adb.python('stage-gate',header+safety+"\nrequire_stock(stock_snapshot());owned_directory(DEST,True)\nfree=os.statvfs('/mnt/data');assert free.f_bavail*free.f_frsize>128*1024*1024\nexists=os.path.isdir(DEST+'/bin')\nprint('RESULT='+repr({'exists':exists}))"))
    if not gate['exists']:
        for name in ('bin','lib'):adb.run('push-'+name,['push',str(bundle/name),remote+'/'+name],timeout=45)
    verify=header+'EXPECTED='+repr(expected)+r'''
import os,hashlib
assert os.path.realpath(DEST)==DEST and not os.path.islink(DEST)
for folder in ['bin','lib']:
 assert os.path.realpath(DEST+'/'+folder)==DEST+'/'+folder
 assert set(folder+'/'+v for v in os.listdir(DEST+'/'+folder))==set(n for n in EXPECTED if n.startswith(folder+'/'))
for name,(length,sha) in EXPECTED.items():
 p=DEST+'/'+name
 assert not os.path.islink(p) and os.path.getsize(p)==length
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for block in iter(lambda:f.read(65536),b''):h.update(block)
 assert h.hexdigest()==sha,'Private runtime differs'
 os.chmod(p,0o700 if name.startswith('bin/') else 0o600)
for sub in ['config','cache']:
 p=DEST+'/'+sub
 if not os.path.lexists(p):os.mkdir(p,0o700)
 assert not os.path.islink(p) and os.path.isdir(p)
print('RESULT='+repr({'verified':len(EXPECTED)}))
'''
    result={'identity':identity,'candidate':remote,'account_used':False,'mode':'play' if args.play else ('catalog' if args.catalog else ('silent_volume' if args.check_volume else 'api')),'requested_player_volume':args.volume}
    try:
        adb.python('verify-private-runtime',verify)
        code=header+safety+r'''
import subprocess,ctypes
require_stock(stock_snapshot());owned_directory(DEST)
env=dict(os.environ,LD_LIBRARY_PATH=DEST+'/lib',XDG_RUNTIME_DIR='/run/user/0',WAYLAND_DISPLAY='wayland-0',SDL_VIDEODRIVER='wayland',XDG_CONFIG_HOME=DEST+'/config',XDG_CACHE_HOME=DEST+'/cache')
for k in ['http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD']:env.pop(k,None)
if VOLUME is not None:env['P011_PROBE_VOLUME']=str(VOLUME)
def child_limit():
 class Limit(ctypes.Structure):_fields_=[('cur',ctypes.c_ulong),('max',ctypes.c_ulong)]
 libc=ctypes.CDLL('libc.so.6');lim=Limit(0,0);libc.setrlimit(4,ctypes.byref(lim))
args=[DEST+'/bin/api-probe']
if VOLUME_CHECK:args=[DEST+'/bin/mpv-probe','--volume-check']
if PLAY:args.append('--play')
elif CATALOG:args.append('--catalog')
p=subprocess.Popen(args,env=env,cwd=DEST,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=child_limit)
timed_out=False
try:o,e=p.communicate(timeout=130)
except subprocess.TimeoutExpired:
 timed_out=True;p.kill();o,e=p.communicate()
print('RESULT='+repr({'probe_exit':p.returncode,'timeout':timed_out,'stdout':o,'stderr':e,'own_process_exited':p.poll() is not None}))
'''
        answer=result_from(adb.python('run','PLAY='+repr(args.play)+'\nCATALOG='+repr(args.catalog)+'\nVOLUME='+repr(args.volume)+'\nVOLUME_CHECK='+repr(args.check_volume)+'\n'+code,timeout=140))
        for name in ('stdout','stderr'):(out/('probe.'+name+'.raw')).write_bytes(answer.pop(name))
        result.update(answer)
    finally:
        after=result_from(adb.python('after',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
        result.update(stock_hashes_unchanged=before['hashes']==after['hashes'],stock_processes_unchanged=before['processes']==after['processes'])
        result['passed']=result.get('probe_exit')==0 and result.get('own_process_exited') and result['stock_hashes_unchanged'] and result['stock_processes_unchanged']
        (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2));archive(out)
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
