"""Linux host fixtures: actual cache helper and installed-upgrade dispatcher."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

PKG=Path('/src/formal/out/P011-Bili-ADB-v7-playback-cache-final-20261014')
spec=importlib.util.spec_from_file_location('device',PKG/'device_install.py')
device=importlib.util.module_from_spec(spec);spec.loader.exec_module(device)
checks=0
with tempfile.TemporaryDirectory(dir='/output',prefix='cache-') as tmp:
    device.AREA=tmp
    root=Path(tmp)
    cache=root/'qmlcache/feedback.qmlc';cache.parent.mkdir()
    backup=root/'backups';backup.mkdir()
    other=cache.parent/'other.qmlc';other.write_bytes(b'preserve another page')
    device.FEEDBACK_CACHE=str(cache)
    good=b'qv4cdata'+b'qrc:/ZybQmlFiles/ZybSet/SetUserReport.qml'
    for phase in ('install','repair','restore','rollback'):
        cache.write_bytes(good)
        before=hashlib.sha256(good).hexdigest()
        result=device.invalidate_feedback_cache(str(backup),phase)
        assert result['removed'] and not cache.exists()
        assert Path(result['backup']).read_bytes()==good and result['sha256']==before
        assert other.read_bytes()==b'preserve another page'
        checks+=1
    assert device.invalidate_feedback_cache(str(backup),'install')['absent'];checks+=1
    for bad in (b'unknown-format',b'qv4cdatawrong-page'):
        cache.write_bytes(bad)
        try:device.invalidate_feedback_cache(str(backup),'install')
        except RuntimeError:pass
        else:raise AssertionError('bad cache must be refused')
        assert cache.read_bytes()==bad;checks+=1
    cache.unlink();os.symlink(other,cache)
    try:device.invalidate_feedback_cache(str(backup),'install')
    except RuntimeError:pass
    else:raise AssertionError('cache symlink must be refused')
    assert other.read_bytes()==b'preserve another page';checks+=1
tree=ast.parse((PKG/'device_install.py').read_text())
for name,phase in (('install','install'),('restore','restore')):
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    cache_calls=[n for n in calls if n.func.id=='invalidate_feedback_cache' and n.args[1].value==phase]
    restarts=[n for n in calls if n.func.id=='restart_ui']
    assert len(cache_calls)==1 and cache_calls[0].lineno<min(n.lineno for n in restarts)
    checks+=1
spec=importlib.util.spec_from_file_location('upgrade',PKG/'adb_playback_upgrade.py')
upgrade=importlib.util.module_from_spec(spec);spec.loader.exec_module(upgrade)
class FakeAdb:
    def __init__(self,need):self.need=need;self.calls=[]
    def python(self,name,code,*args):
        self.calls.append(name)
        if name=='playback-revision-preflight':return {'needs_patch':self.need}
        if name=='playback-prepare-stage':
            assert "'/." not in code and '/.\'' not in code
            return {'staging_ready':True}
        if name=='playback-upgrade':return {'applied':True}
        raise AssertionError(name)
    def run(self,name,args,**kwargs):self.calls.append(name)
for need in (False,True):
    fake=FakeAdb(need);report={}
    upgrade.upgrade_playback(fake,PKG,'PINNED_HELPERS',report,lambda x:x)
    assert (fake.calls.count('playback-upgrade')==1)==need
    assert fake.calls.count('push-playback-fix')==(7 if need else 0)
    assert 'playback_upgrade' in report;checks+=1
text=(PKG/'install_formal.py').read_text()
start=text.index('if args.action == \'install\' and before.get(\'installed\') is True:')
branch=text[start:text.index("        if args.action == 'inspect':",start)]
assert branch.index('upgrade_playback(adb,')<branch.index("adb.python('repair-cache'")
checks+=1
print(json.dumps({'passed':True,'checks':checks,'device_connected':False,
                  'scope':'cache filesystem fixtures, call ordering and upgrade dispatcher'}))
