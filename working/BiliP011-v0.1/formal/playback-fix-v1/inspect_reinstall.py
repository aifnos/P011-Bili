"""Read the restored installation and retained directory identities only."""
import datetime
import importlib.util
import json
from pathlib import Path
import re
import zipfile

HERE=Path(__file__).resolve().parent
FORMAL=HERE.parent
PKG=FORMAL/'out/P011-Bili-ADB-v7-playback-cache-final-20261014'
spec=importlib.util.spec_from_file_location('reader',PKG/'install_formal.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
out=HERE/('reinstall-readonly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
out.mkdir()
adb=reader.Adb(out)
rows=adb.run('devices',['devices','-l'])
targets=re.findall(r'^\S+\s+device\s+.*model:sprdisk .*transport_id:(\d+)',rows,re.M)
assert len(targets)==1
adb.transport=int(targets[0])
rid='9412e49de8feb2d6b2677180'
release='/mnt/data/p011-toolbox/bili-formal/releases/'+rid
helper=(PKG/'device_install.py').read_text(encoding='utf8').replace('from __future__ import print_function\n','',1).rsplit("if __name__ == '__main__':",1)[0]
code='__file__='+repr(release+'/device_install.py')+'\n'+helper+'\n'+r'''
rid='9412e49de8feb2d6b2677180'
release=FORMAL+'/releases/'+rid
runtime=AREA+'/bili-awake/'+rid
answer=dict(stock=inspect(),receipt_present=os.path.lexists(FORMAL+'/install-receipt.json'),
            release_present=os.path.lexists(release),runtime_present=os.path.lexists(runtime),
            startup_present=os.path.lexists(INIT),startup_link_present=os.path.lexists('/etc/rc5.d/S99p011-bili-formal'),
            release_files={},retained_receipts=[],runtime_types={},runtime_count=0)
for name in ('build-result.json','manifest.json','device_install.py','media/bin/bili-hw'):
    path=release+'/'+name
    if os.path.isfile(path):answer['release_files'][name]=dict(sha256=digest(path),bytes=os.path.getsize(path))
manifest=json.loads(read(release+'/manifest.json').decode('ascii'))
bad=[]
for name,row in manifest.items():
    if name=='Z03.patched':continue
    path=release+'/'+name
    if not os.path.isfile(path) or digest(path)!=row['sha256']:bad.append(name)
answer['payload_mismatches']=bad
for root,dirs,files in os.walk(runtime,followlinks=False):
    for name in dirs+files:
        info=os.lstat(root+'/'+name)
        kind='dir' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'other'
        answer['runtime_types'][kind]=answer['runtime_types'].get(kind,0)+1
        answer['runtime_count']+=1
for name in sorted(os.listdir(FORMAL+'/backups')):
    if not re.match('^'+rid+'-[0-9]{8}-[0-9]{6}$',name):continue
    base=FORMAL+'/backups/'+name
    path=base+'/restored-install-receipt.json'
    if os.path.isfile(path):
        item=json.loads(read(path).decode('ascii'))
        proof=dict(path=path,release_id=item.get('release_id'),original_matches=digest(base+'/Z03.original')==PINS[TARGET])
        if os.path.isfile(base+'/restore-result.json'):
            restored=json.loads(read(base+'/restore-result.json').decode('ascii'))
            proof['restored']=restored.get('restored');proof['root_mount_restored']=restored.get('root_mount_restored')
        answer['retained_receipts'].append(proof)
print('RESULT='+repr(answer),flush=True)
'''
answer=reader.result(adb.python('retained-after-restore',code,60))
(out/'result.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf8')
with zipfile.ZipFile(str(out)+'.private.zip','x',zipfile.ZIP_DEFLATED) as z:
    for p in out.iterdir():
        if p.is_file():z.write(p,p.name)
print(json.dumps(dict(logs=str(out),device=answer),ensure_ascii=False))
