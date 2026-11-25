"""Exercise the real transaction's commit, rollback and drift refusal on PC."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
source=(HERE/'device_patch.py').read_text()


def run(fail=False,drift=False):
    with tempfile.TemporaryDirectory(prefix='p011-worker-patch-host-') as td:
        area=Path(td)
        release=area/'release'
        formal=area/'formal'
        release.mkdir();formal.mkdir()
        rid='a'*24;rev='b'*64
        stage=formal/'playback-patches'/rev[:24]
        stage.mkdir(parents=True)
        names=['media/bin/bili-hw','media/manifest.json','app/config.py',
               'app/native-build-result.json','source-manifest.json','manifest.json','build-result.json']
        before={};after={}
        for name in names:
            for root,raw in ((release,('old:'+name).encode()),(stage,('new:'+name).encode())):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            before[name]={'sha256':hashlib.sha256((release/name).read_bytes()).hexdigest()}
            after[name]={'sha256':hashlib.sha256((stage/name).read_bytes()).hexdigest(),
                         'bytes':(stage/name).stat().st_size}
        manifest={n:dict(after[n]) for n in names if n not in ('manifest.json','build-result.json')}
        (stage/'manifest.json').write_text(json.dumps(manifest))
        after['manifest.json']={'sha256':hashlib.sha256((stage/'manifest.json').read_bytes()).hexdigest(),
                               'bytes':(stage/'manifest.json').stat().st_size}
        backup_root=formal/'backups'/rid
        backup_root.mkdir(parents=True)
        receipt={'backup':str(backup_root)}
        receipt_path=formal/'install-receipt.json'
        receipt_path.write_text(json.dumps(receipt))
        receipt_before=receipt_path.read_bytes()
        live={'boot':'boot','mounts':{'options':['ro']},'startup':{'kind':'sysv'},
              'app':{'pid':1,'parent':2,'start':'3','exe':'Z03','args':['Z03'],'state':'S'},
              'launcher':{'pid':2,'parent':3,'start':'4','exe':'sh','args':['sh'],'state':'S'}}
        def require(value,why):
            if not value:raise RuntimeError(why)
        def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        def read(path,limit=1048576):return Path(path).read_bytes()
        fault=[fail]
        def atomic(path,raw,mode):
            if Path(path)==release/names[1] and raw==(stage/names[1]).read_bytes() and fault[0]:
                fault[0]=False;raise OSError('synthetic failed replacement')
            Path(path).write_bytes(raw);os.chmod(path,mode)
        def save(path,obj):Path(path).write_text(json.dumps(obj))
        def directory(path,create=False):
            if create:Path(path).mkdir(parents=True,exist_ok=True)
            require(Path(path).is_dir(),'directory')
        lock=area/'lock'
        env=dict(os=os,stat=__import__('stat'),json=json,BASE=str(release),FORMAL=str(formal),
                 PATCH={'release_id':rid,'revision_sha256':rev,'before':before,'after':after,'order':names},
                 require=require,read=read,digest=digest,atomic=atomic,save=save,directory=directory,
                 regular=lambda p:None,transaction_lock=lambda:os.open(lock,os.O_CREAT|os.O_WRONLY,0o600))
        exec(compile(source,'device_patch.py','exec'),env)
        env['playback_gate']=lambda:(json.loads(receipt_path.read_text()),live,'runtime')
        def verify_old():
            for name,spec in before.items():require(digest(release/name)==spec['sha256'],'drift')
        env['verify_old_payload']=verify_old
        env['worker_selftest']=lambda *a:{'exit':0,'result':{'ok':True}}
        if drift:(release/names[0]).write_bytes(b'unknown drift')
        try:
            result=env['apply_playback_patch']()
            require(not fail and not drift,'failure was not refused')
            require(result['applied'],'commit missing')
            for name,spec in after.items():require(digest(release/name)==spec['sha256'],'commit mismatch')
            require(json.loads(receipt_path.read_text())['playback_patch']['revision']==rev,'revision missing')
        except (OSError,RuntimeError):
            require(fail or drift,'unexpected transaction failure')
            for name,spec in before.items():
                if drift and name==names[0]:continue
                require(digest(release/name)==spec['sha256'],'rollback mismatch')
            require(receipt_path.read_bytes()==receipt_before,'receipt rollback mismatch')
            if fail:
                result=json.loads((backup_root/('playback-fix-'+rev[:24])/'transaction.json').read_text())
                require(result['rolled_back'] and not result['applied'],'rollback not recorded')


for mode in ({},{'fail':True},{'drift':True}):run(**mode)
print('actual_patch_transactions=3 passed')
