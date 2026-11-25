"""PC one-click installer. An explicit 'install' is the only write entry.

Raw ADB stdout/stderr and host/remote exits stay separate. ZIP contains only
installation evidence; cookies, QR codes, user files and vendor UI logs are
never pulled. No archived START or legacy trial entry is invoked.
"""
import argparse
import ast
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_root():
    # The packaged copy lives beside its payload. The source entry takes an
    # explicit --package so it cannot accidentally choose an old release.
    return HERE if (HERE / 'build-result.json').is_file() else None


def verify_package(package):
    raw = (package / 'PACKAGE.sha256').read_text(encoding='utf-8')
    listed = set()
    for line in raw.splitlines():
        value, length, name = line.split(' ', 2)
        if (not re.fullmatch(r'[\w.+-]+(?:/[\w.+-]+)*', name) or
                any(part in ('.', '..') for part in name.split('/')) or name in listed):
            raise ValueError('Invalid package manifest path')
        path = package / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != int(length) or sha(path) != value:
            raise ValueError('Package identity differs: ' + name)
        listed.add(name)
    required = {'device_install.py', 'install_formal.py', 'build-result.json', 'manifest.json', 'Z03.patched',
                'app/formal_service.py', 'app/stdlib-json35.zip'}
    if not required <= listed:
        raise ValueError('Package is incomplete')
    observed = set()
    for path in package.rglob('*'):
        if path.is_symlink():
            raise ValueError('Linked package member refused')
        if path.is_file():
            observed.add(path.relative_to(package).as_posix())
    if observed != listed | {'PACKAGE.sha256'}:
        raise ValueError('Package contains unlisted or missing files')
    meta = json.loads((package / 'build-result.json').read_text(encoding='utf-8'))
    rid = meta['release_id']
    if not re.fullmatch('[0-9a-f]{24}', rid):
        raise ValueError('Invalid release identity')
    return meta, listed


class Adb:
    def __init__(self, out, transport=None):
        self.out = out
        self.transport = transport
        self.sequence = 0

    def run(self, name, args, data=None, timeout=30):
        self.sequence += 1
        prefix = self.out / ('%02d-%s' % (self.sequence, name))
        argv = ['adb'] + (['-t', str(self.transport)] if self.transport is not None else []) + args
        try:
            child = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            stdout, stderr, host_exit, expired = child.stdout, child.stderr, child.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, host_exit, expired = exc.stdout or b'', exc.stderr or b'', None, True
        prefix.with_suffix('.stdout.raw').write_bytes(stdout)
        prefix.with_suffix('.stderr.raw').write_bytes(stderr)
        # CRCRLF/ANSI are normalized only for parsing this derived result.
        decoded = stdout.decode('utf-8', 'replace').replace('\r\r\n', '\n').replace('\r\n', '\n')
        decoded = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', decoded)
        markers = re.findall(r'^P011_FORMAL_REMOTE_EXIT=([0-9]+)$', decoded, re.M)
        remote_exit = int(markers[-1]) if markers else None
        status = dict(host_exit=host_exit, remote_exit=remote_exit, timeout=expired,
                      stderr_bytes=len(stderr), remote_exit_applicable='exec-out' in args)
        prefix.with_suffix('.status.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
        if expired or host_exit != 0 or ('exec-out' in args and remote_exit != 0):
            raise RuntimeError('%s failed; inspect raw logs and status' % name)
        return decoded

    def python(self, name, code, timeout=35):
        wrapper = ('import sys,traceback\ntry:\n exec(' + repr(code) + ')\n'
                   'except BaseException:\n traceback.print_exc()\n print("P011_FORMAL_REMOTE_EXIT=1",flush=True)\n sys.exit(1)\n'
                   'else:\n print("P011_FORMAL_REMOTE_EXIT=0",flush=True)\n')
        return self.run(name, ['exec-out', '/usr/bin/python3', '-B', '-'], wrapper.encode('utf-8'), timeout)


def result(text):
    for line in reversed(text.splitlines()):
        if line.startswith('RESULT='):
            value = ast.literal_eval(line[7:])
            if not isinstance(value, dict):
                raise ValueError('Remote result schema')
            return value
    raise RuntimeError('Remote result missing')


def choose_transport(adb, requested):
    listing = adb.run('devices', ['devices', '-l'])
    candidates = []
    for line in listing.splitlines():
        match = re.search(r'^\S+\s+device\b.*\btransport_id:(\d+)\b', line)
        if match:
            candidates.append(int(match.group(1)))
    if requested is not None:
        if requested not in candidates:
            raise RuntimeError('Requested ADB transport is unavailable')
        return requested
    # Select by read-only Linux identity; never default to the first transport
    # when Android emulators or other devices are also attached.
    accepted = []
    for transport in candidates:
        adb.transport = transport
        try:
            probe = result(adb.python('identity-%d' % transport,
                'import os\nprint("RESULT="+repr({"system":os.uname()[0],"machine":os.uname()[4],'
                '"p011": "z031_v2.4.0-20251128_174826-user" in open("/etc/os-release").read()}))'))
            if probe == {'system': 'Linux', 'machine': 'armv7l', 'p011': True}:
                accepted.append(transport)
        except RuntimeError:
            pass
    if len(accepted) != 1:
        raise RuntimeError('No unique supported P011 connected (found %d); connect it and enable root ADB' % len(accepted))
    return accepted[0]


def remote_call(adb, stage, action, timeout=180):
    if not re.fullmatch(r'/mnt/data/p011-toolbox/bili-formal/staging/[0-9a-f]{24}-[0-9]{14}', stage):
        raise ValueError('Stage path refused')
    code = ('import sys\nsys.path.insert(0,' + repr(stage + '/app/stdlib-json35.zip') + ')\n'
            'sys.path.insert(0,' + repr(stage) + ')\nimport device_install\n'
            'sys.argv=["device_install.py",' + repr(action) + ']\ndevice_install.main()\n')
    return result(adb.python(action, code, timeout))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'inspect', 'restore', 'status', 'verify'])
    parser.add_argument('--package', type=pathlib.Path, default=package_root())
    parser.add_argument('--transport', type=int)
    parser.add_argument('--logs', type=pathlib.Path)
    args = parser.parse_args()
    if args.package is None:
        parser.error('Source entry requires --package; use the packaged one-click CMD')
    package = args.package.resolve()
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    out = args.logs or package.parent / ('P011-Bili-Formal-' + args.action + '-' + timestamp)
    out.mkdir(parents=True, exist_ok=False)
    report = dict(action=args.action, passed=False, device_write_started=False, physical_acceptance=False,
                  settings_navigation_verified=False, no_device_test=False)
    print('LOG_DIR=' + str(out), flush=True)
    try:
        meta, listed = verify_package(package)
        report['release_id'] = meta['release_id']
        if args.action == 'verify':
            report.update(passed=True, host_only=True)
            return 0
        if not shutil.which('adb'):
            raise RuntimeError('ADB is not installed on this PC')
        adb = Adb(out)
        adb.transport = choose_transport(adb, args.transport)
        report['transport_id'] = adb.transport
        # Execute the same live gate from stdin before creating any device
        # directories. This path needs no target json standard library.
        installer = (package / 'device_install.py').read_text(encoding='utf-8')
        inspector = installer.replace('import json\n', '# json unused by read-only inspection\n', 1)
        inspector = inspector.replace('from __future__ import print_function\n', '', 1)
        inspector = inspector.rsplit("if __name__ == '__main__':", 1)[0]
        preflight_code = '__file__="/tmp/p011-formal-readonly.py"\n' + inspector
        if args.action in ('inspect', 'install'):
            before = result(adb.python('readonly-preflight', preflight_code + '\nprint("RESULT="+repr(inspect()))\n'))
            report['preflight'] = before
        if args.action == 'inspect':
            report.update(passed=True, read_only=True)
            return 0
        if args.action in ('restore', 'status'):
            code = ('import sys\nsys.path.insert(0,' + repr('/mnt/data/p011-toolbox/bili-formal/releases/' + meta['release_id'] + '/app/stdlib-json35.zip') + ')\n'
                    'sys.path.insert(0,' + repr('/mnt/data/p011-toolbox/bili-formal/releases/' + meta['release_id']) + ')\n'
                    'import device_install\nsys.argv=["device_install.py",' + repr(args.action) + ']\ndevice_install.main()\n')
            report['device_write_started'] = args.action == 'restore'
            report['device'] = result(adb.python(args.action, code, 180))
            report['passed'] = True
            return 0
        stage = '/mnt/data/p011-toolbox/bili-formal/staging/' + meta['release_id'] + '-' + timestamp
        create_code = preflight_code + '\ndirectory(' + repr(stage.rsplit('/', 1)[0]) + ',True)\n'
        create_code += 'require(not os.path.lexists(' + repr(stage) + '),"stage exists")\nos.mkdir(' + repr(stage) + ',0o700)\nprint("RESULT="+repr({"staged_directory":True}))\n'
        result(adb.python('stage-directory', create_code))
        report['device_write_started'] = True
        # Push only manifest-listed immutable payload. Never pull the runtime,
        # account, user directories or factory process logs.
        for folder in ('app', 'media'):
            adb.run('push-' + folder, ['push', str(package / folder), stage + '/' + folder], timeout=120)
        for name in ('Z03.patched', 'source-manifest.json', 'SOURCE.sha256', 'build-result.json', 'manifest.json', 'device_install.py'):
            adb.run('push-' + name.replace('.', '-'), ['push', str(package / name), stage + '/' + name], timeout=60)
        trusted = {name: sha(package / name) for name in ('device_install.py', 'build-result.json', 'manifest.json')}
        check_code = 'import hashlib\nbase=' + repr(stage) + '\nexpected=' + repr(trusted) + '\n'
        check_code += 'assert all(hashlib.sha256(open(base+"/"+n,"rb").read()).hexdigest()==v for n,v in expected.items())\nprint("RESULT="+repr({"bootstrap_hashes_verified":True}))\n'
        result(adb.python('verify-bootstrap-readback', check_code))
        check = remote_call(adb, stage, 'install', timeout=180)
        report['device'] = check
        report['passed'] = check.get('installed') is True and check.get('root_mount_restored') is True
        return 0 if report['passed'] else 1
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        report['no_device_test'] = not report['device_write_started']
        print('FAILED: ' + report['error'], flush=True)
        return 1
    finally:
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        archive = out.with_suffix('.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(out.iterdir()):
                if path.is_file():
                    bundle.write(path, path.name)
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise RuntimeError('Result ZIP integrity failed')
        print('RESULT_ZIP=' + str(archive), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
