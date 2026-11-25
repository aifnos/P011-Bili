"""Assemble exact hashes and metadata for a compatibility hotfix revision."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

HERE = Path(__file__).resolve().parent
FORMAL = HERE.parent
OLD = FORMAL/'out/P011-Bili-Formal-v5-adb-directory-20261014'
BUILD = HERE/'build-v2'
NEW = FORMAL/'out/P011-Bili-PlaybackFix-v4-20261014'
RID = '9412e49de8feb2d6b2677180'


def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(obj): return json.dumps(obj,sort_keys=True,separators=(',',':')).encode('ascii')


def main():
    assert not NEW.exists()
    build = json.loads((BUILD/'build-result.json').read_bytes())
    assert build['host_exit'] == build['gate_host_exit'] == 0
    worker = (BUILD/'bin/bili-hw').read_bytes()
    assert sha(worker) == build['artifacts']['bin/bili-hw']['sha256']
    old_worker = sha((OLD/'media/bin/bili-hw').read_bytes())
    revision = sha(canonical({'base_release':RID,'worker':sha(worker),
                              'transaction_source':sha((HERE/'device_patch.py').read_bytes()),
                              'sources':build['source_files']}))
    changes = {'media/bin/bili-hw':worker}
    config = (OLD/'app/config.py').read_bytes()
    assert config.count(old_worker.encode()) == 1
    changes['app/config.py'] = config.replace(old_worker.encode(),sha(worker).encode(),1)
    media = json.loads((OLD/'media/manifest.json').read_bytes())
    media['bin/bili-hw'].update(sha256=sha(worker),bytes=len(worker))
    changes['media/manifest.json'] = canonical(media)
    changes['app/native-build-result.json'] = canonical(build)
    source = json.loads((OLD/'source-manifest.json').read_bytes())
    source['playback-fix-v1/build-result.json'] = dict(sha256=sha(canonical(build)),bytes=len(canonical(build)))
    source['playback-fix-v1/source.diff'] = dict(sha256=sha((BUILD/'source.diff').read_bytes()),bytes=(BUILD/'source.diff').stat().st_size)
    changes['source-manifest.json'] = canonical(source)
    manifest = json.loads((OLD/'manifest.json').read_bytes())
    for name, raw in changes.items(): manifest[name] = dict(sha256=sha(raw), bytes=len(raw))
    changes['manifest.json'] = canonical(manifest)
    meta = json.loads((OLD/'build-result.json').read_bytes())
    meta.update(manifest_sha256=sha(changes['manifest.json']),
                compatible_release_id=RID, patch_revision_sha256=revision,
                patch_status='HOST_BUILT_DEVICE_PENDING',
                patch_reason='hardware bundle path gate omitted formal installation layouts')
    changes['build-result.json'] = canonical(meta)
    patch = dict(release_id=RID,revision_sha256=revision,patched_sha256=meta['patched_sha256'],
                 before={name:dict(sha256=sha((OLD/name).read_bytes()),bytes=(OLD/name).stat().st_size)
                         for name in changes},
                 after={name:dict(sha256=sha(raw),bytes=len(raw)) for name,raw in changes.items()},
                 order=list(changes))
    NEW.mkdir(parents=True)
    for name, raw in changes.items():
        target = NEW/'payload'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    (NEW/'patch.json').write_bytes(canonical(patch))
    (NEW/'legacy_reader.py').write_bytes((OLD/'install_formal.py').read_bytes())
    (NEW/'device_install_helpers.py').write_bytes((OLD/'device_install.py').read_bytes())
    for name in ('device_patch.py','run_patch.py'):
        shutil.copyfile(HERE/name,NEW/name)
    ast.parse((NEW/'device_patch.py').read_text(),feature_version=(3,5))
    (NEW/'source').mkdir()
    for p in HERE.rglob('*'):
        if p.is_file() and (p.is_relative_to(HERE/'native') or p.parent==HERE):
            target=NEW/'source'/p.relative_to(HERE)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
    for p in ('THIRD_PARTY_NOTICES.md','GPL-3.0.txt'):
        shutil.copyfile(OLD/'app'/p,NEW/p)
    (NEW/'一键修复视频播放.cmd').write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'
        'python -B "%~dp0run_patch.py" apply\r\nset "P011_EXIT=%ERRORLEVEL%"\r\n'
        'pause\r\nexit /b %P011_EXIT%\r\n').encode('utf8'))
    (NEW/'README.md').write_text('''# P011 B站视频播放修复 v1

此包是当前开发笔已安装 release 9412e49de8feb2d6b2677180 的专用 ADB 修复工具。
修复硬解进程只允许旧试验目录、导致正式路径错误41立即退出的问题。
退出 B站并保持 USB，双击“一键修复视频播放.cmd”；电脑需要现有 Python 和 adb。
先核对完整安装、设备原备份和原厂进程，再备份并原子更新硬解程序及六份关联校验文件。
保留页面兼容 release ID，并以独立 patch_revision_sha256 标识本次代码修订。
不重刷 system、不改用户反馈名字、不重启原厂界面、不删除账号或历史。
失败按精确哈希恢复本轮文件。原件及事务记录保存在本设备原安装备份下。
日志为本机私有证据，不应随分发包发送。修复自检通过仍需用户实际播放验收。
此开发修复使用 ADB；免ADB分发刷写包需要另外同步镜像，旧包未自动更新。
''',encoding='utf8')
    listed={p.relative_to(NEW).as_posix():dict(sha256=sha(p.read_bytes()),bytes=p.stat().st_size)
            for p in NEW.rglob('*') if p.is_file()}
    (NEW/'PACKAGE.json').write_bytes(canonical(listed))
    archive=Path(str(NEW)+'.private.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in NEW.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(NEW).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for p in NEW.rglob('*'):
            if p.is_file(): assert z.read(p.relative_to(NEW).as_posix())==p.read_bytes()
    (HERE/'patch-build-result.json').write_text(json.dumps(dict(package=str(NEW),revision=revision,
        archive=str(archive),sha256=sha(archive.read_bytes()),changed_files=list(changes)),indent=2))
    print(json.dumps({'package':str(NEW),'revision':revision,'archive':str(archive)}))


if __name__=='__main__':main()
