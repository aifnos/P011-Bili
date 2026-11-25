"""Versioned v8 ADB package: preserve verified restored directories."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
FORMAL=HERE.parent
OLD=FORMAL/'out/P011-Bili-ADB-v7-playback-cache-final-20261014'
NEW=FORMAL/'out/P011-Bili-ADB-v8-reinstall-cache-20261014'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(body,old,new):
    assert body.count(old)==1,old
    return body.replace(old,new,1)


def main():
    assert not NEW.exists()
    spec=importlib.util.spec_from_file_location('oldhost',OLD/'install_formal.py')
    host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
    host.verify_package(OLD)
    body=(OLD/'device_install.py').read_text(encoding='utf8')
    pins='\nREINSTALL_JSON_SHA='+repr(sha(OLD/'app/stdlib-json35.zip'))+'\n'
    legacy=FORMAL/'out/P011-Bili-Formal-v5-adb-directory-20261014'
    pins+='REINSTALL_LEGACY_MANIFEST_SHA='+repr(sha(legacy/'manifest.json'))+'\n'
    pins+='REINSTALL_LEGACY_HELPERS='+repr(tuple(sorted({sha(legacy/'device_install.py'),sha(OLD/'device_install.py')})))+'\n'
    block=pins+(HERE/'retained_reinstall.py').read_text(encoding='utf8')
    body=replace_once(body,'\ndef install():','\n'+block+'\n\ndef install():')
    body=replace_once(body,"    require(not os.path.lexists(release) and not os.path.lexists(runtime), 'release/runtime already exists; inspect partial install')",
                      '    retained=retained_layout(meta)')
    body=replace_once(body,"    save(backup + '/before.json', before)\n    directory(release, True)",
                      "    save(backup + '/before.json', before)\n    retained_archive=archive_retained_layout(meta,retained,backup)\n    directory(release, True)")
    body=replace_once(body,'                  installed=False, physical_acceptance=False, settings_navigation_verified=False)',
                      '                  installed=False, physical_acceptance=False, settings_navigation_verified=False,\n                  retained_archive=retained_archive)')
    ast.parse(body,feature_version=(3,5))
    text=(OLD/'install_formal.py').read_text(encoding='utf8')
    old="            gate += 'else:\\n print(\"RESULT=\"+repr(inspect()))\\n'"
    new="""            gate += 'else:\\n state=inspect()\\n'
            gate += ' state["retained_reinstall"]=retained_layout(' + repr(meta) + ',' + repr(sha(package/'device_install.py')) + ')\\n'
            gate += ' print("RESULT="+repr(state))\\n'"""
    text=replace_once(text,old,new)
    compile(text,'install_formal.py','exec')
    shutil.copytree(OLD,NEW)
    for name in ('device_install.py','source/runtime/device_install.py'):(NEW/name).write_text(body,encoding='utf8')
    for name in ('install_formal.py','source/host/install_formal.py'):(NEW/name).write_text(text,encoding='utf8')
    for name in ('retained_reinstall.py','build_adb_reinstall.py','test_reinstall.py'):
        shutil.copyfile(HERE/name,NEW/'source/playback-fix-v1'/name)
    prefix='''# P011 B站 ADB 包 v8：恢复后可再次一键安装

修正“恢复用户反馈”后保留 release/runtime，随后重新安装被旧目录阻挡的问题。
重新安装前必须确认原厂文件、原备份、成功恢复记录、保留应用完整清单和目录属主均匹配。
程序先把旧应用与运行资料移到本设备 bili-formal/retained 下的独立归档，再安装新副本。
不删除旧目录、账号或历史；无成功恢复记录、清单漂移、符号链接等情况停止并保留原件。
首次安装、已有安装的播放修复及安装后的反馈页 Qt 编译缓存备份清理继续保留。

以下为上一版功能说明，v8整包验证边界以交付记录为准：

'''
    (NEW/'README.md').write_text(prefix+(OLD/'README.md').read_text(encoding='utf8'),encoding='utf8')
    listed=NEW/'PACKAGE.sha256'
    listed.write_text(''.join(sha(p)+' '+str(p.stat().st_size)+' '+p.relative_to(NEW).as_posix()+'\n'
        for p in sorted(NEW.rglob('*')) if p.is_file() and p!=listed),encoding='utf8')
    host.verify_package(NEW)
    print(json.dumps({'package':str(NEW),'payload_worker_unchanged':sha(NEW/'media/bin/bili-hw')==sha(OLD/'media/bin/bili-hw')}))


if __name__=='__main__':main()
