"""Actual retained-reinstall code on isolated Linux filesystem fixtures."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

PKG=Path('/src/formal/out/P011-Bili-ADB-v8-reinstall-cache-20261014')
spec=importlib.util.spec_from_file_location('installer',PKG/'device_install.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks=0


def case(mode):
    global checks
    with tempfile.TemporaryDirectory(dir='/output',prefix='reinstall-') as td:
        area=Path(td);formal=area/'formal';formal.mkdir()
        m.AREA=str(area);m.FORMAL=str(formal);m.BASE=str(PKG)
        rid='a'*24
        release=formal/'releases'/rid;release.mkdir(parents=True)
        runtime=area/'bili-awake'/rid;runtime.mkdir(parents=True)
        personal=runtime/'private-runtime-state';personal.write_bytes(b'preserved runtime bytes')
        (release/'app').mkdir();(release/'media/bin').mkdir(parents=True)
        for name in ('app/stdlib-json35.zip','device_install.py'):
            (release/name).write_bytes((PKG/name).read_bytes())
        worker=release/'media/bin/bili-hw';worker.write_bytes(b'known immutable worker')
        def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
        manifest={name:{'sha256':sha(release/name),'bytes':(release/name).stat().st_size}
                  for name in ('app/stdlib-json35.zip','media/bin/bili-hw')}
        manifest['Z03.patched']={'sha256':'patched','bytes':123}
        (release/'manifest.json').write_text(json.dumps(manifest))
        meta={'release_id':rid,'patched_sha256':'patched','manifest_sha256':sha(release/'manifest.json')}
        (release/'build-result.json').write_text(json.dumps(meta))
        oldbackup=formal/'backups'/(rid+'-20261014-231059');oldbackup.mkdir(parents=True)
        original=oldbackup/'Z03.original';original.write_bytes(b'original stock')
        m.PINS[m.TARGET]=sha(original)
        receipt={'release_id':rid,'release':str(release),'runtime':str(runtime),'patched_sha256':'patched'}
        (oldbackup/'restored-install-receipt.json').write_text(json.dumps(receipt))
        (oldbackup/'restore-result.json').write_text(json.dumps({'restored':True,'root_mount_restored':True}))
        newbackup=formal/'backups'/(rid+'-20261014-234500');newbackup.mkdir()
        if mode=='absent':
            os.rename(release,area/'outside-release');os.rename(runtime,area/'outside-runtime')
            assert m.retained_layout(meta)=={'present':False};checks+=1;return
        if mode=='drift':worker.write_bytes(b'unknown modified worker')
        if mode=='symlink':os.symlink(personal,runtime/'link')
        if mode=='missing-proof':(oldbackup/'restored-install-receipt.json').unlink()
        if mode=='active':(formal/'install-receipt.json').write_text('{}')
        if mode=='restore-failed':(oldbackup/'restore-result.json').write_text('{"restored":false}')
        if mode=='half':os.rename(runtime,area/'runtime-outside')
        if mode in ('drift','symlink','missing-proof','active','restore-failed','half'):
            try:m.retained_layout(meta)
            except RuntimeError:pass
            else:raise AssertionError('unsafe state accepted: '+mode)
            assert release.exists() and worker.exists();checks+=1;return
        expected=m.retained_layout(meta)
        if mode=='rename-failure':
            original_rename=os.rename
            def fail_second(src,dst):
                if str(src)==str(runtime):raise OSError('synthetic second-directory failure')
                return original_rename(src,dst)
            with patch.object(m.os,'rename',fail_second):
                try:m.archive_retained_layout(meta,expected,str(newbackup))
                except OSError:pass
                else:raise AssertionError('move failure ignored')
            assert release.exists() and runtime.exists() and personal.read_bytes()==b'preserved runtime bytes'
            assert not list((formal/'retained').glob('*/release'));checks+=1;return
        result=m.archive_retained_layout(meta,expected,str(newbackup))
        archive=Path(result['archive'])
        assert result['preserved'] and not release.exists() and not runtime.exists()
        assert (archive/'runtime/private-runtime-state').read_bytes()==b'preserved runtime bytes'
        assert (archive/'release/media/bin/bili-hw').read_bytes()==b'known immutable worker'
        assert original.read_bytes()==b'original stock'
        assert m.retained_layout(meta)=={'present':False};checks+=1


for mode in ('absent','normal','drift','symlink','missing-proof','active','restore-failed','half','rename-failure'):
    case(mode)
print(json.dumps({'passed':True,'checks':checks,'scope':'actual retained layout, preservation and move-failure rollback','device_connected':False}))
