"""One-click narrow awake trial controller. Start requires a fresh built bundle.
Start switches the stock UI only after device-side guardian is armed. Existing
60-second probe wrappers remain unchanged and never switch the original UI.
"""
import argparse
import ast
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time

BASE=pathlib.Path(__file__).resolve().parents[1]; ROOT=BASE.parents[1]
NATIVE=ROOT/'working/ToolboxNext-v0.5.1-native'; sys.path.insert(0,str(NATIVE/'host'))
from native_trial import Adb, result_from, archive


def check_bundle(path):
    path=path.resolve()
    if path.parent!=BASE/'out' or not re.fullmatch('awake-[0-9a-f]{24}',path.name): raise ValueError('Not a trial bundle')
    meta=json.loads((path/'build-result.json').read_text())
    if meta['session']!=path.name[6:] or meta['remote']!='/mnt/data/p011-toolbox/bili-awake/'+meta['session']: raise ValueError('Identity mismatch')
    raw=(path/'SOURCE.sha256').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=meta['manifest_sha256']: raise ValueError('Manifest differs')
    names=[]
    for line in raw.decode().splitlines():
        sha,length,name=line.split(' ')
        if not re.fullmatch('[A-Za-z0-9_.-]+',name): raise ValueError('Unsafe filename')
        data=(path/name).read_bytes()
        if len(data)!=int(length) or hashlib.sha256(data).hexdigest()!=sha: raise ValueError('Source differs')
        names.append(name)
    return meta,names


def command(adb,meta,name,args):
    code='import sys\nsys.path.insert(0,'+repr(meta['remote'])+')\nimport awake_trial as trial\nsys.argv='+repr(['awake_trial.py']+args)+'\ntrial.main()\n'
    return adb.python(name,code,timeout=20)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','start','play','pause-test','stop','status','peek','collect'])
    p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args()
    meta,names=check_bundle(a.bundle); remote=meta['remote']
    out=ROOT/'logs'/('BiliP011-Awake-'+a.action+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));out.mkdir()
    print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
    if a.action=='stage':
        safety=(NATIVE/'runtime/native_safety.py').read_text()
        result_from(adb.python('preflight',safety+'\nrequire_stock(stock_snapshot())\nowned_directory('+repr(remote.rsplit('/',1)[0])+',True)\nassert not os.path.lexists('+repr(remote)+')\nos.mkdir('+repr(remote)+',0o700)\nprint("RESULT="+repr({"gate":True}))\n'))
        media=pathlib.Path(meta['media_local']); media_manifest=json.loads((media/'manifest.json').read_bytes())
        # Stage the isolated media copy without running it or reusing old gates.
        media_remote=meta['media_remote']
        found=result_from(adb.python('media-path',safety+'\nowned_directory('+repr(media_remote)+',True)\nprint("RESULT="+repr({"exists":os.path.isdir('+repr(media_remote+'/bin')+')}))\n'))
        if not found['exists']:
            for folder in ('bin','lib'): adb.run('push-'+folder,['push',str(media/folder),media_remote+'/'+folder],timeout=45)
        for name in names+['SOURCE.sha256']:adb.run('push-'+name,['push',str(a.bundle/name),remote+'/'+name],timeout=30)
        script='import sys,os\nsys.path.insert(0,'+repr(remote)+')\nimport awake_trial as trial\ntrial.verify()\n'
        script+='for name in '+repr(names+['SOURCE.sha256'])+':os.chmod('+repr(remote+'/')+'+name,0o700 if name=="Z03.awake-candidate" else 0o600)\n'
        script+='for name in '+repr(list(media_manifest))+':os.chmod('+repr(media_remote+'/')+'+name,0o700 if name.startswith("bin/") else 0o600)\n'
        script+='for name in ["config","cache"]:\n p='+repr(media_remote+'/')+'+name\n if not os.path.exists(p):os.mkdir(p,0o700)\n assert not os.path.islink(p) and os.path.isdir(p)\n'
        script+='print("RESULT="+repr({"staged":True}))'
        print(result_from(adb.python('verify-stage',script)))
    elif a.action=='peek':
        script='import os\nROOT='+repr(remote)+'\n'
        script+='names=["play-1.stdout.raw","play-1.stderr.raw","play-2.stdout.raw","play-2.stderr.raw","play-3.stdout.raw","play-3.stderr.raw","candidate.stdout.raw","candidate.stderr.raw","worker.stderr.raw","guardian.stderr.raw"]\n'
        script+='print("RESULT="+repr({name:open(ROOT+"/"+name,"rb").read(8*1024*1024) for name in names if os.path.isfile(ROOT+"/"+name)}))\n'
        files=result_from(adb.python('peek',script))
        for name,content in files.items():
            (out/name).write_bytes(content)
            if name.startswith('play-') or name in ('worker.stderr.raw','guardian.stderr.raw'):print(name+'\n'+content.decode('utf-8','replace')[-1800:])
            elif name.startswith('candidate.'):
                print(name+'\n'+'\n'.join(line for line in content.decode('utf-8','replace').splitlines() if 'P011_AWAKE' in line or 'Bridge.qml' in line)[-3000:])
    elif a.action=='collect':
        status=result_from(command(adb,meta,'status',['status']))
        if not status['complete']: raise RuntimeError('Still running; collect after recovery completes')
        adb.run('pull',['pull',remote,str(out/'device')],timeout=45)
        safety=(NATIVE/'runtime/native_safety.py').read_text()
        final=result_from(adb.python('independent-stock',safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'))
        (out/'independent-stock.json').write_text(json.dumps(final,indent=2),encoding='utf-8')
        (out/'result.json').write_text(status['files']['result.json'],encoding='utf-8')
        print(status['files']['result.json'])
    else:
        args=['play','pause'] if a.action=='pause-test' else [a.action]
        answer=result_from(command(adb,meta,a.action,args))
        if a.action=='status':
            files=answer.pop('files')
            for name,text in files.items():(out/name).write_text(text,encoding='utf-8')
            answer['recent_events']=[json.loads(line) for line in files.get('events.jsonl','').splitlines()[-6:]]
        print(json.dumps(answer,ensure_ascii=False,indent=2))
    (out/'bundle.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    archive(out)


if __name__=='__main__':main()
