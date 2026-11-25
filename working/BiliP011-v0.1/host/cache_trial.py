"""Bounded synthetic-fixture cache decode; never touches default media or UI."""
import argparse,datetime,hashlib,json,pathlib,re,secrets
from cache_artifact import validate
from ion_copy_trial import IDLE_GATE

def parse_probe(output):
    prefix=b'CACHE_DECODE='
    rows=[line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
    if len(rows)!=1:return {}
    result=json.loads(rows[0])
    return result if isinstance(result,dict) else {}

PAYLOAD=r'''
import hashlib,stat,subprocess
before=stock_snapshot();require_stock(before);require_private_idle();owned_directory(DIRECTORY)
for path,pin in VENDOR_PINS.items():
 if hashlib.sha256(open(path,'rb').read()).hexdigest()!=pin:raise ValueError('Vendor cache ABI differs')
for name,pin in HASHES.items():
 path=DIRECTORY+'/'+name;info=os.lstat(path)
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or hashlib.sha256(open(path,'rb').read()).hexdigest()!=pin:raise ValueError('Cache probe file differs')
 os.chmod(path,0o700 if name=='cache-decode-probe' else 0o600)
env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','GST_'))}
env['P011_CACHE_PROBE_ROOT']=DIRECTORY;env['P011_CACHE_PROBE_MODE']=MODE
env['P011_CACHE_PROBE_CHECK']=CHECK
child=None;timed_out=False;removed=False
try:
 child=subprocess.Popen([DIRECTORY+'/cache-decode-probe',str(os.getpid())],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
 try:o,e=child.communicate(timeout=45)
 except subprocess.TimeoutExpired:
  timed_out=True;child.terminate()
  try:o,e=child.communicate(timeout=5)
  except subprocess.TimeoutExpired:child.kill();o,e=child.communicate(timeout=3)
finally:
 if child is None or child.poll() is not None:
  owned_directory(DIRECTORY)
  names=os.listdir(DIRECTORY)
  if any(name not in list(HASHES)+['gst-registry.bin','cache-helper.py'] or not stat.S_ISREG(os.lstat(DIRECTORY+'/'+name).st_mode) for name in names):raise ValueError('Unexpected cache probe directory entries')
  for name in names:os.unlink(DIRECTORY+'/'+name)
  os.rmdir(DIRECTORY);removed=not os.path.exists(DIRECTORY)
after=stock_snapshot();require_stock(after);require_private_idle()
print('RESULT='+repr(dict(exit=child.returncode,timeout=timed_out,stdout_raw=o,stderr_raw=e,
 stock_unchanged=before==after,vendor_unchanged=all(hashlib.sha256(open(p,'rb').read()).hexdigest()==h for p,h in VENDOR_PINS.items()),
 temporary_directory_removed=removed)))
'''

def cleanup_staged(adb,safety,directory,hashes):
    if not re.fullmatch('/mnt/data/p011-toolbox/ion-cache-probe-[a-f0-9]{24}',directory):raise ValueError('Not an exact scratch directory')
    code=safety+'\nDIRECTORY='+repr(directory)+'\nHASHES='+repr(hashes)+r'''
import stat
before=stock_snapshot();require_stock(before);require_private_idle()
removed=[]
if os.path.lexists(DIRECTORY):
 owned_directory(DIRECTORY);names=os.listdir(DIRECTORY)
 for name in names:
  path=DIRECTORY+'/'+name;info=os.lstat(path)
  if name not in list(HASHES)+['gst-registry.bin'] or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Unknown scratch contents')
  if name in HASHES and digest(path)!=HASHES[name]:raise ValueError('Scratch file changed')
 for name in names:os.unlink(DIRECTORY+'/'+name);removed.append(name)
 os.rmdir(DIRECTORY)
after=stock_snapshot();require_stock(after)
print('RESULT='+repr(dict(removed_files=removed,temporary_directory_removed=not os.path.lexists(DIRECTORY),stock_unchanged=before==after)))
'''
    from awake_trial import result_from
    return result_from(adb.python('independent-owned-cleanup',code))

def main():
    from awake_trial import Adb,BASE,NATIVE,ROOT,result_from,archive
    parser=argparse.ArgumentParser();parser.add_argument('--artifact',type=pathlib.Path,required=True)
    parser.add_argument('--fixture',type=pathlib.Path,required=True);parser.add_argument('--mode',choices=('uncached','cached'),required=True)
    parser.add_argument('--check',choices=('pixels','timing'),default='pixels')
    args=parser.parse_args();artifact=args.artifact.resolve();meta=validate(BASE,artifact)
    fixture=args.fixture.resolve()
    if fixture.parent!=BASE/'out' or not re.fullmatch('cache-fixture-[a-f0-9]{16}',fixture.name):raise ValueError('Not a generated fixture')
    record=json.loads((fixture/'fixture.json').read_text());video=fixture/'input.mp4';body=video.read_bytes();sha=hashlib.sha256(body).hexdigest()
    if video.is_symlink() or not record.get('synthetic') or record.get('sha256')!=sha or fixture.name!='cache-fixture-'+sha[:16] or (record.get('width'),record.get('height'),record.get('fps'),record.get('frames'))!=(1920,1080,60,240):raise ValueError('Synthetic fixture differs')
    log=ROOT/'logs'/('BiliP011-CacheDecode-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));log.mkdir();print('LOG_DIR='+str(log),flush=True)
    adb=Adb(log);directory='/mnt/data/p011-toolbox/ion-cache-probe-'+secrets.token_hex(12)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+IDLE_GATE
    hashes=dict(meta['binaries'],**{'input.mp4':sha})
    code=safety+'\nDIRECTORY='+repr(directory)+'\nMODE='+repr(args.mode)+'\nCHECK='+repr(args.check)+'\nVENDOR_PINS='+repr(meta['pins'])+'\nHASHES='+repr(hashes)+'\n'+PAYLOAD
    helper=log/'cache-helper.py';helper.write_bytes(code.encode('utf-8'))
    hashes['cache-helper.py']=hashlib.sha256(helper.read_bytes()).hexdigest()
    (log/'identity.json').write_text(json.dumps(dict(artifact=artifact.name,hashes=hashes,mode=args.mode,check=args.check,directory=directory),indent=2))
    try:
        result_from(adb.python('prepare',safety+'\nrequire_stock(stock_snapshot())\nowned_directory("/mnt/data/p011-toolbox")\nassert not os.path.lexists('+repr(directory)+')\nos.mkdir('+repr(directory)+',0o700)\nprint("RESULT="+repr(dict(prepared=True)))'))
        for name in meta['binaries']:adb.run('push-'+name,['push',str(artifact/name),directory+'/'+name])
        adb.run('push-synthetic-fixture',['push',str(video),directory+'/input.mp4'])
        adb.run('push-verified-helper',['push',str(helper),directory+'/cache-helper.py'])
        loader=safety+'\nowned_directory('+repr(directory)+')\nHELPER='+repr(directory+'/cache-helper.py')+'\nEXPECTED='+repr(hashes['cache-helper.py'])+r'''
import stat
info=os.lstat(HELPER)
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>65536:raise ValueError('Unsafe helper')
raw=open(HELPER,'rb').read()
if hashlib.sha256(raw).hexdigest()!=EXPECTED:raise ValueError('Helper identity differs')
exec(compile(raw,HELPER,'exec'))
'''
        result=result_from(adb.python('finite-cache-decode',loader,timeout=60))
        output=result.pop('stdout_raw');error=result.pop('stderr_raw')
        (log/'probe.stdout.raw').write_bytes(output);(log/'probe.stderr.raw').write_bytes(error)
        result['probe']=parse_probe(output)
        result.update(mode=args.mode,check=args.check,artifact=artifact.name,fixture_sha256=sha,stderr_bytes=len(error),playback_passed=False)
        result['passed']=result['exit']==0 and not result['timeout'] and result['stock_unchanged'] and result['vendor_unchanged'] and result['temporary_directory_removed'] and result['probe'].get('passed') is True
        (log/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        brief=dict(result);brief['probe']=dict(result['probe']);brief['probe']['frames']='saved_in_result.json'
        print(json.dumps(brief,indent=2))
        if not result['passed']:raise ValueError('Synthetic decode cache gate failed')
    finally:
        try:
            cleanup=cleanup_staged(adb,safety,directory,hashes)
            (log/'cleanup.json').write_text(json.dumps(cleanup,indent=2),encoding='utf-8')
        finally:archive(log)

if __name__=='__main__':main()
