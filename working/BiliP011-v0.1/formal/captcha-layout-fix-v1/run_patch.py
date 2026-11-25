"""Prepare, inspect, apply or verify the fixed five-file captcha QML repair."""
import argparse
import ast
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
FORMAL = HERE.parent
PROJECT = FORMAL.parent
BASE_PACKAGE = FORMAL / 'out/P011-Bili-ADB-v8-reinstall-cache-20261014'
RELEASE_ID = '9412e49de8feb2d6b2677180'
PATCHED_SHA = '3526b379c4083092c9c282d4d749d2e5c72d89e56730bf08c975e3222ed42896'
QML_NAMES = ('BiliCaptcha.qml', 'BiliExtras.qml')
ORDER = ['app/' + name for name in QML_NAMES] + [
    'source-manifest.json', 'manifest.json', 'build-result.json']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def spec(raw):
    return dict(sha256=sha(raw), bytes=len(raw))


def load_reader(path):
    # Importing the known reader must never add __pycache__ to the old v8
    # package, whose exact package membership remains immutable.
    sys.dont_write_bytecode = True
    module_spec = importlib.util.spec_from_file_location('captcha_legacy_reader', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def build_changes(base, source_files, transaction_raw):
    """Pure package assembly; source QML files are never edited here."""
    meta = json.loads((base / 'build-result.json').read_bytes())
    assert meta['release_id'] == RELEASE_ID and meta['patched_sha256'] == PATCHED_SHA
    assert 'ui_patch_revision' not in meta, 'already-patched base package'
    manifest = json.loads((base / 'manifest.json').read_bytes())
    assert sha((base / 'manifest.json').read_bytes()) == meta['manifest_sha256']
    source_manifest = json.loads((base / 'source-manifest.json').read_bytes())
    assert set(source_files) == set(QML_NAMES), 'only the two fixed QML files are accepted'
    before = {name: spec((base / name).read_bytes()) for name in ORDER}
    changes = {}
    source_records = dict(before={}, after={})
    for name in QML_NAMES:
        raw = source_files[name]
        assert isinstance(raw, bytes) and 0 < len(raw) < 1048576
        raw.decode('utf-8')
        installed_raw = raw.replace(b'@REMOTE@', meta['remote'].encode('ascii'))
        assert installed_raw != (base / 'app' / name).read_bytes(), name + ' was not changed'
        changes['app/' + name] = installed_raw
        source_records['before'][name] = source_manifest['client/' + name]
        source_records['after'][name] = spec(raw)
        source_manifest['client/' + name] = spec(raw)
    revision = sha(canonical(dict(release_id=RELEASE_ID, before=before,
        qml={name: spec(raw) for name, raw in changes.items()},
        transaction_sha256=sha(transaction_raw))))
    changes['source-manifest.json'] = canonical(source_manifest)
    for name, raw in changes.items():
        manifest[name] = spec(raw)
    changes['manifest.json'] = canonical(manifest)
    meta.update(manifest_sha256=sha(changes['manifest.json']),
                ui_patch_revision=revision,
                ui_patch_status='HOST_PREPARED_DEVICE_PENDING',
                ui_patch_reason='fit official login captcha within physical 800x268 display')
    changes['build-result.json'] = canonical(meta)
    patch = dict(release_id=RELEASE_ID, patched_sha256=PATCHED_SHA,
        revision_sha256=revision, base_source_identity_sha256=meta['source_identity_sha256'],
        order=list(ORDER), qml_paths=['app/' + name for name in QML_NAMES],
        before=before, after={name: spec(raw) for name, raw in changes.items()},
        source_records=source_records, manifest_keys=sorted(manifest))
    assert list(changes) == ORDER
    return patch, changes


def prepare(output=None):
    reader = load_reader(BASE_PACKAGE / 'install_formal.py')
    reader.verify_package(BASE_PACKAGE)
    source_files = {name: (PROJECT / 'client' / name).read_bytes() for name in QML_NAMES}
    transaction_raw = (HERE / 'device_patch.py').read_bytes()
    ast.parse(transaction_raw.decode('utf-8'), feature_version=(3, 5))
    patch, changes = build_changes(BASE_PACKAGE, source_files, transaction_raw)
    output = output or HERE / 'out' / ('captcha-layout-' + patch['revision_sha256'][:24])
    output = output.resolve()
    assert HERE in output.parents and not output.exists(), 'new output must be within this repair directory'
    output.mkdir(parents=True)
    for name, raw in changes.items():
        target = output / 'payload' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for name, raw in source_files.items():
        target = output / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (output / 'patch.json').write_bytes(canonical(patch))
    for name in ('run_patch.py', 'device_patch.py'):
        shutil.copyfile(HERE / name, output / name)
    shutil.copyfile(BASE_PACKAGE / 'install_formal.py', output / 'legacy_reader.py')
    shutil.copyfile(BASE_PACKAGE / 'device_install.py', output / 'device_install_helpers.py')
    members = {p.relative_to(output).as_posix(): spec(p.read_bytes())
               for p in output.rglob('*') if p.is_file()}
    (output / 'PACKAGE.json').write_bytes(canonical(members))
    print(json.dumps(dict(prepared=True, package=str(output),
        revision=patch['revision_sha256'], changed_files=ORDER, device_used=False)))
    return output


def verify_package(package):
    members = json.loads((package / 'PACKAGE.json').read_bytes())
    assert set(members) == {'patch.json', 'run_patch.py', 'device_patch.py',
        'legacy_reader.py', 'device_install_helpers.py'} | {
        'payload/' + name for name in ORDER} | {'source/' + name for name in QML_NAMES}
    for name, row in members.items():
        path = package / name
        assert not path.is_symlink() and path.is_file() and spec(path.read_bytes()) == row, name
    observed = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    assert observed == set(members) | {'PACKAGE.json'}, 'unlisted package files'
    assert not any(p.is_symlink() for p in package.rglob('*')), 'linked package member'
    patch = json.loads((package / 'patch.json').read_bytes())
    assert patch['release_id'] == RELEASE_ID and patch['patched_sha256'] == PATCHED_SHA
    assert patch['order'] == ORDER and set(patch['before']) == set(patch['after']) == set(ORDER)
    assert patch['qml_paths'] == ['app/' + name for name in QML_NAMES]
    assert re.fullmatch('[0-9a-f]{64}', patch['revision_sha256'])
    for name in ORDER:
        assert spec((package / 'payload' / name).read_bytes()) == patch['after'][name]
    return patch


def remote_code(package, patch):
    release = '/mnt/data/p011-toolbox/bili-formal/releases/' + RELEASE_ID
    helper = (package / 'device_install_helpers.py').read_text(encoding='utf-8')
    code = '__file__=' + repr(release + '/device_install.py') + '\n'
    code += helper.replace('from __future__ import print_function\n', '', 1).rsplit(
        "if __name__ == '__main__':", 1)[0]
    code += '\nPATCH=' + repr(patch) + '\n'
    code += (package / 'device_patch.py').read_text(encoding='utf-8')
    return code


def device_action(action, package, transport=None):
    patch = verify_package(package)
    reader = load_reader(package / 'legacy_reader.py')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = HERE / 'evidence' / (action + '-' + stamp)
    out.mkdir(parents=True)
    report = dict(passed=False, action=action, physical_acceptance=False,
                  device_write_started=False)
    adb = reader.Adb(out, transport)
    try:
        # The known formal host reader performs current Linux/firmware checks.
        adb.transport = reader.choose_transport(adb, transport)
        code = remote_code(package, patch)
        if action == 'inspect':
            report['device'] = reader.result(adb.python('inspect-ui-patch',
                code + '\nprint("RESULT="+repr(qml_inspect()),flush=True)\n', 90))
        elif action == 'verify':
            report['device'] = reader.result(adb.python('verify-ui-patch',
                code + '\nprint("RESULT="+repr(qml_verify()),flush=True)\n', 90))
        else:
            before = reader.result(adb.python('preflight-ui-patch',
                code + '\nprint("RESULT="+repr(qml_inspect()),flush=True)\n', 90))
            report['before'] = before
            assert before['ready'] is True, 'exit Bili and wait for session cleanup before apply'
            stage = '/mnt/data/p011-toolbox/bili-formal/ui-patches/' + patch['revision_sha256'][:24]
            report['device_write_started'] = True
            prepare_code = code + '\ndirectory(FORMAL+"/ui-patches",True)\ndirectory(' + repr(stage) + ',True)\n'
            prepare_code += 'directory(' + repr(stage + '/app') + ',True)\n'
            prepare_code += 'print("RESULT="+repr(dict(staging_ready=True)),flush=True)\n'
            reader.result(adb.python('prepare-ui-stage', prepare_code))
            for name in ORDER:
                adb.run('push-ui-patch', ['push', str(package / 'payload' / name), stage + '/' + name])
            report['device'] = reader.result(adb.python('apply-ui-patch',
                code + '\nqml_apply()\n', 150))
            assert report['device']['applied'] is True
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'inspect', 'apply', 'verify'))
    parser.add_argument('--package', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--transport', type=int)
    args = parser.parse_args()
    if args.action == 'prepare':
        if args.package is not None or args.transport is not None:
            parser.error('prepare is a host-only source assembly')
        prepare(args.output)
        return 0
    if args.output is not None:
        parser.error('--output is only accepted by prepare')
    package = args.package or (HERE if (HERE / 'patch.json').is_file() else None)
    if package is None:
        parser.error('use --package with a prepared repair directory')
    return device_action(args.action, package.resolve(), args.transport)


if __name__ == '__main__':
    raise SystemExit(main())
