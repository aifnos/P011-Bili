"""Offline immutable v5 package; check mode only, never opens a real device."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
ROOT = PACK.parents[4]
NAME = 'P011-Bili-NoADB-v5-open-20261014'
OLD = PACK / 'out/P011-Bili-NoADB-v4-ready-20261014'
OUT = PACK / 'out' / NAME
USER = pathlib.Path('D:/文档/近代史/视频') / NAME
REPORT = ROOT / '04_Documents/P011-Bili串口打开生命周期修订-20261014.md'
MODULES = ('engine.py', 'win32_download_transport.py', 'flash.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    tests = json.loads((HERE / 'host-tests-result.json').read_bytes())
    assert tests['passed'] and tests['tests'] == 48 and tests['failures'] == tests['errors'] == 0
    for name, digest in tests['files'].items():
        assert sha(HERE / name) == digest
    manifest = json.loads((OLD / 'package-manifest.json').read_bytes())
    for name, row in manifest['files'].items():
        assert sha(OLD / name) == row['sha256']
    assert not OUT.exists() and not USER.exists()
    shutil.copytree(OLD, OUT)
    for name in MODULES:
        shutil.copyfile(HERE / name, OUT / 'app' / name)
    shutil.copyfile(HERE / 'host-tests-result.json', OUT / 'evidence/open-lifecycle-host-tests.json')
    shutil.copyfile(REPORT, OUT / 'evidence/串口打开生命周期修订.md')
    readme = (OUT / '使用说明.md').read_text(encoding='utf-8')
    readme = readme.replace('v4 首次接口就绪修订', 'v5 串口打开修订')
    # Replace accumulated current-version paragraphs; their reports remain as history.
    readme = readme.split('\n本版修正 MODE 后固定等待')[0].rstrip()
    readme += '\n\n本版修订串口打开流程：首次下载节点出现后，就绪观察和打开共用3秒期限；MODE后先确认同设备重新枚举，观察和打开共用30秒期限。遇到已识别的短暂消失错误，会在确认失败句柄关闭后重新识别同一设备。MODE发送一经尝试不重发，SYNC及存储传输失败也不自动重试。日志增加失败API、WinError和异常调用栈。48项电脑端模拟检查通过；真实433恢复和system实机验收仍待。\n'
    (OUT / '使用说明.md').write_text(readme, encoding='utf-8')
    replacements = {'installer/' + name: name for name in MODULES}
    with zipfile.ZipFile(OLD / 'source/project-sources.zip') as source, zipfile.ZipFile(OUT / 'source/project-sources.zip', 'w', zipfile.ZIP_DEFLATED) as dest:
        for item in source.infolist():
            name = 'installer/history/v4-' + replacements[item.filename] if item.filename in replacements else item.filename
            dest.writestr(name, source.read(item))
        for name in (*MODULES, 'test_open_lifecycle.py', 'deliver.py'):
            dest.write(HERE / name, 'installer/' + ('deliver_open_lifecycle.py' if name == 'deliver.py' else name))
        dest.write(PACK.parent / 'test_win32_transport.py', 'installer/test_win32_transport.py')
    manifest.update(name=NAME, port_open_lifecycle_recovery=True,
                    port_open_recovery_device_tested=False, host_open_lifecycle_tests=48)
    manifest['files'] = {p.relative_to(OUT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'package-manifest.json'}
    assert not any(part in ('logs', 'backups', '__pycache__') for name in manifest['files'] for part in pathlib.PurePosixPath(name).parts)
    for name in manifest['files']:
        if name.startswith(('data/', 'drivers/', 'runtime/')):
            assert manifest['files'][name] == json.loads((OLD / 'package-manifest.json').read_bytes())['files'][name]
    (OUT / 'package-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(OUT, USER)
    check = subprocess.run([str(USER / 'runtime/python.exe'), '-B', '-X', 'utf8', str(USER / 'app/run.py'), 'check'], capture_output=True, timeout=60)
    (HERE / 'user-path-check.stdout.raw').write_bytes(check.stdout)
    (HERE / 'user-path-check.stderr.raw').write_bytes(check.stderr)
    (HERE / 'user-path-check.exit.txt').write_text(str(check.returncode))
    assert check.returncode == 0 and not check.stderr
    for source in (OUT / 'source').glob('*.zip'):
        with zipfile.ZipFile(source) as bundle:
            assert bundle.testzip() is None
    archive = ROOT / 'packages' / (NAME + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(OUT.rglob('*')):
            if path.is_file():
                bundle.write(path, NAME + '/' + path.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, item in manifest['files'].items():
            data = bundle.read(NAME + '/' + name)
            assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256']
        assert bundle.read(NAME + '/package-manifest.json') == (OUT / 'package-manifest.json').read_bytes()
    before = HERE / 'root-entries-before-v5'
    before.mkdir()
    for local, target in [('一键正式写入B站.cmd','一键正式写入B站.cmd'), ('一键恢复用户反馈.cmd','一键恢复原系统.cmd'),
                         ('校验免ADB刷写包.cmd','校验刷写包.cmd'), ('一键安装P011下载驱动.cmd','一键安装下载驱动.cmd')]:
        shutil.copy2(ROOT / local, before / local)
        (ROOT / local).write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + str((OUT / target).relative_to(ROOT)) + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))
    result = dict(status='OPEN_LIFECYCLE_HOST_FIX_PACKAGED_DEVICE_PENDING', package=str(archive),
        zip_sha256=sha(archive), zip_bytes=archive.stat().st_size, user_folder=str(USER),
        host_tests=tests['tests'], user_path_check_exit=check.returncode,
        zip_crc_and_all_member_sha_passed=True, device_operations=False,
        system_candidate_sha256_unchanged=manifest['candidate_sha256'],
        driver_and_runtime_unchanged=True, original_failure_preserved=True,
        original_user_failure_sha256=sha(HERE / 'user-failed-install-v4-original.zip'))
    (HERE / 'delivery-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    latest = '> v5串口打开修订（2026-10-14）：用户v4首次节点已就绪，但打开/初始化报告WinError433；MODE/SYNC/写入均0，原wire TX/RX为0字节，旧日志不足以定位具体API。本版在已确认失败句柄关闭、同设备身份及协议未尝试条件下限时重新识别打开；禁止重发MODE、SYNC和分区命令，新增API/错误码/关闭结果/调用栈证据。48项HOST检查、用户中文路径校验和ZIP全成员核验通过。新包 `packages/' + NAME + '.zip`，SHA256 `' + result['zip_sha256'] + '`，原用户目录旁已有v5，根入口已切换。真实433恢复、system及干净电脑验收仍待；本轮无设备命令或驱动安装。详见 `04_Documents/P011-Bili串口打开生命周期修订-20261014.md`；以下为历史。\n\n'
    for path in [ROOT / '01_Environment/00-项目交接与当前状态.md', ROOT / '01_Environment/02-工具版本与验证边界.md',
                 PACK.parents[1] / 'NO_ADB_DISTRIBUTION.md', PACK.parents[1] / 'NO_ADB_NEXT_GATE.md', PACK.parent / 'README.md']:
        header, rest = path.read_text(encoding='utf-8-sig').split('\n', 1)
        path.write_text(header + '\n\n' + latest + rest.lstrip('\n'), encoding='utf-8')
    audit = ROOT / 'packages/P011-Bili-NoADB-v5-open-evidence-private-20261014.zip'
    paths = [p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts] + [REPORT]
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    with zipfile.ZipFile(audit, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(ROOT).as_posix())
        bundle.writestr('sha256.json', json.dumps(hashes, indent=2))
    with zipfile.ZipFile(audit) as bundle:
        assert bundle.testzip() is None
        for name, value in hashes.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == value
    print(json.dumps(dict(result, evidence_zip=str(audit), evidence_sha256=sha(audit)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
