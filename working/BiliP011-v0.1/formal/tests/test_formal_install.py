"""HOST-only installer fault injection: no ADB, Linux paths or signals used.

The transaction cases run the real install()/atomic() control flow against an
in-memory filesystem and recorded system calls. They are not hardware tests.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import signal
import stat
import tempfile
import types
import unittest
from unittest import mock

FORMAL = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


device = load('formal_device_install_tested', FORMAL/'runtime/device_install.py')
host = load('formal_host_install_tested', FORMAL/'host/install_formal.py')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def package_fixture(directory):
    contents = {
        'device_install.py': b'# HOST fixture only\n',
        'install_formal.py': b'# HOST fixture only\n',
        'build-result.json': json.dumps({'release_id': 'a'*24}).encode(),
        'manifest.json': b'{}', 'Z03.patched': b'fixture candidate',
        'app/formal_service.py': b'# HOST fixture only\n',
        'app/stdlib-json35.zip': b'fixture json zip'}
    for name, content in contents.items():
        target = directory/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (directory/'PACKAGE.sha256').write_text(''.join(
        sha(content)+' '+str(len(content))+' '+name+'\n'
        for name, content in sorted(contents.items())), encoding='ascii')
    return contents


class VirtualTransaction:
    """Only module-owned OS calls are replaced; real atomic logic is retained."""
    def __init__(self, fsync_failure=False, command_failure=None):
        self.rid = 'a'*24
        self.release = device.FORMAL+'/releases/'+self.rid
        self.runtime = device.AREA+'/bili-awake/'+self.rid
        self.original = b'HOST original executable fixture'
        self.patched = b'HOST patched executable fixture'
        self.files = {
            device.TARGET: self.original,
            '/usr/bin/control_engine': b'HOST control fixture',
            '/usr/bin/zyb_z03_launch.sh': b'HOST launcher fixture',
            device.BASE+'/Z03.patched': self.patched,
            device.BASE+'/app/formal_service.py': b'HOST service fixture',
            device.BASE+'/device_install.py': b'HOST install fixture',
            device.BASE+'/build-result.json': b'{}',
            device.BASE+'/manifest.json': b'{}',
            '/proc/101/exe': self.original}
        self.pins = {name: sha(self.files[name]) for name in device.PINS}
        self.meta = dict(release_id=self.rid, patched_sha256=sha(self.patched))
        self.manifest = {name: dict(bytes=len(self.files[device.BASE+'/'+name]),
                                    sha256=sha(self.files[device.BASE+'/'+name]))
                         for name in ('Z03.patched', 'app/formal_service.py')}
        self.app = dict(pid=101, start='10001', parent=88, exe=device.TARGET,
                        args=[device.TARGET, '-platform', 'wayland'], state='S')
        self.launcher = dict(pid=88, start='9001', parent=1, exe='/bin/sh',
                             args=['/bin/sh', '/usr/bin/zyb_z03_launch.sh'], state='S')
        self.plan = dict(kind='systemd', path=device.UNIT, systemctl='/bin/systemctl',
                         init_exe='/lib/systemd/systemd')
        self.before = dict(app=self.app, launcher=self.launcher, boot='HOST fixture boot',
                           mounts=dict(device='/dev/root', at='/', type='ext4', options=['ro']),
                           startup=self.plan)
        self.directories = set()
        self.calls = []
        self.saved = {}
        self.fd_table = {}
        self.fd_number = 1000
        self.root_rw = False
        self.fsync_failure = fsync_failure
        self.fsync_failed = False
        self.command_failure = command_failure
        self.last_replace = None
        self.stack = contextlib.ExitStack()

    def __enter__(self):
        patches = {
            'verify_payload': lambda: (self.meta, self.manifest, self.rid, self.release, self.runtime),
            'live_gate': lambda *args, **kwargs: copy.deepcopy(self.before),
            'directory': self.directory, 'digest': lambda path: sha(self.files[path]),
            'read': lambda path, limit=1048576: self.files[path],
            'save': self.save, 'command': self.command, 'remount': self.remount,
            'mount_snapshot': self.mount_snapshot,
            'processes': lambda: [copy.deepcopy(self.app)],
            'wait_service': lambda *args: dict(pid=202, start='20002'),
            'restart_ui': lambda *args: dict(pid=303, start='30003')}
        for name, value in patches.items():
            self.stack.enter_context(mock.patch.object(device, name, side_effect=value))
        self.stack.enter_context(mock.patch.object(device, 'PINS', self.pins))
        self.stack.enter_context(mock.patch.object(device.shutil, 'copyfile', side_effect=self.copyfile))
        for name, value in {
            'lexists': lambda path: path in self.files or path in self.directories,
            'exists': lambda path: path in self.files or path in self.directories,
            'islink': lambda path: False}.items():
            self.stack.enter_context(mock.patch.object(device.os.path, name, side_effect=value))
        for name, value in {
            'open': self.open, 'fdopen': self.fdopen, 'fsync': self.fsync,
            'close': self.close, 'replace': self.replace, 'unlink': self.unlink,
            'chmod': lambda *args: self.calls.append(('chmod',)+args),
            'stat': lambda path: types.SimpleNamespace(st_mode=stat.S_IFREG | 0o755),
            'statvfs': lambda path: types.SimpleNamespace(f_bavail=1 << 24, f_frsize=4096)
        }.items():
            self.stack.enter_context(mock.patch.object(device.os, name, side_effect=value, create=True))
        for name, value in (('O_DIRECTORY', 0x10000000), ('O_NOFOLLOW', 0x20000000)):
            self.stack.enter_context(mock.patch.object(device.os, name, value, create=True))
        self.stack.enter_context(mock.patch.object(device.time, 'strftime', return_value='20261014-120000'))
        self.stack.enter_context(mock.patch('builtins.print'))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def directory(self, path, create=False):
        if create:
            self.calls.append(('mkdir', path))
            self.directories.add(path)
        return path

    def save(self, path, value):
        self.saved[path] = copy.deepcopy(value)

    def copyfile(self, source, destination):
        self.files[destination] = self.files[source]
        self.calls.append(('copy', source, destination))

    def open(self, path, flags, mode=0o600):
        self.fd_number += 1
        if flags & device.os.O_DIRECTORY:
            kind = 'directory'
        else:
            kind = 'file'
            if flags & device.os.O_EXCL and path in self.files:
                raise FileExistsError(path)
            self.files[path] = b''
        self.fd_table[self.fd_number] = kind, path
        return self.fd_number

    def fdopen(self, fd, mode):
        fixture = self
        class File(io.BytesIO):
            def fileno(inner):
                return fd
            def close(inner):
                if not inner.closed:
                    fixture.files[fixture.fd_table[fd][1]] = inner.getvalue()
                super().close()
        return File()

    def fsync(self, fd):
        kind, path = self.fd_table[fd]
        if (kind == 'directory' and self.fsync_failure and not self.fsync_failed and
                self.last_replace == device.TARGET and self.files[device.TARGET] == self.patched):
            self.fsync_failed = True
            self.calls.append(('injected-directory-fsync-failure', path))
            raise OSError('HOST injected directory fsync failure after replace')

    def close(self, fd):
        self.calls.append(('close-fd', fd))

    def replace(self, source, destination):
        self.files[destination] = self.files.pop(source)
        self.last_replace = destination
        self.calls.append(('replace', source, destination))

    def unlink(self, path):
        self.files.pop(path, None)
        self.calls.append(('unlink', path))

    def command(self, args, timeout=30):
        self.calls.append(('command', tuple(args)))
        if self.command_failure and self.command_failure in args:
            raise RuntimeError('HOST injected command failure: '+self.command_failure)
        return b''

    def remount(self, writable):
        self.root_rw = writable
        self.calls.append(('remount', writable))

    def mount_snapshot(self):
        return dict(device='/dev/root', at='/', type='ext4',
                    options=['rw' if self.root_rw else 'ro'])


class PackageTests(unittest.TestCase):
    def test_extra_package_file_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='p011-install-package-') as temporary:
            package = pathlib.Path(temporary)
            package_fixture(package)
            host.verify_package(package)
            (package/'app/subprocess.py').write_bytes(b'# unlisted import shadow fixture')
            with self.assertRaisesRegex(ValueError, 'unlisted or missing'):
                host.verify_package(package)

    def test_wrong_hash_is_rejected_before_adb(self):
        with tempfile.TemporaryDirectory(prefix='p011-install-hash-') as temporary:
            package = pathlib.Path(temporary)
            package_fixture(package)
            (package/'Z03.patched').write_bytes(b'fixture candidatz')
            with mock.patch.object(host.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'Package identity differs'):
                    host.verify_package(package)
                run.assert_not_called()

    def test_device_payload_wrong_hash_is_rejected(self):
        manifest = {'Z03.patched': {'bytes': 3, 'sha256': '0'*64}}
        meta = dict(manifest_sha256='a'*64, patched_sha256='0'*64)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(device, 'metadata', return_value=(meta, 'b'*24, 'release', 'runtime')))
            stack.enter_context(mock.patch.object(device, 'directory'))
            stage = device.FORMAL+'/staging/'+'b'*24+'-20261014120000'
            stack.enter_context(mock.patch.object(device, 'BASE', stage))
            stack.enter_context(mock.patch.object(device, 'digest', side_effect=lambda path: 'a'*64 if path.endswith('/manifest.json') else 'f'*64))
            stack.enter_context(mock.patch.object(device, 'read', return_value=json.dumps(manifest).encode()))
            stack.enter_context(mock.patch.object(device, 'regular'))
            stack.enter_context(mock.patch.object(device.os.path, 'getsize', return_value=3))
            atomic = stack.enter_context(mock.patch.object(device, 'atomic'))
            with self.assertRaisesRegex(RuntimeError, 'payload differs'):
                device.verify_payload()
            atomic.assert_not_called()


class TransactionTests(unittest.TestCase):
    def test_initial_live_gate_failure_has_no_system_or_managed_writes(self):
        with VirtualTransaction() as fixture:
            with mock.patch.object(device, 'live_gate', side_effect=RuntimeError('HOST live gate refused')):
                with self.assertRaisesRegex(RuntimeError, 'live gate refused'):
                    device.install()
            self.assertFalse(fixture.calls)
            self.assertEqual(fixture.files[device.TARGET], fixture.original)
            self.assertFalse(fixture.saved)

    def test_replace_then_directory_fsync_failure_rolls_back_exact_original(self):
        with VirtualTransaction(fsync_failure=True) as fixture:
            with self.assertRaisesRegex(OSError, 'directory fsync failure'):
                device.install()
            self.assertTrue(fixture.fsync_failed)
            replacements = [call for call in fixture.calls if call[0] == 'replace' and call[2] == device.TARGET]
            self.assertEqual(len(replacements), 2, 'candidate replace plus exact original rollback')
            self.assertEqual(fixture.files[device.TARGET], fixture.original)
            self.assertNotIn(device.UNIT, fixture.files)
            result = [value for path, value in fixture.saved.items() if path.endswith('/transaction.json')][-1]
            self.assertTrue(result['rolled_back'])
            self.assertTrue(result['root_mount_restored'])
            self.assertNotIn('rollback_error', result)
            self.assertFalse(fixture.root_rw)
            self.assertIn(('remount', True), fixture.calls)
            self.assertEqual([call for call in fixture.calls if call[0] == 'remount'][-1], ('remount', False))

    def test_root_readonly_finally_after_startup_failure(self):
        with VirtualTransaction(command_failure='start') as fixture:
            with self.assertRaisesRegex(RuntimeError, 'command failure: start'):
                device.install()
            self.assertFalse(fixture.root_rw)
            self.assertEqual(fixture.files[device.TARGET], fixture.original)
            self.assertNotIn(device.UNIT, fixture.files)
            result = [value for path, value in fixture.saved.items() if path.endswith('/transaction.json')][-1]
            self.assertTrue(result['root_mount_restored'])
            self.assertTrue(result['rolled_back'])

    def test_root_readonly_restored_on_success(self):
        with VirtualTransaction() as fixture:
            result = device.install()
            self.assertTrue(result['installed'])
            self.assertTrue(result['root_mount_restored'])
            self.assertFalse(fixture.root_rw)
            self.assertEqual(fixture.files[device.TARGET], fixture.patched)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(pid=12345, start='42', exe=device.TARGET, parent=1,
                        args=[device.TARGET, '-platform', 'wayland'], state='S')

    def test_same_pid_changed_executable_is_not_signalled(self):
        current = dict(self.row, exe='/usr/bin/unrelated-process')
        with mock.patch.object(device, 'proc', return_value=current), mock.patch.object(device.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'exec changed; signal refused'):
                device.terminate(self.row)
            kill.assert_not_called()

    def test_reused_pid_is_not_signalled(self):
        with mock.patch.object(device, 'proc', return_value=dict(self.row, start='43')), mock.patch.object(device.os, 'kill') as kill:
            device.terminate(self.row)
            kill.assert_not_called()

    def test_changed_running_hash_is_not_signalled(self):
        with mock.patch.object(device, 'proc', return_value=self.row), mock.patch.object(device, 'digest', return_value='f'*64), mock.patch.object(device.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'running executable differs'):
                device.terminate(self.row, '0'*64)
            kill.assert_not_called()

    def test_restarted_ui_requires_same_vendor_launcher_identity(self):
        new = dict(self.row, pid=12346, start='44', parent=88)
        launcher = dict(pid=88, start='41', exe='/bin/sh',
                        args=['/bin/sh', '/usr/bin/zyb_z03_launch.sh'])
        changed = dict(launcher, start='45')
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(device, 'processes', side_effect=[[self.row], [new]]))
            stack.enter_context(mock.patch.object(device, 'terminate'))
            stack.enter_context(mock.patch.object(device, 'digest', return_value='a'*64))
            stack.enter_context(mock.patch.object(device, 'proc', return_value=changed))
            with self.assertRaisesRegex(RuntimeError, 'vendor launcher identity changed'):
                device.restart_ui('0'*64, 'a'*64, self.row, launcher)


class RestoreTests(unittest.TestCase):
    def seed(self, fixture):
        backup = device.FORMAL+'/backups/'+fixture.rid+'-20261014-120000'
        receipt = dict(release_id=fixture.rid, backup=backup, runtime=fixture.runtime,
                       patched_sha256=sha(fixture.patched), startup=fixture.plan)
        unit = device.startup_bytes(fixture.plan, fixture.release)
        receipt['startup_sha256'] = sha(unit)
        fixture.files[device.FORMAL+'/install-receipt.json'] = json.dumps(receipt).encode('ascii')
        fixture.files[backup+'/Z03.original'] = fixture.original
        fixture.files[device.UNIT] = unit
        fixture.files[device.TARGET] = fixture.patched
        fixture.files['/proc/101/exe'] = fixture.patched
        return backup, receipt

    def rename(self, fixture, source, destination):
        fixture.files[destination] = fixture.files.pop(source)
        fixture.calls.append(('rename', source, destination))

    def restart(self, fixture, *args):
        fixture.calls.append(('stock-ui-confirmed', args))
        fixture.files['/proc/101/exe'] = fixture.original
        fixture.app['exe'] = device.TARGET
        return dict(pid=303, start='30003')

    def test_service_stops_only_after_original_file_and_ui_are_confirmed(self):
        with VirtualTransaction() as fixture:
            self.seed(fixture)
            with mock.patch.object(device, 'restart_ui', side_effect=lambda *args: self.restart(fixture, *args)), mock.patch.object(device.os, 'rename', side_effect=lambda *args: self.rename(fixture, *args)):
                result = device.restore()
            self.assertTrue(result['restored'])
            self.assertTrue(result['root_mount_restored'])
            replaced = next(i for i, call in enumerate(fixture.calls) if call[0] == 'replace' and call[2] == device.TARGET)
            confirmed = next(i for i, call in enumerate(fixture.calls) if call[0] == 'stock-ui-confirmed')
            stopped = next(i for i, call in enumerate(fixture.calls) if call[0] == 'command' and 'stop' in call[1])
            disabled = next(i for i, call in enumerate(fixture.calls) if call[0] == 'command' and 'disable' in call[1])
            receipt_moved = next(i for i, call in enumerate(fixture.calls) if call[0] == 'rename')
            self.assertLess(replaced, confirmed)
            self.assertLess(confirmed, stopped)
            self.assertLess(stopped, disabled)
            self.assertLess(disabled, receipt_moved)
            self.assertEqual(fixture.files[device.TARGET], fixture.original)
            self.assertFalse(fixture.root_rw)

    def test_restore_replace_fsync_failure_keeps_service_then_precise_retry(self):
        with VirtualTransaction() as fixture:
            backup, receipt = self.seed(fixture)
            failed = []
            def fsync(fd):
                kind, path = fixture.fd_table[fd]
                if (not failed and kind == 'directory' and fixture.last_replace == device.TARGET and
                        fixture.files[device.TARGET] == fixture.original):
                    failed.append(True)
                    fixture.calls.append(('restore-fsync-failure', path))
                    raise OSError('HOST restore directory fsync failure after replace')
            with mock.patch.object(device.os, 'fsync', side_effect=fsync), mock.patch.object(device, 'restart_ui', side_effect=lambda *args: self.restart(fixture, *args)) as restart, mock.patch.object(device.os, 'rename', side_effect=lambda *args: self.rename(fixture, *args)):
                with self.assertRaisesRegex(OSError, 'restore directory fsync failure'):
                    device.restore()
                restart.assert_not_called()
                self.assertFalse(any(call[0] == 'command' for call in fixture.calls), 'service stays available during failed UI replacement')
                self.assertIn(device.UNIT, fixture.files)
                self.assertIn(device.FORMAL+'/install-receipt.json', fixture.files)
                self.assertEqual(fixture.files[device.TARGET], fixture.original)
                self.assertEqual(fixture.files['/proc/101/exe'], fixture.patched)
                self.assertFalse(fixture.root_rw)
                self.assertFalse(fixture.saved[backup+'/restore-result.json']['restored'])
                self.assertTrue(fixture.saved[backup+'/restore-result.json']['root_mount_restored'])
                fixture.app['exe'] = device.TARGET+' (deleted)'
                fixture.before['app'] = fixture.app
                expected_app = copy.deepcopy(fixture.before['app'])
                result = device.restore()
                self.assertTrue(result['restored'])
                restart.assert_called_once_with(receipt['patched_sha256'], fixture.pins[device.TARGET], expected_app, fixture.before['launcher'])
                self.assertEqual(len([call for call in fixture.calls if call[0] == 'replace' and call[2] == device.TARGET]), 1, 'retry reuses verified original disk file')
                self.assertNotIn(device.UNIT, fixture.files)
                self.assertNotIn(device.FORMAL+'/install-receipt.json', fixture.files)
                self.assertFalse(fixture.root_rw)

    def test_unknown_disk_or_running_hash_refuses_restore_before_write(self):
        for drift in ('disk', 'running'):
            with self.subTest(drift=drift), VirtualTransaction() as fixture:
                self.seed(fixture)
                fixture.files[device.TARGET if drift == 'disk' else '/proc/101/exe'] = b'HOST unknown executable'
                with self.assertRaisesRegex(RuntimeError, 'restore target drift' if drift == 'disk' else 'restore running UI drift'):
                    device.restore()
                self.assertFalse(fixture.calls)
                self.assertFalse(fixture.saved)
                self.assertIn(device.UNIT, fixture.files)
                self.assertIn(device.FORMAL+'/install-receipt.json', fixture.files)


if __name__ == '__main__':
    unittest.main()
