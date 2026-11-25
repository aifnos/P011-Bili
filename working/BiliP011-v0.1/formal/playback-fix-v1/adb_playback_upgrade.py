"""Integrate the exact worker revision before existing-install cache repair."""
import json
from pathlib import Path


def upgrade_playback(adb, package, installed_code, report, decode):
    patch=json.loads((package/'playback-patch.json').read_bytes())
    release='/mnt/data/p011-toolbox/bili-formal/releases/'+patch['release_id']
    code=installed_code+'\nPATCH='+repr(patch)+'\n'+(package/'device_playback_patch.py').read_text(encoding='utf8')
    code+='''
def installed_worker_revision():
    receipt, live, runtime = playback_gate()
    worker = digest(BASE+'/media/bin/bili-hw')
    old = PATCH['before']['media/bin/bili-hw']['sha256']
    fixed = PATCH['after']['media/bin/bili-hw']['sha256']
    if worker == old:
        verify_old_payload()
        return dict(needs_patch=True)
    require(worker == fixed, 'unknown installed playback worker')
    for name, spec in PATCH['after'].items():
        regular(BASE+'/'+name)
        require(digest(BASE+'/'+name) == spec['sha256'], 'installed patch revision differs: '+name)
    manifest=json.loads(read(BASE+'/manifest.json').decode('ascii'))
    for name, spec in manifest.items():
        if name == 'Z03.patched': continue
        regular(BASE+'/'+name)
        require(digest(BASE+'/'+name) == spec['sha256'], 'installed payload drift: '+name)
    return dict(needs_patch=False, revision=PATCH['revision_sha256'])
'''
    state=decode(adb.python('playback-revision-preflight',code+'\nprint("RESULT="+repr(installed_worker_revision()),flush=True)\n',60))
    if state['needs_patch']:
        stage='/mnt/data/p011-toolbox/bili-formal/playback-patches/'+patch['revision_sha256'][:24]
        prepare=code+'\ndirectory(FORMAL+"/playback-patches",True)\ndirectory('+repr(stage)+',True)\n'
        parents=sorted({str(Path(name).parent).replace('\\','/') for name in patch['order']} - {'.'})
        prepare+='\n'.join('directory('+repr(stage+'/'+parent)+',True)' for parent in parents)+'\n'
        prepare+='print("RESULT="+repr(dict(staging_ready=True)),flush=True)\n'
        report['device_write_started']=True
        decode(adb.python('playback-prepare-stage',prepare))
        for name in patch['order']:
            adb.run('push-playback-fix',['push',str(package/name),stage+'/'+name],timeout=60)
        value=decode(adb.python('playback-upgrade',code+'\napply_playback_patch()\n',90))
        if value.get('applied') is not True:raise RuntimeError('Playback upgrade not completed')
        report['playback_upgrade']=value
    else:
        report['playback_upgrade']=dict(already_current=True,revision=patch['revision_sha256'])
    return report['playback_upgrade']
