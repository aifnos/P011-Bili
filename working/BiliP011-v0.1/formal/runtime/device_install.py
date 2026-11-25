"""Explicit formal installation, not a trial. Python 3.5; fixed targets only.

Every system write is preceded by firmware, process, mount, payload and backup
checks. No reboot, partition write, radio change, vendor launcher edit or ADB
change. Rollback preserves application data and immutable releases.
"""
from __future__ import print_function
import os
import sys
BASE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(BASE, 'app', 'stdlib-json35.zip'))
import json
import hashlib
import re
import shutil
import signal
import stat
import subprocess
import time
import ctypes

AREA = '/mnt/data/p011-toolbox'
FORMAL = AREA + '/bili-formal'
TARGET = '/usr/bin/Z03'
UNIT = '/etc/systemd/system/p011-bili-formal.service'
INIT = '/etc/init.d/p011-bili-formal'
PINS = {
    TARGET: 'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a',
    '/usr/bin/control_engine': '364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d',
    '/usr/bin/zyb_z03_launch.sh': '7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b'}
FIRMWARE = 'z031_v2.4.0-20251128_174826-user'


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def read(path, limit=1048576):
    with open(path, 'rb') as handle:
        value = handle.read(limit + 1)
    require(len(value) <= limit, 'read limit: ' + path)
    return value


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(65536)
            if not block:
                break
            value.update(block)
    return value.hexdigest()


def regular(path):
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0, 'unsafe file: ' + path)
    return info


def directory(path, create=False):
    require(path == AREA or path.startswith(AREA + '/'), 'outside managed area')
    require(os.path.normpath(path) == path, 'noncanonical path')
    current = ''
    for part in path.strip('/').split('/'):
        current += '/' + part
        if not os.path.lexists(current) and create and current.startswith(AREA):
            os.mkdir(current, 0o700)
        info = os.lstat(current)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0, 'unsafe directory: ' + current)
    return path


def atomic(path, data, mode=0o600):
    temporary = path + '.p011-new-' + str(os.getpid())
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    fd = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    atomic(path, json.dumps(value, sort_keys=True, indent=2).encode('ascii'))


def command(args, timeout=30):
    # Only fixed executables and installer-owned paths reach this function.
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        raise RuntimeError('command timeout: ' + args[0])
    require(process.returncode == 0, 'command failed: ' + args[0] + ' rc=' + str(process.returncode))
    return out


def proc(pid):
    try:
        text = read('/proc/%d/stat' % pid, 8192).decode('ascii')
        fields = text[text.rindex(')') + 2:].split()
        row = dict(pid=int(pid), start=fields[19], state=fields[0], parent=int(fields[1]),
                   exe=os.readlink('/proc/%d/exe' % pid),
                   args=[os.fsdecode(x) for x in read('/proc/%d/cmdline' % pid, 65536).split(b'\0') if x])
        again = read('/proc/%d/stat' % pid, 8192).decode('ascii')
        require(again[again.rindex(')') + 2:].split()[19] == row['start'], 'PID changed while reading')
        return row
    except (FileNotFoundError, ProcessLookupError):
        return None


def processes():
    rows = []
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        row = proc(int(name))
        if row and row['state'] not in ('Z', 'X'):
            rows.append(row)
    return rows


def terminate(row, expected_hash=None):
    current = proc(row['pid'])
    if not current or current['start'] != row['start']:
        return
    require(current['exe'] == row['exe'] or current['exe'] == row['exe'] + ' (deleted)', 'exec changed; signal refused')
    if expected_hash:
        require(digest('/proc/%d/exe' % row['pid']) == expected_hash, 'running executable differs')
    require(row['pid'] > 1 and row['pid'] != os.getpid(), 'signal target refused')
    os.kill(row['pid'], signal.SIGTERM)
    until = time.monotonic() + 15
    while time.monotonic() < until:
        current = proc(row['pid'])
        if not current or current['start'] != row['start'] or current['state'] in ('Z', 'X'):
            return
        time.sleep(.1)
    raise RuntimeError('normal exit not confirmed; no forced stock kill')


def mount_snapshot():
    rows = []
    for line in read('/proc/mounts').decode('ascii').splitlines():
        fields = line.split()
        if len(fields) >= 4:
            rows.append(dict(device=fields[0], at=fields[1], type=fields[2], options=fields[3].split(',')))
    root = [row for row in rows if row['at'] == '/']
    require(len(root) == 1 and root[0]['type'] == 'ext4', 'unsupported root mount')
    for path in (TARGET, UNIT, INIT):
        covering = [row for row in rows if row['at'] != '/' and path.startswith(row['at'].rstrip('/') + '/')]
        require(not covering, 'separate system mount requires review')
    return root[0]


def startup_plan():
    init_exe = os.readlink('/proc/1/exe')
    if os.path.basename(init_exe) == 'systemd':
        systemctl = next((p for p in ('/bin/systemctl', '/usr/bin/systemctl') if os.path.isfile(p)), None)
        require(systemctl is not None and os.path.isdir('/etc/systemd/system'), 'systemd controls unavailable')
        info = os.lstat('/etc/systemd/system')
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and os.path.realpath('/etc/systemd/system') == '/etc/systemd/system', 'unsafe systemd directory')
        return dict(kind='systemd', path=UNIT, systemctl=systemctl, init_exe=init_exe)
    # SysV: accept only a declared default runlevel and the conventional rc
    # dispatcher. Never append to or patch a vendor startup script.
    require(os.path.basename(init_exe) in ('init', 'busybox'), 'unsupported init')
    inittab = read('/etc/inittab', 65536).decode('ascii')
    matches = re.findall(r'^\s*[^:#]+:([2-5]):initdefault:\s*$', inittab, re.M)
    require(len(matches) == 1, 'default SysV runlevel not established')
    level = matches[0]
    dispatch = re.findall(r'^\s*[^:#]+:([2-5]+):wait:(/etc/init.d/rc)\s+([2-5])\s*$', inittab, re.M)
    require(any(level in levels and arg == level for levels, path, arg in dispatch), 'SysV dispatcher not established')
    regular('/etc/init.d/rc')
    rc_dir = '/etc/rc' + level + '.d'
    require(os.path.isdir(rc_dir) and not os.path.islink(rc_dir), 'runlevel directory unavailable')
    return dict(kind='sysv', path=INIT, link=rc_dir + '/S99p011-bili-formal', init_exe=init_exe)


def live_gate(z03_hash, allow_service=False, allow_deleted=False):
    require(os.getuid() == 0, 'root ADB required')
    require(os.uname()[0] == 'Linux' and os.uname()[4] == 'armv7l', 'not a P011 ARMv7 target')
    release = read('/etc/os-release', 8192).decode('ascii')
    require(FIRMWARE in release, 'firmware differs from supported v2.4.0')
    expected = dict(PINS)
    expected[TARGET] = z03_hash
    require({path: digest(path) for path in expected} == expected, 'firmware file identity differs')
    for path in expected:
        regular(path)
    for path in (AREA + '/bili-awake.lock', AREA + '/native.lock', '/tmp/p011-menutest.lock', '/mnt/data/p011-menu'):
        require(not os.path.lexists(path), 'existing trial requires inspection: ' + path)
    all_rows = processes()
    apps = [r for r in all_rows if r['exe'] == TARGET or allow_deleted and r['exe'] == TARGET + ' (deleted)']
    loops = [r for r in all_rows if '/usr/bin/zyb_z03_launch.sh' in r['args'][:3]]
    require(len(apps) == len(loops) == 1, 'stock UI/parent is not unique')
    require(apps[0]['parent'] == loops[0]['pid'] and apps[0]['args'][1:] == ['-platform', 'wayland'], 'stock topology differs')
    require(all(r['state'] not in ('D', 'T', 't') for r in apps + loops), 'stock UI/parent unhealthy')
    for name in ('control_engine', 'weston'):
        require(len([r for r in all_rows if os.path.basename(r['exe']) == name]) == 1, 'ambiguous ' + name)
    if not allow_service:
        ancestors = set()
        row = proc(os.getpid())
        while row and row['pid'] not in ancestors:
            ancestors.add(row['pid'])
            row = proc(row['parent']) if row['parent'] > 0 else None
        for row in all_rows:
            if row['pid'] in ancestors:
                continue
            require(not row['exe'].startswith(AREA + '/') and not any(AREA + '/' in a for a in row['args'][1:3]),
                    'another managed program is active')
    env = dict(os.fsdecode(x).split('=', 1) for x in read('/proc/%d/environ' % apps[0]['pid'], 131072).split(b'\0') if b'=' in x)
    require(env.get('XDG_RUNTIME_DIR') == '/run/user/0' and env.get('WAYLAND_DISPLAY', 'wayland-0') == 'wayland-0', 'display environment differs')
    return dict(app=apps[0], launcher=loops[0], boot=read('/proc/sys/kernel/random/boot_id', 128).decode('ascii').strip(),
                mounts=mount_snapshot(), startup=startup_plan())


def inspect():
    # Entirely read-only. Report paths/capabilities without device identifiers,
    # accounts, network addresses, command environments or vendor stdout.
    result = live_gate(PINS[TARGET])
    result['radio'] = {name: len([r for r in processes() if os.path.basename(r['exe']) == name])
                       for name in ('connmand', 'bluetoothd')}
    result['wlan0'] = read('/sys/class/net/wlan0/operstate', 64).decode('ascii').strip() if os.path.exists('/sys/class/net/wlan0/operstate') else None
    return result


def metadata():
    meta = json.loads(read(BASE + '/build-result.json').decode('utf-8'))
    rid = meta.get('release_id', meta.get('session', ''))
    require(re.match(r'^[0-9a-f]{24}$', rid) is not None, 'release identity invalid')
    release = FORMAL + '/releases/' + rid
    runtime = AREA + '/bili-awake/' + rid
    return meta, rid, release, runtime


def verify_payload():
    meta, rid, release, runtime = metadata()
    directory(BASE)
    require(re.match(r'^' + FORMAL + r'/staging/[0-9a-f]{24}-[0-9]{14}$', BASE), 'installation stage location differs')
    require(digest(BASE + '/manifest.json') == meta['manifest_sha256'], 'payload manifest identity differs')
    manifest = json.loads(read(BASE + '/manifest.json').decode('utf-8'))
    if 'files' in manifest:
        manifest = manifest['files']
    require(isinstance(manifest, dict) and 'Z03.patched' in manifest, 'payload manifest missing')
    for name, record in manifest.items():
        require(re.match(r'^(?:app/[A-Za-z0-9_.+-]+|media/(?:bin|lib)(?:/gst)?/[A-Za-z0-9_.+-]+|media/manifest.json|source-manifest.json|Z03.patched)$', name), 'payload path refused: ' + name)
        path = BASE + '/' + name
        regular(path)
        require(os.path.getsize(path) == record['bytes'] and digest(path) == record['sha256'], 'payload differs: ' + name)
    expected_payload = set(manifest)
    observed_payload = set()
    for subdirectory in ('app', 'media'):
        for root, dirs, files in os.walk(BASE + '/' + subdirectory):
            for name in dirs:
                require(not os.path.islink(root + '/' + name), 'linked payload directory')
            for name in files:
                observed_payload.add(os.path.relpath(root + '/' + name, BASE))
    require(observed_payload == {name for name in expected_payload if name.startswith(('app/', 'media/'))}, 'unlisted payload files')
    require(meta['patched_sha256'] == digest(BASE + '/Z03.patched'), 'patched executable identity differs')
    return meta, manifest, rid, release, runtime


def startup_bytes(plan, release):
    if plan['kind'] == 'systemd':
        return ('[Unit]\nDescription=P011 Bili user feedback page\nAfter=local-fs.target\nRequiresMountsFor=/mnt/data\n'
                '[Service]\nType=simple\nExecStart=/usr/bin/python3 -B ' + release + '/app/formal_service.py\n'
                'WorkingDirectory=' + release + '/app\nEnvironment=HOME=/home\nEnvironment=XDG_RUNTIME_DIR=/run/user/0\n'
                'Environment=WAYLAND_DISPLAY=wayland-0\nUMask=0077\nLimitCORE=0\nRestart=on-failure\nRestartSec=3\n'
                'TimeoutStopSec=25\nKillMode=control-group\n[Install]\nWantedBy=multi-user.target\n').encode('ascii')
    return ('#!/bin/sh\n# Separate P011 Bili service; vendor startup files are untouched.\n'
            'case "$1" in\nstart) /usr/bin/python3 -B ' + release + '/device_install.py service-start ;;\n'
            'stop) /usr/bin/python3 -B ' + release + '/device_install.py service-stop ;;\n'
            'restart) "$0" stop && "$0" start ;;\n*) exit 2 ;;\nesac\n').encode('ascii')


def service_rows(release):
    path = release + '/app/formal_service.py'
    return [r for r in processes() if path in r['args'][1:4]]


def service_start(release, runtime):
    require(not service_rows(release), 'formal service already active')
    child = os.fork()
    if child == 0:
        os.setsid()
        fd = os.open(os.devnull, os.O_RDWR)
        for stream in (0, 1, 2):
            os.dup2(fd, stream)
        if fd > 2:
            os.close(fd)
        os.chdir(release + '/app')
        os.environ['HOME'] = '/home'
        os.environ['XDG_RUNTIME_DIR'] = '/run/user/0'
        os.environ['WAYLAND_DISPLAY'] = 'wayland-0'
        os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', release + '/app/formal_service.py'])
        os._exit(99)


def service_stop(release):
    rows = service_rows(release)
    require(len(rows) <= 1, 'formal service identity ambiguous')
    for row in rows:
        terminate(row)


def wait_service(release, runtime):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        rows = service_rows(release)
        if len(rows) == 1 and os.path.isfile(runtime + '/bili-endpoint.json'):
            regular(runtime + '/bili-endpoint.json')
            return rows[0]
        time.sleep(.15)
    raise RuntimeError('formal loopback service did not become ready')


def restart_ui(old_hash, expected_hash, row=None, launcher=None):
    apps = [r for r in processes() if r['exe'] in (TARGET, TARGET + ' (deleted)')]
    if row is None:
        require(len(apps) == 1, 'UI restart identity ambiguous')
        row = apps[0]
    terminate(row, old_hash)
    until = time.monotonic() + 25
    while time.monotonic() < until:
        apps = [r for r in processes() if r['exe'] == TARGET]
        if len(apps) == 1 and apps[0]['start'] != row['start'] and digest('/proc/%d/exe' % apps[0]['pid']) == expected_hash:
            parent = proc(apps[0]['parent'])
            require(parent and '/usr/bin/zyb_z03_launch.sh' in parent['args'][:3], 'new UI parent differs')
            if launcher is not None:
                require(parent['pid'] == launcher['pid'] and parent['start'] == launcher['start'] and parent['exe'] == launcher['exe'], 'vendor launcher identity changed')
            return apps[0]
        time.sleep(.2)
    raise RuntimeError('vendor loop did not restore the expected UI')


def remount(writable):
    command(['/bin/mount', '-o', 'remount,' + ('rw' if writable else 'ro'), '/'])
    require(('ro' not in mount_snapshot()['options']) == writable, 'root mount mode not confirmed')


def install():
    meta, manifest, rid, release, runtime = verify_payload()
    before = inspect()
    plan = before['startup']
    require(not os.path.lexists(FORMAL + '/install-receipt.json'), 'existing installation: use status or restore first')
    for path in (plan['path'], plan.get('link', '/nonexistent-p011-check')):
        require(not os.path.lexists(path), 'startup target already exists: ' + path)
    if plan['kind'] == 'systemd':
        require(not os.path.lexists('/etc/systemd/system/multi-user.target.wants/p011-bili-formal.service'), 'existing service enablement requires inspection')
    require(not os.path.lexists(release) and not os.path.lexists(runtime), 'release/runtime already exists; inspect partial install')
    require(os.statvfs('/mnt/data').f_bavail * os.statvfs('/mnt/data').f_frsize > sum(v['bytes'] for v in manifest.values()) + 16777216,
            'insufficient storage for payload and rollback')
    directory(FORMAL + '/backups', True)
    backup = FORMAL + '/backups/' + rid + '-' + time.strftime('%Y%m%d-%H%M%S')
    directory(backup, True)
    shutil.copyfile(TARGET, backup + '/Z03.original')
    require(digest(backup + '/Z03.original') == PINS[TARGET], 'original backup failed')
    save(backup + '/before.json', before)
    directory(release, True)
    directory(runtime, True)
    for name in sorted(manifest):
        if name == 'Z03.patched':
            continue
        destination = release + '/' + name
        directory(os.path.dirname(destination), True)
        shutil.copyfile(BASE + '/' + name, destination)
        os.chmod(destination, 0o700 if name.startswith('media/bin/') else 0o600)
        require(digest(destination) == manifest[name]['sha256'], 'staged file readback differs')
    for name in ('device_install.py', 'build-result.json', 'manifest.json'):
        shutil.copyfile(BASE + '/' + name, release + '/' + name)
        os.chmod(release + '/' + name, 0o600)
    directory(release + '/media/config', True)
    directory(release + '/media/cache', True)
    originally_ro = 'ro' in before['mounts']['options']
    changed = False
    startup_created = False
    result = dict(release_id=rid, backup=backup, release=release, runtime=runtime, startup=plan,
                  old_sha256=PINS[TARGET], patched_sha256=meta['patched_sha256'],
                  installed=False, physical_acceptance=False, settings_navigation_verified=False)
    save(backup + '/transaction.json', result)
    try:
        # Recheck immediately before the first system write. Remount is only
        # for this explicit installation and only when the verified root is ro.
        live_gate(PINS[TARGET])
        if originally_ro:
            remount(True)
        content = startup_bytes(plan, release)
        startup_created = True
        atomic(plan['path'], content, 0o644 if plan['kind'] == 'systemd' else 0o755)
        if plan['kind'] == 'systemd':
            command([plan['systemctl'], 'daemon-reload'])
            command([plan['systemctl'], 'enable', 'p011-bili-formal.service'])
            command([plan['systemctl'], 'start', 'p011-bili-formal.service'])
        else:
            os.symlink('../init.d/p011-bili-formal', plan['link'])
            service_start(release, runtime)
        result['service'] = wait_service(release, runtime)
        original_mode = stat.S_IMODE(os.stat(TARGET).st_mode)
        changed = True
        atomic(TARGET, read(BASE + '/Z03.patched', 16777216), original_mode)
        require(digest(TARGET) == meta['patched_sha256'], 'written executable readback differs')
        result['ui'] = restart_ui(PINS[TARGET], meta['patched_sha256'], before['app'], before['launcher'])
        require(digest('/usr/bin/control_engine') == PINS['/usr/bin/control_engine'] and
                digest('/usr/bin/zyb_z03_launch.sh') == PINS['/usr/bin/zyb_z03_launch.sh'], 'protected file changed')
        result['startup_sha256'] = digest(plan['path'])
        result['installed'] = True
        save(FORMAL + '/install-receipt.json', result)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        # Roll back the exact files created by this transaction; keep evidence
        # and all payload/user directories. A failed rollback stays a failure.
        try:
            if changed:
                old = digest(TARGET)
                require(old in (meta['patched_sha256'], PINS[TARGET]), 'rollback refused: target drift')
                if old == meta['patched_sha256']:
                    atomic(TARGET, read(backup + '/Z03.original', 16777216), stat.S_IMODE(os.stat(TARGET).st_mode))
                apps = [r for r in processes() if r['exe'] in (TARGET, TARGET + ' (deleted)')]
                require(len(apps) == 1, 'rollback UI identity ambiguous')
                running_hash = digest('/proc/%d/exe' % apps[0]['pid'])
                if running_hash == meta['patched_sha256']:
                    restart_ui(running_hash, PINS[TARGET], apps[0], before['launcher'])
                else:
                    require(running_hash == PINS[TARGET], 'rollback running identity differs')
            if startup_created and os.path.lexists(plan['path']):
                require(digest(plan['path']) == hashlib.sha256(startup_bytes(plan, release)).hexdigest(), 'startup drift')
                if plan['kind'] == 'systemd':
                    command([plan['systemctl'], 'stop', 'p011-bili-formal.service'])
                    command([plan['systemctl'], 'disable', 'p011-bili-formal.service'])
                else:
                    service_stop(release)
                    if os.path.islink(plan['link']) and os.readlink(plan['link']) == '../init.d/p011-bili-formal':
                        os.unlink(plan['link'])
                os.unlink(plan['path'])
                if plan['kind'] == 'systemd':
                    command([plan['systemctl'], 'daemon-reload'])
            result['rolled_back'] = digest(TARGET) == PINS[TARGET]
        except Exception as rollback_error:
            result['rollback_error'] = type(rollback_error).__name__ + ': ' + str(rollback_error)
        raise
    finally:
        try:
            if originally_ro and 'ro' not in mount_snapshot()['options']:
                remount(False)
            result['root_mount_restored'] = ('ro' in mount_snapshot()['options']) == originally_ro
        finally:
            save(backup + '/transaction.json', result)
            print('RESULT=' + repr(result), flush=True)
    require(result['root_mount_restored'], 'root mount mode restoration failed')
    save(FORMAL + '/install-receipt.json', result)
    return result


def restore():
    receipt = json.loads(read(FORMAL + '/install-receipt.json').decode('ascii'))
    rid = receipt['release_id']
    require(re.match(r'^[0-9a-f]{24}$', rid), 'receipt identity invalid')
    release = FORMAL + '/releases/' + rid
    backup = receipt['backup']
    directory(backup)
    require(backup.startswith(FORMAL + '/backups/' + rid + '-'), 'backup path differs')
    require(digest(backup + '/Z03.original') == PINS[TARGET], 'rollback original differs')
    disk_hash = digest(TARGET)
    require(disk_hash in (PINS[TARGET], receipt['patched_sha256']), 'restore target drift')
    live = live_gate(disk_hash, allow_service=True, allow_deleted=True)
    running_hash = digest('/proc/%d/exe' % live['app']['pid'])
    require(running_hash in (PINS[TARGET], receipt['patched_sha256']), 'restore running UI drift')
    plan = receipt['startup']
    require(plan == live['startup'] and digest(plan['path']) == receipt['startup_sha256'], 'startup drift')
    ro = 'ro' in live['mounts']['options']
    result = dict(restored=False, physical_acceptance=False, release_id=rid, backup=backup)
    try:
        if ro:
            remount(True)
        # Keep the formal service alive until the restored stock executable
        # is running. An fsync/restart failure cannot strand a live Bili page.
        if disk_hash != PINS[TARGET]:
            atomic(TARGET, read(backup + '/Z03.original', 16777216), stat.S_IMODE(os.stat(TARGET).st_mode))
        if running_hash != PINS[TARGET] or live['app']['exe'].endswith(' (deleted)'):
            restart_ui(running_hash, PINS[TARGET], live['app'], live['launcher'])
        if plan['kind'] == 'systemd':
            command([plan['systemctl'], 'stop', 'p011-bili-formal.service'])
            command([plan['systemctl'], 'disable', 'p011-bili-formal.service'])
        else:
            service_stop(release)
            require(os.path.islink(plan['link']) and os.readlink(plan['link']) == '../init.d/p011-bili-formal', 'init link drift')
            os.unlink(plan['link'])
        os.unlink(plan['path'])
        if plan['kind'] == 'systemd':
            command([plan['systemctl'], 'daemon-reload'])
        os.rename(FORMAL + '/install-receipt.json', backup + '/restored-install-receipt.json')
        result['restored'] = True
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        # If the UI file is still the installed version, restore its own
        # service after a failed uninstallation instead of stranding the page.
        try:
            if digest(TARGET) == receipt['patched_sha256']:
                if plan['kind'] == 'systemd':
                    command([plan['systemctl'], 'enable', 'p011-bili-formal.service'])
                    command([plan['systemctl'], 'start', 'p011-bili-formal.service'])
                elif not service_rows(release):
                    if not os.path.lexists(plan['link']):
                        os.symlink('../init.d/p011-bili-formal', plan['link'])
                    service_start(release, receipt['runtime'])
                result['installed_service_recovered'] = True
        except Exception as recovery_error:
            result['recovery_error'] = type(recovery_error).__name__ + ': ' + str(recovery_error)
        raise
    finally:
        if ro and 'ro' not in mount_snapshot()['options']:
            remount(False)
        result['root_mount_restored'] = ('ro' in mount_snapshot()['options']) == ro
        save(backup + '/restore-result.json', result)
        print('RESULT=' + repr(result), flush=True)
    return result


def transaction_lock():
    directory(FORMAL, True)
    path = FORMAL + '/install.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0, 'unsafe installation lock')
        if ctypes.CDLL(None, use_errno=True).flock(fd, 2 | 4):
            raise RuntimeError('another install or restore is active')
        return fd
    except Exception:
        os.close(fd)
        raise


def main():
    require(len(sys.argv) == 2, 'one explicit action required')
    action = sys.argv[1]
    if action == 'inspect':
        print('RESULT=' + repr(inspect()))
    elif action == 'install':
        verify_payload()
        inspect()
        lock_fd = transaction_lock()
        try:
            install()
        finally:
            os.close(lock_fd)
    elif action == 'restore':
        receipt = json.loads(read(FORMAL + '/install-receipt.json').decode('ascii'))
        current_hash = digest(TARGET)
        require(current_hash in (PINS[TARGET], receipt['patched_sha256']), 'restore target drift')
        live_gate(current_hash, True, True)
        lock_fd = transaction_lock()
        try:
            restore()
        finally:
            os.close(lock_fd)
    elif action == 'status':
        receipt = json.loads(read(FORMAL + '/install-receipt.json').decode('ascii'))
        live_gate(receipt['patched_sha256'], True)
        print('RESULT=' + repr(dict(installed=True, release_id=receipt['release_id'], physical_acceptance=False)))
    elif action in ('service-start', 'service-stop'):
        meta, rid, release, runtime = metadata()
        require(BASE == release, 'service control location differs')
        if action == 'service-start':
            service_start(release, runtime)
        else:
            service_stop(release)
    else:
        raise RuntimeError('unknown action')


if __name__ == '__main__':
    main()
