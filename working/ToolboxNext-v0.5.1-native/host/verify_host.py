"""One-click PC-only tests and a results ZIP. This script never invokes ADB."""
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import zipfile

BASE=pathlib.Path(__file__).resolve().parents[1]


def main():
    workspace=BASE.parents[1] if BASE.parent.name=='working' and (BASE.parents[1]/'AGENTS.md').is_file() else BASE
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out=workspace/'logs'/('ToolboxNative-HostVerify-'+stamp)
    out.mkdir(parents=True,exist_ok=False)
    rows=[]
    def run(name,command,timeout=50):
        begin=time.monotonic()
        try:
            result=subprocess.run(command,cwd=str(BASE),capture_output=True,timeout=timeout)
            rawout,rawerr,code=result.stdout,result.stderr,result.returncode
            status='PASS' if code==0 else 'FAIL'
        except subprocess.TimeoutExpired as exc:
            rawout,rawerr,code=exc.stdout or b'',exc.stderr or b'',None;status='TIMEOUT'
        except OSError as exc:
            rawout,rawerr,code=b'',(type(exc).__name__+': '+str(exc)).encode(),None;status='UNAVAILABLE'
        (out/(name+'.stdout.raw')).write_bytes(rawout)
        (out/(name+'.stderr.raw')).write_bytes(rawerr)
        row={'test':name,'status':status,'host_exit':code,'elapsed_seconds':round(time.monotonic()-begin,2)}
        rows.append(row);print(name+': '+status,flush=True)
    run('backend-windows' if os.name=='nt' else 'backend-native',[sys.executable,'-B','-m','unittest','discover','-s',str(BASE/'tests'),'-p','test_*.py','-v'])
    run('game-rules',[shutil.which('node') or 'node',str(BASE/'tests/test_games.js')])
    run('qml-preview',[sys.executable,'-B',str(BASE/'host/preview.py'),'--screenshots',str(out/'screenshots')])
    if os.name=='nt' and shutil.which('wsl'):
        listing=subprocess.run(['wsl','--list','--quiet'],capture_output=True,timeout=15)
        text=listing.stdout.decode('utf-16-le','replace') if b'\x00' in listing.stdout else listing.stdout.decode('utf-8','replace')
        if 'kali-linux' in text:
            path='/mnt/'+BASE.drive[0].lower()+BASE.as_posix()[2:]+'/tests'
            run('backend-linux',['wsl','-d','kali-linux','--exec','/usr/bin/python3','-B','-m','unittest','discover','-s',path,'-p','test_*.py','-v'])
        else:rows.append({'test':'backend-linux','status':'SKIP','reason':'kali-linux is not installed'})
    else:rows.append({'test':'backend-linux','status':'SKIP','reason':'WSL is not available; native test remains separate'})
    manifest=[]
    for file in sorted(BASE.iterdir()):
        if file.is_file() and file.suffix.lower() in ('.md','.cmd'):
            manifest.append({'path':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    for folder in ('runtime','device','web','host','tests'):
        for file in sorted((BASE/folder).rglob('*')):
            if file.is_file() and not file.is_symlink() and '__pycache__' not in file.parts:
                manifest.append({'path':file.relative_to(BASE).as_posix(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    result={'candidate':'ToolboxNext-v0.5.1-native','scope':'PC only; not a pen UI/LAN/audio acceptance',
            'adb_invoked':False,'tests':rows,'passed':all(r['status'] in ('PASS','SKIP') for r in rows)}
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(out.rglob('*')):
            if file.is_file():bundle.write(file,file.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as bundle:assert bundle.testzip() is None
    print('RESULT_DIR='+str(out));print('RESULT_ZIP='+str(archive));print('SHA256='+hashlib.sha256(archive.read_bytes()).hexdigest())
    return 0 if result['passed'] else 1


if __name__=='__main__':sys.exit(main())
