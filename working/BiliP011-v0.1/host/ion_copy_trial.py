"""Run an owned, synthetic CPU/ION benchmark. No VSP, player, UI or network media."""
import argparse,datetime,hashlib,json,pathlib,re,secrets
SOURCES=('probes/ion_copy_probe.cpp','probes/linux414_ion.h','build/build_ion_copy_probe.py','host/ion_copy_trial.py',
         'third_party/gst-omx-1.14.2-p011/omx/p011_copy.h','third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h',
         'third_party/gst-omx-1.14.2-p011/omx/p011_half.h')
def source_hashes(base):return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in SOURCES}

def artifact_name(digest, sources):
    identity=json.dumps({'sha256':digest,'sources':sources},sort_keys=True,separators=(',',':')).encode('ascii')
    return 'ion-copy-probe-'+hashlib.sha256(identity).hexdigest()[:16]

IDLE_GATE=r'''
def require_private_idle():
 for pid in os.listdir('/proc'):
  if not pid.isdigit() or int(pid)==os.getpid():continue
  try:
   exe=os.readlink('/proc/'+pid+'/exe')
   args=open('/proc/'+pid+'/cmdline','rb').read(4096)
  except OSError:continue
  if exe.startswith('/mnt/data/p011-toolbox/') or b'/mnt/data/p011-toolbox/' in args:
   raise ValueError('Another private trial is active')
require_private_idle()
'''

PAYLOAD=r'''
import subprocess,hashlib,stat
before=stock_snapshot();require_stock(before);owned_directory(DIRECTORY)
require_private_idle()
path=DIRECTORY+'/ion-copy-probe';info=os.lstat(path)
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or hashlib.sha256(open(path,'rb').read()).hexdigest()!=DIGEST:raise ValueError('Probe differs')
os.chmod(path,0o700)
parent=os.getpid()
child=None;timed_out=False;removed=False
try:
 child=subprocess.Popen([path,str(parent)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,P011_ION_COPY_ROOT=DIRECTORY))
 try:o,e=child.communicate(timeout=35)
 except subprocess.TimeoutExpired:
  timed_out=True;child.terminate()
  try:o,e=child.communicate(timeout=5)
  except subprocess.TimeoutExpired:child.kill();o,e=child.communicate(timeout=3)
finally:
 # Never delete a binary/directory while its child might still be running.
 if child is None or child.poll() is not None:
  owned_directory(DIRECTORY)
  if os.listdir(DIRECTORY)!=['ion-copy-probe']:raise ValueError('Unexpected probe directory contents')
  if os.path.islink(path) or hashlib.sha256(open(path,'rb').read()).hexdigest()!=DIGEST:raise ValueError('Cleanup identity differs')
  os.unlink(path);os.rmdir(DIRECTORY);removed=not os.path.exists(DIRECTORY)
lines=[line[9:] for line in o.splitlines() if line.startswith(b'ION_COPY=')]
after=stock_snapshot();require_stock(after)
require_private_idle()
print('RESULT='+repr(dict(record=lines[0].decode('ascii') if len(lines)==1 else '',exit=child.returncode,timeout=timed_out,
 stock_unchanged=before==after,temporary_directory_removed=removed,stdout_raw=o,stderr_raw=e,stderr_bytes=len(e))))
'''

def main():
    from awake_trial import Adb,BASE,NATIVE,ROOT,result_from,archive
    parser=argparse.ArgumentParser();parser.add_argument('--artifact',type=pathlib.Path,required=True);args=parser.parse_args()
    path=args.artifact.resolve()
    if path.parent!=BASE/'out' or not re.fullmatch('ion-copy-probe-[a-f0-9]{16}',path.name):raise ValueError('Not an owned artifact')
    meta=json.loads((path/'build.json').read_text());binary=path/'ion-copy-probe';body=binary.read_bytes();digest=hashlib.sha256(body).hexdigest()
    if binary.is_symlink() or meta.get('schema')!=2 or meta.get('sources')!=source_hashes(BASE) or meta.get('sha256')!=digest or path.name!=artifact_name(digest,meta['sources']) or body[:5]!=b'\x7fELF\x01' or int.from_bytes(body[18:20],'little')!=40:raise ValueError('Stale/non-ARM artifact')
    log=ROOT/'logs'/('BiliP011-IONCopy-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));log.mkdir()
    print('LOG_DIR='+str(log),flush=True);adb=Adb(log);directory='/mnt/data/p011-toolbox/ion-copy-probe-'+secrets.token_hex(12)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    try:
        result_from(adb.python('prepare',safety+'\n'+IDLE_GATE+'\nrequire_stock(stock_snapshot())\nowned_directory("/mnt/data/p011-toolbox")\nassert not os.path.lexists('+repr(directory)+')\nos.mkdir('+repr(directory)+',0o700)\nprint("RESULT="+repr(dict(prepared=True)))'))
        adb.run('push',['push',str(binary),directory+'/ion-copy-probe'])
        result=result_from(adb.python('finite-cpu-only',safety+'\n'+IDLE_GATE+'\nDIRECTORY='+repr(directory)+'\nDIGEST='+repr(digest)+'\n'+PAYLOAD,timeout=50))
        for stream in ('stdout','stderr'):
            (log/('probe.'+stream+'.raw')).write_bytes(result.pop(stream+'_raw'))
        result['probe']=json.loads(result.pop('record') or '{}');result['sha256']=digest
        result['passed']=result['exit']==0 and not result['timeout'] and result['stock_unchanged'] and result['temporary_directory_removed'] and result['probe'].get('passed') is True
        result['playback_passed']=False
        (log/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
        if not result['passed']:raise ValueError('CPU-only ION comparison did not pass')
    finally:
        archive(log)

if __name__=='__main__':main()
