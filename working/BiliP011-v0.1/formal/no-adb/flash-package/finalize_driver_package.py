"""Verify new package, readonly native driver lookup, ZIP and root shortcuts."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]
NAME = 'P011-Bili-NoADB-v2-driver-final-20261014'
PACKAGE = HERE / 'out' / NAME
VALIDATION = HERE / 'driver-host-validation-20261014-corrected'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def capture(name, command, env=None):
    result = subprocess.run(command, cwd=str(VALIDATION), env=env, capture_output=True, timeout=60)
    (VALIDATION / (name + '.stdout.raw')).write_bytes(result.stdout)
    (VALIDATION / (name + '.stderr.raw')).write_bytes(result.stderr)
    (VALIDATION / (name + '.exit.txt')).write_text(str(result.returncode))
    assert result.returncode == 0 and not result.stderr, name + ': ' + result.stderr.decode('utf-8', errors='replace')


def main():
    VALIDATION.mkdir(exist_ok=False)
    manifest = json.loads((PACKAGE / 'package-manifest.json').read_bytes())
    for name, row in manifest['files'].items():
        assert (PACKAGE / name).stat().st_size == row['bytes'] and sha(PACKAGE / name) == row['sha256']
    moved = VALIDATION / '中文 含驱动/P011 B站'
    moved.mkdir(parents=True)
    for path in PACKAGE.rglob('*'):
        if path.is_file():
            target = moved / path.relative_to(PACKAGE)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target)
    python = str(moved / 'runtime/python.exe')
    env = dict(os.environ, PYTHONHOME='Z:\\P011_INVALID_PYTHON', PYTHONPATH='Z:\\P011_INVALID_PYTHON')
    capture('relocated-check', [python, '-B', '-X', 'utf8', '-u', str(moved / 'app/run.py'), 'check'], env)
    # A strict guard makes accidental UAC/driver installation impossible in this check.
    code = '''import json, pathlib
from unittest import mock
import driver_setup as d
d.check_host()
d.verify_driver_bundle()
found = d.registered_driver()
assert found, 'Expected current registered VCOM driver not found; stop without installing'
print(json.dumps(found, ensure_ascii=False))
with mock.patch.object(d, 'install_driver', side_effect=AssertionError('INSTALL_FORBIDDEN')), mock.patch.object(d, 'elevate_helper', side_effect=AssertionError('UAC_FORBIDDEN')):
    assert d.ensure_driver(pathlib.Path('readonly-existing-driver')) == 0
print('READONLY_EXISTING_DRIVER_PASS_NO_INSTALL_NO_USB')
'''
    capture('native-registered-driver', [python, '-B', '-X', 'utf8', '-c', code], env)
    for path in (PACKAGE / 'source').glob('*.zip'):
        with zipfile.ZipFile(path) as nested:
            assert nested.testzip() is None
    archive = ROOT / 'packages' / (NAME + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(PACKAGE.rglob('*')):
            if path.is_file():
                bundle.write(path, NAME + '/' + path.relative_to(PACKAGE).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, row in manifest['files'].items():
            data = bundle.read(NAME + '/' + name)
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        assert bundle.read(NAME + '/package-manifest.json') == (PACKAGE / 'package-manifest.json').read_bytes()
    before = HERE / 'root-entry-before-driver'
    before.mkdir(exist_ok=False)
    entries = {'一键正式写入B站.cmd': '一键正式写入B站.cmd', '一键恢复用户反馈.cmd': '一键恢复原系统.cmd',
        '校验免ADB刷写包.cmd': '校验刷写包.cmd', '一键安装P011下载驱动.cmd': '一键安装下载驱动.cmd'}
    for local, packaged in entries.items():
        path = ROOT / local
        if path.exists():
            shutil.copy2(path, before / local)
        destination = PACKAGE / packaged
        assert destination.is_file()
        path.write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncall "%~dp0' + str(destination.relative_to(ROOT)) + '"\r\nexit /b %ERRORLEVEL%\r\n').encode('utf-8'))
    result = {'status': 'DRIVER_BUNDLED_HOST_VERIFIED_DEVICE_AND_CLEAN_PC_PENDING',
        'zip': str(archive), 'zip_bytes': archive.stat().st_size, 'zip_sha256': sha(archive),
        'package_files': len(manifest['files']) + 1, 'driver_included': True, 'driver_version': '4.20.42.134',
        'driver_signature_and_members_verified': True, 'native_registered_driver_readonly_check': True,
        'unicode_space_relocation_isolated_python': True, 'zip_crc_and_all_member_sha_verified': True,
        'driver_new_host_unit_tests': 10, 'driver_host_unit_evidence_chunk': 'e0a679',
        'baseline_flash_host_checks_reused': 11, 'candidate_sha256_unchanged': manifest['candidate_sha256'],
        'driver_installed_this_turn': False, 'usb_protocol_used_this_turn': False,
        'clean_pc_driver_first_install_tested': False, 'uac_helper_real_install_tested': False,
        'system_device_acceptance': False, 'root_entries_updated': list(entries)}
    (HERE / 'driver-package-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
