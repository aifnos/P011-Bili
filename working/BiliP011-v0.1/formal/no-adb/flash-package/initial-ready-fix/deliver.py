"""Offline v4 package, user-path copy and immutable host/failure evidence."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
ROOT = PACK.parents[4]
NAME = 'P011-Bili-NoADB-v4-ready-20261014'
OLD = PACK / 'out/P011-Bili-NoADB-v3-reenum-20261014'
OUT = PACK / 'out' / NAME
USER = pathlib.Path('D:/文档/近代史/视频') / NAME
REPORT = ROOT / '04_Documents/P011-Bili首次接口就绪等待修订-20261014.md'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((OLD / 'package-manifest.json').read_bytes())
    for name, row in manifest['files'].items():
        assert sha(OLD / name) == row['sha256']
    shutil.copytree(OLD, OUT)
    shutil.copyfile(HERE / 'engine.py', OUT / 'app/engine.py')
    shutil.copyfile(HERE / 'host-tests-result.json', OUT / 'evidence/initial-ready-host-tests.json')
    shutil.copyfile(REPORT, OUT / 'evidence/首次接口就绪修订.md')
    readme = (OUT / '使用说明.md').read_text(encoding='utf-8')
    readme = readme.replace('v3 重枚举修订', 'v4 首次接口就绪修订')
    readme += '\n本版补齐首次插入时的节点启动等待：只观察同一设备，最长3秒，就绪立即打开；持续失败会给出 started、problem 和 COM 实际字段。等待期间不发送模式或分区命令。MODE 后的同设备重枚举等待继续保留。8项新HOST检查和1项受影响完整模拟连接通过，仍待实机验证。\n'
    (OUT / '使用说明.md').write_text(readme, encoding='utf-8')
    with zipfile.ZipFile(OLD / 'source/project-sources.zip') as source, zipfile.ZipFile(OUT / 'source/project-sources.zip', 'w', zipfile.ZIP_DEFLATED) as dest:
        for item in source.infolist():
            name = 'installer/history/v3-engine.py' if item.filename == 'installer/engine.py' else item.filename
            dest.writestr(name, source.read(item))
        for path, name in [(HERE / 'engine.py', 'engine.py'), (HERE / 'test_initial_ready.py', 'test_initial_ready.py'),
                           (pathlib.Path(__file__), 'deliver_initial_ready.py')]:
            dest.write(path, 'installer/' + name)
    manifest.update(name=NAME, initial_interface_ready_wait=True, initial_ready_device_tested=False)
    manifest['files'] = {p.relative_to(OUT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'package-manifest.json'}
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
    old_entries = HERE / 'root-entries-before-v4'
    old_entries.mkdir()
    for local, target in [('一键正式写入B站.cmd','一键正式写入B站.cmd'), ('一键恢复用户反馈.cmd','一键恢复原系统.cmd'),
                         ('校验免ADB刷写包.cmd','校验刷写包.cmd'), ('一键安装P011下载驱动.cmd','一键安装下载驱动.cmd')]:
        shutil.copy2(ROOT / local, old_entries / local)
        (ROOT / local).write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + str((OUT / target).relative_to(ROOT)) + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))
    result = dict(status='INITIAL_READY_HOST_FIX_PACKAGED_DEVICE_PENDING', package=str(archive),
        zip_sha256=sha(archive), zip_bytes=archive.stat().st_size, user_folder=str(USER),
        new_initial_host_checks=8, affected_full_connect_check=1, user_path_check_exit=check.returncode,
        zip_crc_and_all_member_sha_passed=True, device_operations=False,
        system_candidate_sha256_unchanged=manifest['candidate_sha256'],
        original_user_failure_sha256=sha(HERE / 'user-failed-install-v3-original.zip'))
    (HERE / 'delivery-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    latest = '> v4首次就绪修订（2026-10-14）：用户v3停止于首次节点未就绪，open/MODE/SYNC/写入均0，原wire TX/RX为0字节；驱动包已注册，原日志未保存具体未就绪字段。补齐同实例首次启动/COM分配的3秒限时观察，持续异常报告实际状态，保留v3模式后重枚举和存储断连拒绝。8项新HOST＋1项受影响完整模拟连接、用户中文路径校验和ZIP成员校验通过。新包 `packages/' + NAME + '.zip`，SHA256 `' + result['zip_sha256'] + '`，原用户目录旁已有v4、根入口已切换。system设备验收仍待，本轮无驱动安装或设备命令。详见 `04_Documents/P011-Bili首次接口就绪等待修订-20261014.md`；以下为历史。\n\n'
    for path in [ROOT / '01_Environment/00-项目交接与当前状态.md', ROOT / '01_Environment/02-工具版本与验证边界.md',
                 PACK.parents[1] / 'NO_ADB_DISTRIBUTION.md', PACK.parents[1] / 'NO_ADB_NEXT_GATE.md', PACK.parent / 'README.md']:
        header, rest = path.read_text(encoding='utf-8-sig').split('\n', 1)
        path.write_text(header + '\n\n' + latest + rest.lstrip('\n'), encoding='utf-8')
    audit = ROOT / 'packages/P011-Bili-NoADB-v4-ready-evidence-private-20261014.zip'
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
