"""Stage a hash-identified candidate and run/stop/collect a finite native trial.

Only /mnt/data/p011-toolbox is written. No vendor processes are signalled.
An on-device supervisor enforces the deadline even if USB disconnects.
"""
import argparse
import ast
import base64
import datetime
import hashlib
import json
import pathlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
import zlib

BASE=pathlib.Path(__file__).resolve().parents[1]
WORKSPACE=BASE.parents[1] if BASE.parent.name=='working' and (BASE.parents[1]/'AGENTS.md').is_file() else BASE
AREA='/mnt/data/p011-toolbox'
LAST=BASE/'.last-native-trial.json'


class Adb:
    def __init__(self,out):
        self.out=out;self.sequence=0
        executable=shutil.which('adb')
        if not executable:raise RuntimeError('ADB is not available on this PC')
        p=subprocess.run([executable,'devices'],capture_output=True,timeout=10)
        serials=re.findall(rb'^(\S+)\s+device\s*$',p.stdout,re.M)
        if p.returncode or len(serials)!=1:raise RuntimeError('Expected exactly one connected ready P011')
        self.prefix=[executable,'-s',serials[0].decode('ascii')]

    def run(self,name,args,timeout=30):
        self.sequence+=1;tag='%02d-%s'%(self.sequence,name)
        try:
            p=subprocess.run(self.prefix+args,capture_output=True,timeout=timeout)
            stdout,stderr,code=p.stdout,p.stderr,p.returncode
        except subprocess.TimeoutExpired as exc:
            stdout,stderr,code=exc.stdout or b'',exc.stderr or b'',None
        (self.out/(tag+'.stdout.raw')).write_bytes(stdout)
        (self.out/(tag+'.stderr.raw')).write_bytes(stderr)
        clean=stdout.decode('utf-8','replace').replace('\r\r\n','\n').replace('\r\n','\n')
        exits=re.findall(r'^__REMOTE_EXIT__=(\d+)\s*$',clean,re.M) if args[0]=='shell' else []
        status={'host_exit':code,'remote_exit':int(exits[-1]) if exits else None,'timeout':code is None}
        (self.out/(tag+'.status.json')).write_text(json.dumps(status,indent=2),encoding='utf-8')
        if code!=0 or (args[0]=='shell' and exits!=['0']):
            raise RuntimeError(name+' failed; see raw logs in '+str(self.out))
        return clean

    def python(self,name,code,timeout=30):
        packed=base64.b64encode(zlib.compress(code.encode('utf-8'),9)).decode('ascii')
        loader='import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
        command='(python3 -B -c '+shlex.quote(loader)+'); rc=$?; printf "\n__REMOTE_EXIT__=%s\n" "$rc"'
        if len(command.encode())>=4096:raise ValueError('Legacy ADB command too long; use an owned helper file')
        return self.run(name,['shell',command],timeout)


def result_from(text):
    match=re.search(r'^RESULT=(.+)$',text,re.M)
    if not match:raise ValueError('Missing explicit remote result')
    return ast.literal_eval(match.group(1))


def archive(out):
    target=out.with_suffix('.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(out.rglob('*')):
            if path.is_file():bundle.write(path,path.relative_to(out).as_posix())
    with zipfile.ZipFile(target) as bundle:
        if bundle.testzip() is not None:raise ValueError('Results ZIP CRC failed')
    print('RESULT_ZIP='+str(target))
    print('ZIP_SHA256='+hashlib.sha256(target.read_bytes()).hexdigest())


def load_run(path):
    run=json.loads(path.read_text(encoding='utf-8'))
    if not re.fullmatch(re.escape(AREA)+r'/sessions/\d{8}-\d{6}-[0-9a-f]{8}',run['session']):raise ValueError('Invalid saved session path')
    if not re.fullmatch(re.escape(AREA)+r'/candidates/native-051-[0-9a-f]{16}',run['candidate']):raise ValueError('Invalid saved candidate path')
    return run


def check_status(adb,run):
    code="""import os,sys
sys.path.insert(0,CANDIDATE+'/runtime')
from native_safety import owned_directory,stock_snapshot,verify_candidate
verify_candidate(CANDIDATE);owned_directory(SESSION)
answer={'complete':os.path.isfile(SESSION+'/result.json'),'started':os.path.isfile(SESSION+'/started.json')}
if answer['complete']:
 with open(SESSION+'/result.json') as handle:answer['result_text']=handle.read(131072)
else:
 answer['lock_present']=os.path.isdir('/mnt/data/p011-toolbox/native.lock')
print('RESULT='+repr(answer))
"""
    return result_from(adb.python('status','CANDIDATE='+repr(run['candidate'])+'\nSESSION='+repr(run['session'])+'\n'+code))


def collect(adb,run,out):
    status=check_status(adb,run)
    if not status['complete']:
        print('SESSION_STILL_RUNNING=True');return False
    result=json.loads(status.pop('result_text'))
    device=out/'device'
    adb.run('pull-session',['pull',run['session'],str(device)])
    (out/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print('UI_EXIT='+str(result['ui_exit']))
    print('STOCK_PROCESSES_UNCHANGED='+str(result['stock_processes_unchanged']))
    print('STOCK_HASHES_UNCHANGED='+str(result['stock_hashes_unchanged']))
    print('NATIVE_TRIAL_PASS='+str(result['passed']))
    return True


def start(adb,out,seconds,automated):
    source={}
    for folder in ('runtime','device','web'):
        for file in sorted((BASE/folder).iterdir()):
            if file.is_file() and file.suffix in ('.py','.qml','.js','.html','.css','.svg'):
                source[file.relative_to(BASE).as_posix()]=file.read_bytes()
    manifest=''.join(hashlib.sha256(data).hexdigest()+' '+str(len(data))+' '+name+'\n' for name,data in sorted(source.items())).encode('ascii')
    identity=hashlib.sha256(manifest).hexdigest()
    candidate=AREA+'/candidates/native-051-'+identity[:16]
    runid=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
    session=AREA+'/sessions/'+runid
    safety=(BASE/'runtime/native_safety.py').read_text(encoding='utf-8')
    preflight=safety+"\nrequire_stock(stock_snapshot())\nassert not os.path.lexists(AREA+'/native.lock'),'A native trial or stale lock needs inspection'\n"
    preflight+="s=os.statvfs('/mnt/data');assert s.f_bavail*s.f_frsize>64*1024*1024,'Insufficient user space'\n"
    preflight+="owned_directory(AREA+'/candidates',True)\nowned_directory(AREA+'/sessions',True)\n"
    preflight+='candidate='+repr(candidate)+'\nexists=os.path.lexists(candidate)\n'
    preflight+="if exists:verify_candidate(candidate)\nelse:os.mkdir(candidate,0o700)\n"
    preflight+='os.mkdir('+repr(session)+",0o700)\nprint('RESULT='+repr({'candidate_exists':exists,'stock_gate':True}))\n"
    # Local helpers remain full-size files. This compressed read/gate operation
    # fits the legacy 4 KiB ADB command limit and never reads stdin to EOF.
    gate=result_from(adb.python('preflight',preflight))
    stage=out/'staged-source';stage.mkdir()
    for name,data in source.items():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (stage/'SOURCE.sha256').write_bytes(manifest)
    if not gate['candidate_exists']:
        for folder in ('runtime','device','web'):
            adb.run('push-'+folder,['push',str(stage/folder),candidate+'/'+folder])
        adb.run('push-manifest',['push',str(stage/'SOURCE.sha256'),candidate+'/SOURCE.sha256'])
    run={'candidate':candidate,'session':session,'source_identity':identity,'seconds':seconds,'automated':automated,'host_start_logs':str(out)}
    (out/'run.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
    LAST.write_text(json.dumps(run,indent=2),encoding='utf-8')
    code="""import os,sys,subprocess
sys.path.insert(0,CANDIDATE+'/runtime')
from native_safety import verify_candidate,require_stock,stock_snapshot
assert verify_candidate(CANDIDATE)==SOURCE
require_stock(stock_snapshot())
args=[sys.executable,'-B',CANDIDATE+'/runtime/native_session.py','--session',SESSION,'--seconds',str(SECONDS)]
if AUTOMATED:args.append('--automated')
with open(SESSION+'/supervisor.stdout.raw','xb') as stdout,open(SESSION+'/supervisor.stderr.raw','xb') as stderr:
 child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
print('RESULT='+repr({'supervisor_pid':child.pid,'deadline_seconds':SECONDS+35,'vendor_untouched':True}))
"""
    header='CANDIDATE='+repr(candidate)+'\nSESSION='+repr(session)+'\nSOURCE='+repr(identity)+'\nSECONDS='+str(seconds)+'\nAUTOMATED='+str(automated)+'\n'
    launched=result_from(adb.python('launch',header+code))
    (out/'launch.json').write_text(json.dumps(launched,indent=2),encoding='utf-8')
    print('SESSION='+session);print('SOURCE_ID='+identity);print('FINITE_UI_STARTED=True')
    if automated:
        deadline=time.monotonic()+seconds+40
        while time.monotonic()<deadline:
            time.sleep(2)
            if check_status(adb,run)['complete']:
                collect(adb,run,out);return
        raise RuntimeError('Completion not confirmed; use status/collect, do not assume restoration')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','smoke','status','stop','collect'))
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--run',type=pathlib.Path,default=LAST)
    args=parser.parse_args()
    if not 15<=args.seconds<=600:parser.error('--seconds must be 15 to 600')
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out=WORKSPACE/'logs'/('ToolboxNative-'+args.action+'-'+stamp);out.mkdir(parents=True)
    print('LOG_DIR='+str(out),flush=True)
    adb=Adb(out)
    if args.action in ('start','smoke'):start(adb,out,30 if args.action=='smoke' else args.seconds,args.action=='smoke')
    else:
        run=load_run(args.run);(out/'run.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
        if args.action=='status':
            status=check_status(adb,run)
            if 'result_text' in status:status['result']=json.loads(status.pop('result_text'))
            (out/'status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
            print('COMPLETE='+str(status['complete']));print('STARTED='+str(status['started']))
        elif args.action=='collect':collect(adb,run,out)
        else:
            status=check_status(adb,run)
            if not status['complete']:
                code="import os;path="+repr(run['session']+'/STOP')+"\nfd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);print('STOP_REQUESTED=True')"
                adb.python('request-stop',code)
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    time.sleep(1)
                    if check_status(adb,run)['complete']:break
            collect(adb,run,out)
    archive(out)
    if args.action=='smoke':return 0 if json.loads((out/'result.json').read_text(encoding='utf-8'))['passed'] else 1
    return 0


if __name__=='__main__':sys.exit(main())
