"""Restart the exact installed Z03 after a verified captcha QML repair.

This separate host entry does not alter the already prepared repair package.
Its device operation requires an inactive Bili session and the installed UI
patch receipt, retains the vendor launcher, and verifies the full payload.
"""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True

DEVICE_RESTART = r'''
def restart_verified_ui():
    lock = transaction_lock()
    result = dict(ui_restarted=False, restart_attempted=False,
                  physical_acceptance=False, system_files_changed=False,
                  revision=PATCH['revision_sha256'])
    try:
        expected_files = len(PATCH['manifest_keys'])
        require(expected_files == 69, 'expected formal release manifest differs')
        verified_before = qml_verify()
        require(verified_before['payload']['payload_files_verified'] == expected_files,
                'pre-restart payload verification incomplete')
        receipt, before, runtime, idle = qml_gate(True)
        receipt_before = read(FORMAL + '/install-receipt.json')
        require('ro' in before['mounts']['options'], 'root filesystem baseline is not read-only')
        stock_hashes = {path:digest(path) for path in PINS}
        service_before = service_rows(BASE)
        require(len(service_before) == 1, 'formal service identity is ambiguous')
        result['restart_attempted'] = True
        new_app = restart_ui(PATCH['patched_sha256'], PATCH['patched_sha256'],
                             before['app'], before['launcher'])
        _, after, _, _ = qml_gate(True)
        keys = ('pid', 'parent', 'start', 'exe', 'args')
        require(all(after['launcher'][key] == before['launcher'][key] for key in keys),
                'vendor launcher identity changed')
        require(after['app']['pid'] != before['app']['pid'] and
                after['app']['start'] != before['app']['start'],
                'new UI PID and start time were not observed')
        require(all(after['app'][key] == new_app[key] for key in keys),
                'restarted UI identity changed before verification')
        require(digest('/proc/%d/exe' % after['app']['pid']) == PATCH['patched_sha256'],
                'restarted UI executable differs')
        require(after['boot'] == before['boot'] and after['mounts'] == before['mounts'] and
                'ro' in after['mounts']['options'] and after['startup'] == before['startup'],
                'boot, root mount or startup changed')
        require({path:digest(path) for path in PINS} == stock_hashes,
                'stock file hashes changed during UI restart')
        require(read(FORMAL + '/install-receipt.json') == receipt_before,
                'installation receipt changed during UI restart')
        service_after = service_rows(BASE)
        require(len(service_after) == 1 and
                all(service_after[0][key] == service_before[0][key] for key in keys),
                'formal service changed during UI restart')
        verified_after = qml_verify()
        require(verified_after['payload']['payload_files_verified'] == expected_files,
                'post-restart payload verification incomplete')
        result.update(ui_restarted=True, payload_files_verified=expected_files,
                      new_ui_pid_and_start_observed=True,
                      vendor_launcher_unchanged=True, stock_hashes_unchanged=True,
                      boot_startup_root_mount_unchanged=True, root_readonly=True,
                      formal_service_unchanged=True, receipt_unchanged=True,
                      payload=verified_after['payload'],
                      page_visual_acceptance=False)
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        os.close(lock)
        print('RESULT=' + repr(result), flush=True)
    return result
'''


def load_host():
    spec = importlib.util.spec_from_file_location('captcha_local_patch_host', HERE / 'run_patch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--transport', type=int, required=True)
    args = parser.parse_args()
    host = load_host()
    package = args.package.resolve()
    patch = host.verify_package(package)
    assert len(patch['manifest_keys']) == 69, 'fixed release manifest membership differs'
    reader = host.load_reader(package / 'legacy_reader.py')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = HERE / 'evidence' / ('restart-ui-' + stamp)
    out.mkdir(parents=True)
    report = dict(passed=False, action='restart-ui', ui_restart_requested=False,
                  system_files_changed=False, physical_acceptance=False,
                  revision=patch['revision_sha256'])
    adb = reader.Adb(out, args.transport)
    try:
        adb.transport = reader.choose_transport(adb, args.transport)
        code = host.remote_code(package, patch) + '\n' + DEVICE_RESTART
        # An independent read-only call gives a useful failure report before
        # requesting the operation. The device function checks again under lock.
        preflight = '\nprint("RESULT="+repr(dict(verification=qml_verify(),idle=qml_gate(True)[3])),flush=True)\n'
        report['before'] = reader.result(adb.python('restart-readonly-preflight', code + preflight, 90))
        report['ui_restart_requested'] = True
        report['device'] = reader.result(adb.python('restart-installed-ui',
            code + '\nrestart_verified_ui()\n', 150))
        assert report['device']['ui_restarted'] is True
        report['passed'] = True
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        archive = Path(str(out) + '.private.zip')
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
            for member in out.iterdir():
                if member.is_file():
                    z.write(member, member.name)
        print(json.dumps(dict(report, logs=str(out), archive=str(archive)), ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
