"""Package the exact cold-start tested engine; no device access during packaging."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
ROOT = PACK.parents[4]
NAME = 'P011-Bili-NoADB-v6-handoff-20261014'
OLD = PACK / 'out/P011-Bili-NoADB-v5-open-20261014'
OUT = PACK / 'out' / NAME
USER = pathlib.Path('D:/文档/近代史/视频') / NAME
REPORT = ROOT / '04_Documents/P011-Bili模式交接修订与冷启动读取实测-20261014.md'
MODULES = ('engine.py', 'run.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    tests = json.loads((HERE / 'host-tests-result.json').read_bytes())
    assert tests['passed'] and tests['tests'] == 30 and tests['failures'] == tests['errors'] == 0
    device = json.loads((HERE / 'cold-read-v6-2/result.json').read_bytes())
    host = json.loads((HERE / 'cold2.host-result.json').read_bytes())
    wire = json.loads((HERE / 'wire-review.json').read_bytes())
    assert device['status'] == 'COLD_AUTOD_GPT_UBOOT_READ_VERIFIED'
    assert host['exit_code'] == 0 and not host['timeout'] and host['source_unchanged']
    assert wire['status'] == 'ALL_RAW_TX_RX_REVIEWED' and wire['write_erase_reset_requests'] == 0
    assert sha(HERE / 'engine.py') == tests['engine_sha256'] == device['source_sha256'] == wire['engine_sha256']
    assert device['transport']['host_handle_closed'] and not device['transport']['write_started']
    manifest = json.loads((OLD / 'package-manifest.json').read_bytes())
    for name, row in manifest['files'].items():
        assert sha(OLD / name) == row['sha256']
    assert not OUT.exists() and not USER.exists()
    shutil.copytree(OLD, OUT)
    for name in MODULES:
        shutil.copyfile(HERE / name, OUT / 'app' / name)
    shutil.copyfile(HERE / 'host-tests-result.json', OUT / 'evidence/mode-handoff-host-tests.json')
    shutil.copyfile(REPORT, OUT / 'evidence/模式交接修订与冷启动读取实测.md')
    public = dict(status=device['status'], engine_sha256=device['source_sha256'],
        gpt_sha256=device['gpt_sha256'], uboot_sha256=device['uboot_sha256'],
        host_exit=0, initial_mode_requests=1, initial_crc_sync_requests=1, serial_closed=True,
        system_write_tested=False, system_boot_tested=False,
        user_reported_factory_boot_after_read_only_test=True, wire_review=wire)
    (OUT / 'evidence/cold-start-readonly-device-result.json').write_text(json.dumps(public,indent=2),encoding='utf-8')
    readme = (OUT / '使用说明.md').read_text(encoding='utf-8')
    readme = readme.replace('v5 串口打开修订', 'v6 模式交接修订')
    # Replace accumulated current-version paragraphs; their reports remain as history.
    readme = readme.split('\n本版修订串口打开流程')[0].rstrip()
    readme += '\n\nv6实测：已在P011上完成关机插线、内置AutoD初始化、32 KiB GPT及1 MiB uboot读取，SHA-256与固定基线相同；MODE和初始SYNC各一次，未写分区，句柄关闭，用户确认随后正常进入原厂主界面。正式包使用同一份实测engine。system安装、修改镜像开机、B站功能、退出和恢复仍待验收。\n\nMODE后先保留旧句柄做限时被动读取，记录回显或旧句柄失效，然后重新打开同设备。支持同一PnP节点被沿用，实际AutoD版本和ACK仍必须严格匹配；不会因PnP稳定就直接读写分区。MODE失败不重发；SYNC、握手及分区传输失败不自动重试。新流程通过30项HOST检查。\n'
    (OUT / '使用说明.md').write_text(readme, encoding='utf-8')
    replacements = {'installer/' + name: name for name in MODULES}
    with zipfile.ZipFile(OLD / 'source/project-sources.zip') as source, zipfile.ZipFile(OUT / 'source/project-sources.zip', 'w', zipfile.ZIP_DEFLATED) as dest:
        for item in source.infolist():
            name = 'installer/history/v5-' + replacements[item.filename] if item.filename in replacements else item.filename
            dest.writestr(name, source.read(item))
        for name in (*MODULES, 'test_mode_handoff.py', 'deliver.py'):
            dest.write(HERE / name, 'installer/' + ('deliver_mode_handoff.py' if name == 'deliver.py' else name))
    manifest.update(name=NAME, mode_handoff_device_tested=True, cold_autod_gpt_uboot_read_device_tested=True,
                    mode_same_pnp_path_host_tested=True, mode_same_pnp_path_device_tested=False,
                    initial_ready_device_tested=True, host_mode_handoff_tests=30, system_write_device_tested=False)
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
    before = HERE / 'root-entries-before-v6'
    before.mkdir()
    for local, target in [('一键正式写入B站.cmd','一键正式写入B站.cmd'), ('一键恢复用户反馈.cmd','一键恢复原系统.cmd'),
                         ('校验免ADB刷写包.cmd','校验刷写包.cmd'), ('一键安装P011下载驱动.cmd','一键安装下载驱动.cmd')]:
        shutil.copy2(ROOT / local, before / local)
        (ROOT / local).write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + str((OUT / target).relative_to(ROOT)) + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))
    result = dict(status='COLD_START_READ_VERIFIED_SYSTEM_WRITE_PENDING', package=str(archive),
        zip_sha256=sha(archive), zip_bytes=archive.stat().st_size, user_folder=str(USER),
        host_tests=tests['tests'], user_path_check_exit=check.returncode,
        zip_crc_and_all_member_sha_passed=True, device_operations_during_packaging=False,
        cold_start_read_verified=True, system_write_verified=False,
        system_candidate_sha256_unchanged=manifest['candidate_sha256'],
        driver_and_runtime_unchanged=True, original_failure_preserved=True,
        original_user_failure_sha256=sha(HERE / 'user-failed-install-v5-original.zip'))
    (HERE / 'delivery-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    latest = '> v6模式交接修订及冷启动实测（2026-10-14）：用户v5已恢复一次CreateFileW433并发送MODE，但强制观察重枚举超时；未发SYNC或分区命令。v6保留MODE后旧句柄被动读取窗口，处理限定阶段的旧句柄失效，允许同节点沿用，仍以精确协议应答确认AutoD。30项HOST通过；实机冷启动初始化、GPT32KiB和uboot1MiB读取通过、基线SHA一致、277次TX/276帧RX离线复核、MODE及初始SYNC各1、无分区写入、HOST0/句柄关闭，用户确认原厂开机。正式包engine与本轮实测完全相同；system写入/修改镜像启动/B站/恢复和干净电脑仍待。新包 `packages/' + NAME + '.zip`，SHA256 `' + result['zip_sha256'] + '`；用户原目录旁已有v6，根入口已切换。详见 `04_Documents/P011-Bili模式交接修订与冷启动读取实测-20261014.md`；以下为历史。\n\n'
    for path in [ROOT / '01_Environment/00-项目交接与当前状态.md', ROOT / '01_Environment/02-工具版本与验证边界.md',
                 PACK.parents[1] / 'NO_ADB_DISTRIBUTION.md', PACK.parents[1] / 'NO_ADB_NEXT_GATE.md', PACK.parent / 'README.md']:
        header, rest = path.read_text(encoding='utf-8-sig').split('\n', 1)
        path.write_text(header + '\n\n' + latest + rest.lstrip('\n'), encoding='utf-8')
    audit = ROOT / 'packages/P011-Bili-NoADB-v6-handoff-evidence-private-20261014.zip'
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
