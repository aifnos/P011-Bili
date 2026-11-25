"""Collect this repair's explicit, non-challenge evidence into one private ZIP."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PACKAGE = HERE / 'out/captcha-layout-7f9abf06e25c1d0018ed891b'
HOST_QA = ROOT / 'formal/evidence/captcha-host-layout-20261020-011605'
DEVICE_EVIDENCE = (
    'inspect-20261020-011549-766274',
    'apply-20261020-011607-705335',
    'restart-ui-20261020-011619-124402',
    'verify-20261020-011842-848054',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = HERE / 'evidence' / ('delivery-' + stamp)
    out.mkdir()
    host = json.loads((HOST_QA / 'result.json').read_bytes())
    assert host['passed'] and host['host_only'] and not host['real_challenge_loaded']
    assert host['source_sha256'] == sha(ROOT / 'client/BiliCaptcha.qml')
    assert host['source_sha256'] == sha(PACKAGE / 'source/BiliCaptcha.qml')
    units = []
    for label, cwd, argv in (
        ('transaction-and-restart', HERE, ['-m', 'unittest', 'discover', '-s', str(HERE), '-p', 'test_*.py']),
        ('layout-units', ROOT / 'host', ['-m', 'unittest', 'test_captcha_layout_qa']),
        ('account-regression', ROOT / 'host', ['-m', 'unittest', 'test_account_features']),
    ):
        run = subprocess.run([sys.executable, '-B'] + argv, cwd=cwd, capture_output=True, timeout=60)
        (out / (label + '.stdout.raw')).write_bytes(run.stdout)
        (out / (label + '.stderr.raw')).write_bytes(run.stderr)
        row = dict(name=label, host_exit=run.returncode, device_accessed=False)
        (out / (label + '.status.json')).write_text(json.dumps(row, indent=2), encoding='utf8')
        assert run.returncode == 0, label
        units.append(row)
    devices = {}
    for name in DEVICE_EVIDENCE:
        folder = HERE / 'evidence' / name
        result = json.loads((folder / 'result.json').read_bytes())
        assert result['passed'], name
        devices[name.split('-2026')[0]] = result
        shutil.copytree(folder, out / 'device' / name)
    shutil.copytree(HOST_QA, out / 'host-synthetic')
    shutil.copytree(PACKAGE, out / 'repair-package')
    for name in ('run_patch.py', 'device_patch.py', 'restart_ui.py', 'test_hotfix.py', 'test_restart_ui.py'):
        (out / 'repair-tools').mkdir(exist_ok=True)
        shutil.copyfile(HERE / name, out / 'repair-tools' / name)
    report = dict(
        status='DEPLOYED_HOST_GEOMETRY_PASS_REAL_CAPTCHA_MANUAL_PENDING',
        revision=json.loads((PACKAGE / 'patch.json').read_bytes())['revision_sha256'],
        source_sha256=host['source_sha256'],
        modified_qml=['BiliCaptcha.qml', 'BiliExtras.qml'],
        keyboard_modified=False, account_protocol_modified=False,
        original_system_files_changed=False, device_payload_files_verified=69,
        host_units=units, host_geometry_result='host-synthetic/result.json',
        device_apply='device/apply-20261020-011607-705335/result.json',
        device_restart='device/restart-ui-20261020-011619-124402/result.json',
        device_verify='device/verify-20261020-011842-848054/result.json',
        real_challenge_solved=False, real_captcha_acceptance=False,
        privacy='No password, cookies, real CAPTCHA screenshots or answers collected in this archive. Raw ADB logs may contain device identifiers.',
    )
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    members = {p.relative_to(out).as_posix(): sha(p) for p in out.rglob('*') if p.is_file()}
    (out / 'evidence-sha256.json').write_text(json.dumps(members, sort_keys=True, indent=2), encoding='utf8')
    archive = Path(str(out) + '.private.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for path in out.rglob('*'):
            if path.is_file():
                z.write(path, path.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name, expected in members.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == expected
    print(json.dumps(dict(report=str(out / 'result.json'), archive=str(archive), sha256=sha(archive)), ensure_ascii=False))


if __name__ == '__main__':
    main()
