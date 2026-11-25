"""Make a full, cache-aware ADB package with the hardware-tested worker fix."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

HERE=Path(__file__).resolve().parent
FORMAL=HERE.parent
OLD=FORMAL/'out/P011-Bili-Formal-v6-adb-cache-20261014'
FIX=FORMAL/'out/P011-Bili-PlaybackFix-v4-20261014'
NEW=FORMAL/'out/P011-Bili-ADB-v7-playback-cache-final-20261014'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not NEW.exists()
    spec=importlib.util.spec_from_file_location('cache_installer',OLD/'install_formal.py')
    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
    host.verify_package(OLD)
    patch=json.loads((FIX/'patch.json').read_bytes())
    shutil.copytree(OLD,NEW)
    for name in patch['order']:
        target=NEW/name
        assert sha(target)==patch['before'][name]['sha256']
        shutil.copyfile(FIX/'payload'/name,target)
        assert sha(target)==patch['after'][name]['sha256']
    for source,name in ((FIX/'patch.json','playback-patch.json'),
                        (FIX/'device_patch.py','device_playback_patch.py'),
                        (HERE/'adb_playback_upgrade.py','adb_playback_upgrade.py')):
        shutil.copyfile(source,NEW/name)
    text=(OLD/'install_formal.py').read_text(encoding='utf8')
    old="                print('已安装同版本，检查并修复反馈页缓存；不重复覆盖 Z03。', flush=True)"
    new="""                from adb_playback_upgrade import upgrade_playback
                upgrade_playback(adb, package, installed_code, report, result)
                print('播放组件已核对；备份并清除用户反馈页缓存，按需重启界面。', flush=True)"""
    assert text.count(old)==1
    text=text.replace(old,new,1)
    for name in ('install_formal.py','source/host/install_formal.py'):
        (NEW/name).write_text(text,encoding='utf8')
    manifest=json.loads((NEW/'manifest.json').read_bytes())
    (NEW/'SOURCE.sha256').write_text(''.join(row['sha256']+' '+str(row['bytes'])+' '+name+'\n'
        for name,row in sorted(manifest.items())),encoding='ascii')
    for p in (HERE/'native').rglob('*'):
        if p.is_file():
            target=NEW/'source/playback-fix-v1/native'/p.relative_to(HERE/'native')
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target)
    for name in ('build_fix.py','test_gate.py','build_patch.py','device_patch.py','run_patch.py',
                 'test_patch_transaction.py','adb_playback_upgrade.py','build_adb_package.py','test_adb_package.py'):
        target=NEW/'source/playback-fix-v1'/name
        shutil.copyfile(HERE/name,target)
    for name in ('build-result.json','source.diff','gate.stdout.raw','gate.stderr.raw'):
        target=NEW/'evidence/playback-fix'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(HERE/'build-v2'/name,target)
    (NEW/'README.md').write_text('''# P011 B站一键 ADB 安装包 v7：播放修复与自动清理反馈页缓存

入口仍为“设置 → 用户反馈”，名称、图标和位置保持。

1. 退出 B站，保持 P011 USB 连接并启用 root ADB，电脑需要 Python 3 和 adb。
2. 双击“一键正式写入B站.cmd”。仅支持固定 v2.4.0 固件和已验证原厂身份。
3. 首次安装先备份原厂文件，安装 B站和独立服务；写入后备份并清除“用户反馈”页的 Qt 编译缓存，再正常重启界面加载新页面。
4. 已安装原正式版本时，先核对整份安装及原备份。旧硬解程序自动更新为已实机验证的修正版；已修复则跳过重复替换。随后自动备份、清除同一页编译缓存并按需重启界面。

修复了硬解程序只允许旧试验目录、在正式安装目录错误41退出的问题。当前开发笔已安装修复，用户确认普通视频、短视频画面及声音正常；本成套安装流程仍是电脑端装配验证，没有再次重装当前设备。

清理范围只包含 /home/.cache/Z03/qmlcache/022ca1fb51bc58aef40fcc9f5c484acedc84422e.qmlc。
清理前核对 qv4cdata 头和 SetUserReport.qml 来源，保存本设备原件及 SHA-256。不会删除账号、历史、视频缓存或其他页面缓存。
首次安装、已有安装修复、恢复原反馈页及失败回滚均包含目标编译缓存处理。缓存不存在时跳过清理，不额外重启界面。

此包使用 ADB，是用户本轮指定的 ADB 安装工具。免ADB下载模式分发包没有在本轮同步。
每次操作在包的相邻目录生成日志、独立 host/remote 状态和结果 ZIP。设备原件、账号、日志与备份不要外发。
“一键恢复用户反馈.cmd”恢复原反馈页与独立启动项，不是整机救砖。正常播放、部分切流和完整长时运行是不同验收范围。
''',encoding='utf8')
    for p in NEW.rglob('*.py'):
        if p.name in ('device_install.py','device_playback_patch.py'):
            ast.parse(p.read_text(encoding='utf-8-sig'),feature_version=(3,5))
        else:compile(p.read_bytes(),str(p),'exec')
    package_manifest=NEW/'PACKAGE.sha256'
    package_manifest.write_text(''.join(sha(p)+' '+str(p.stat().st_size)+' '+p.relative_to(NEW).as_posix()+'\n'
        for p in sorted(NEW.rglob('*')) if p.is_file() and p!=package_manifest),encoding='utf8')
    host.verify_package(NEW)
    print(json.dumps({'package':str(NEW),'worker':sha(NEW/'media/bin/bili-hw'),
                      'revision':patch['revision_sha256'],'status':'HOST_ASSEMBLED_PENDING_PACKAGE_CHECKS'}))


if __name__=='__main__':main()
