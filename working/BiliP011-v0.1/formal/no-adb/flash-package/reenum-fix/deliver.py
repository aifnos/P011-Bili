"""Package the bounded reenumeration change and preserve the user's old run."""
import gzip
import hashlib
import json
import pathlib
import shutil
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
ROOT = PACK.parents[4]
NAME = 'P011-Bili-NoADB-v3-reenum-20261014'
OLD = PACK / 'out/P011-Bili-NoADB-v2-driver-final-20261014'
OUT = PACK / 'out' / NAME
USER = pathlib.Path('D:/文档/近代史/视频') / NAME
REPORT = ROOT / '04_Documents/P011-Bili下载接口重枚举修订-20261014.md'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((OLD / 'package-manifest.json').read_bytes())
    for name, item in manifest['files'].items():
        assert sha(OLD / name) == item['sha256']
    shutil.copytree(OLD, OUT)
    shutil.copyfile(HERE / 'engine.py', OUT / 'app/engine.py')
    shutil.copyfile(REPORT, OUT / 'evidence/重枚举修订说明.md')
    shutil.copyfile(HERE / 'host-tests-result.json', OUT / 'evidence/reenum-host-tests.json')
    readme = (OUT / '使用说明.md').read_text(encoding='utf-8')
    readme = readme.replace('# P011 B站下载模式刷写包（含驱动）', '# P011 B站下载模式刷写包（含驱动，v3 重枚举修订）')
    readme += '\n本版修正 MODE 后固定等待 0.5 秒即打开串口的问题。现在仅发送一次 MODE，关闭旧句柄后最多等待 30 秒，确认同一 USB 实例重新枚举并稳定后再握手。等待期间保持 USB 连接。已有驱动不重复安装；多设备、不同身份与存储期间断连仍立即停止。此初始化修订已过 8 项 HOST 检查，尚待实机验证。\n'
    (OUT / '使用说明.md').write_text(readme, encoding='utf-8')
    with zipfile.ZipFile(OLD / 'source/project-sources.zip') as prior, zipfile.ZipFile(OUT / 'source/project-sources.zip', 'w', zipfile.ZIP_DEFLATED) as current:
        for item in prior.infolist():
            name = 'installer/history/v2-engine.py' if item.filename == 'installer/engine.py' else item.filename
            current.writestr(name, prior.read(item))
        current.write(HERE / 'engine.py', 'installer/engine.py')
        current.write(HERE / 'test_reenum.py', 'installer/test_reenum.py')
        current.write(pathlib.Path(__file__), 'installer/deliver_reenum.py')
    manifest.update(name=NAME, reenumeration_fix=True, reenumeration_device_tested=False)
    manifest['files'] = {p.relative_to(OUT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
        for p in sorted(OUT.rglob('*')) if p.is_file() and p.name != 'package-manifest.json'}
    (OUT / 'package-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(OUT, USER)
    command = [str(USER / 'runtime/python.exe'), '-B', '-X', 'utf8', str(USER / 'app/run.py'), 'check']
    result = subprocess.run(command, capture_output=True, timeout=60)
    (HERE / 'actual-user-path-check.stdout.raw').write_bytes(result.stdout)
    (HERE / 'actual-user-path-check.stderr.raw').write_bytes(result.stderr)
    (HERE / 'actual-user-path-check.exit.txt').write_text(str(result.returncode))
    assert result.returncode == 0 and not result.stderr
    for path in (OUT / 'source').glob('*.zip'):
        with zipfile.ZipFile(path) as bundle:
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
    old_entries = HERE / 'root-entries-before-v3'
    old_entries.mkdir()
    for local, target in [('一键正式写入B站.cmd','一键正式写入B站.cmd'), ('一键恢复用户反馈.cmd','一键恢复原系统.cmd'),
                          ('一键安装P011下载驱动.cmd','一键安装下载驱动.cmd'), ('校验免ADB刷写包.cmd','校验刷写包.cmd')]:
        shutil.copy2(ROOT / local, old_entries / local)
        relative = str((OUT / target).relative_to(ROOT))
        (ROOT / local).write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + relative + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))
    delivered = {'status': 'REENUMERATION_HOST_FIX_PACKAGED_DEVICE_PENDING', 'zip': str(archive),
        'zip_bytes': archive.stat().st_size, 'zip_sha256': sha(archive), 'user_folder': str(USER),
        'host_tests': 8, 'actual_user_path_check_exit': result.returncode, 'zip_crc_and_member_sha_passed': True,
        'device_operations_this_turn': False, 'source_failed_log_sha256': sha(HERE / 'user-failed-install-original.zip'),
        'candidate_system_sha256_unchanged': manifest['candidate_sha256']}
    (HERE / 'delivery-result.json').write_text(json.dumps(delivered, ensure_ascii=False, indent=2), encoding='utf-8')
    status = '> v3重枚举修订（2026-10-14）：用户v2原始TX只有一次MODE、RX只有回显，无实际SYNC/分区命令，原失败保留。修正MODE后固定0.5秒即重开句柄的时序缺口，改为单次MODE后限时观察同一设备重枚举并稳定；存储断连/多设备/身份变化仍拒绝。8项新HOST和用户中文路径纯校验通过。新包 `packages/' + NAME + '.zip`，SHA256 `' + delivered['zip_sha256'] + '`；原使用目录旁已有v3，根入口也已切换。设备初始化及system实机验收仍待，本轮未操作设备。详见 `04_Documents/P011-Bili下载接口重枚举修订-20261014.md`。以下为历史阶段。\n\n'
    for path in [ROOT / '01_Environment/00-项目交接与当前状态.md', ROOT / '01_Environment/02-工具版本与验证边界.md',
                 PACK.parents[1] / 'NO_ADB_DISTRIBUTION.md', PACK.parents[1] / 'NO_ADB_NEXT_GATE.md', PACK.parent / 'README.md']:
        old = path.read_text(encoding='utf-8-sig')
        head, rest = old.split('\n', 1)
        path.write_text(head + '\n\n' + status + rest.lstrip('\n'), encoding='utf-8')
    evidence = ROOT / 'packages/P011-Bili-NoADB-v3-reenum-evidence-private-20261014.zip'
    files = [p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts] + [REPORT]
    evidence_manifest = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    with zipfile.ZipFile(evidence, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(ROOT).as_posix())
        bundle.writestr('sha256.json', json.dumps(evidence_manifest, indent=2))
    with zipfile.ZipFile(evidence) as bundle:
        assert bundle.testzip() is None
        for name, expected in evidence_manifest.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == expected
    print(json.dumps(dict(delivered, evidence_zip=str(evidence), evidence_sha256=sha(evidence)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
