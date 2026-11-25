"""New-layout HOST checks only; never invoke bootstrap main or ARM binaries."""
import ast
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SystemLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        outputs = list((HERE / 'out').iterdir())
        if len(outputs) != 1:
            raise AssertionError('Exactly one initial layout candidate required')
        cls.output = outputs[0]
        cls.plan = json.loads((cls.output / 'layout-plan.json').read_text())
        cls.manifest = json.loads((cls.output / 'files-manifest.json').read_text())
        cls.release = cls.plan['immutable_release']
        cls.root = cls.output / 'system-files'
        cls.bootstrap = load_file('new_layout_bootstrap_host_inspection', cls.root / cls.release.lstrip('/') / 'system_bootstrap.py')

    def test_new_identity_and_pending_boundaries(self):
        self.assertNotEqual(self.plan['release_id'], self.plan['old_formal_release'])
        self.assertEqual(len(self.plan['release_id']), 24)
        self.assertEqual(self.plan['status'], 'HOST_LAYOUT_CANDIDATE_NOT_IMAGE_NOT_FLASHED')
        for flag in ('original_image_modified', 'old_formal_package_modified', 'image_built',
                     'device_tested', 'adb_invoked', 'userdata_cloned', 'nv_cloned', 'stock_init_files_modified'):
            self.assertIs(self.plan[flag], False)

    def test_manifest_all_member_readbacks_and_no_mutable_payload(self):
        actual = set()
        for path, row in self.manifest.items():
            self.assertTrue(path.startswith((self.release + '/', '/usr/bin/Z03', '/etc/init.d/p011-bili-system',
                                            '/etc/rc5.d/', '/etc/rc0.d/', '/etc/rc6.d/')))
            self.assertFalse(path.startswith(('/mnt/', '/home/', '/var/', '/etc/productinfo/')))
            if row['kind'] == 'file':
                raw = (self.output / row['overlay_file']).read_bytes()
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (row['bytes'], row['sha256']))
                actual.add(path)
            else:
                self.assertEqual(row['kind'], 'symlink')
                self.assertEqual(row['target'], '../init.d/p011-bili-system')
        observed = {'/' + str(p.relative_to(self.root)).replace('\\', '/') for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(observed, actual)

    def test_qrc_result_preserves_name_and_other_399_resources(self):
        qrc = self.plan['qrc']
        self.assertEqual((qrc['resources_verified'], qrc['other_resources_unchanged']), (400, 399))
        self.assertTrue(qrc['settings_entry_unchanged'])
        self.assertTrue(qrc['outside_resource_record_unchanged'])
        self.assertEqual(qrc['changed_resource'], '/ZybQmlFiles/ZybSet/SetUserReport.qml')
        self.assertEqual(qrc['new_feedback_source'], 'file://' + self.release + '/app/FeedbackEntry.qml')

    def test_config_and_qml_runtime_paths_close_without_old_release(self):
        app = self.root / self.release.lstrip('/') / 'app'
        tree = ast.parse((app / 'config.py').read_text())
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
        self.assertEqual(values['APP'], self.release + '/app')
        self.assertEqual(values['MEDIA'], self.release + '/media')
        self.assertEqual(values['REMOTE'], self.plan['runtime'])
        for name in ('config.py', 'Bridge.qml', 'BiliPanel.qml'):
            text = (app / name).read_text()
            self.assertNotIn(self.plan['old_formal_release'], text)
            self.assertIn(self.plan['release_id'], text)
        for relative, digest in values['MEDIA_FILES'].items():
            self.assertEqual(hashlib.sha256((self.root / self.release.lstrip('/') / 'media' / relative).read_bytes()).hexdigest(), digest)

    def test_new_startup_syntax_and_exact_links(self):
        script = self.root / 'etc/init.d/p011-bili-system'
        syntax = subprocess.run(['/bin/sh', '-n', str(script)], capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr.decode())
        text = script.read_text()
        self.assertIn(self.release + '/system_bootstrap.py', text)
        self.assertNotIn('@RELEASE_ID@', text)
        links = {name for name, row in self.manifest.items() if row['kind'] == 'symlink'}
        self.assertEqual(links, {'/etc/rc5.d/S99p011-bili-system', '/etc/rc0.d/K05p011-bili-system',
                                '/etc/rc6.d/K05p011-bili-system'})

    def test_runtime_python35_syntax_and_no_bundled_fonts(self):
        for path in self.root.rglob('*.py'):
            ast.parse(path.read_text(), filename=str(path), feature_version=(3, 5))
        self.assertFalse(any(p.suffix.lower() in ('.ttf', '.otf', '.woff', '.woff2') for p in self.root.rglob('*')))

    def test_mount_gate_accepts_only_unique_writable_p40(self):
        accepted = '/dev/mmcblk0p40 /mnt/data ext4 rw,relatime 0 0\n'
        self.assertTrue(self.bootstrap.mounted_userdata(accepted))
        for raw in ('', accepted + accepted, accepted.replace('p40', 'p29'), accepted.replace('rw,', 'ro,'),
                    accepted.replace('ext4', 'tmpfs'), accepted.replace('/mnt/data', '/mnt/userdata')):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                self.bootstrap.mounted_userdata(raw)

    def test_special_boot_modes_are_excluded(self):
        self.assertTrue(self.bootstrap.normal_boot('console=ttyS1 root=/dev/mmcblk0p29 ro'))
        for mode in ('cali', 'autotest', 'factorytest', 'charge'):
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                self.bootstrap.normal_boot('quiet linuxboot.mode=' + mode + ' other=1')
        with self.assertRaises(RuntimeError):
            self.bootstrap.normal_boot('quiet update_recovery=1')

    def test_first_creation_private_and_existing_user_bytes_preserved(self):
        with tempfile.TemporaryDirectory(dir=HERE / 'evidence') as temporary:
            area = str(pathlib.Path(temporary) / 'own-data')
            paths = self.bootstrap.prepare_directories(area, self.plan['release_id'], os.getuid())
            self.assertEqual(len(paths), 10)
            for path in paths:
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
            owned_fixture = pathlib.Path(area) / 'bili-account/host-fixture.txt'
            owned_fixture.write_bytes(b'HOST fixture only; no real credentials')
            self.bootstrap.prepare_directories(area, self.plan['release_id'], os.getuid())
            self.assertEqual(owned_fixture.read_bytes(), b'HOST fixture only; no real credentials')

    def test_first_creation_rejects_symlink_and_does_not_touch_destination(self):
        with tempfile.TemporaryDirectory(dir=HERE / 'evidence') as temporary:
            base = pathlib.Path(temporary)
            area, outside = base / 'own-data', base / 'outside'
            area.mkdir(mode=0o700)
            outside.mkdir(mode=0o700)
            (area / 'bili-account').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                self.bootstrap.prepare_directories(str(area), self.plan['release_id'], os.getuid())
            self.assertEqual(list(outside.iterdir()), [])

    def test_first_creation_rejects_nonprivate_or_invalid_identity(self):
        with tempfile.TemporaryDirectory(dir=HERE / 'evidence') as temporary:
            area = pathlib.Path(temporary) / 'own-data'
            area.mkdir(mode=0o755)
            with self.assertRaises(RuntimeError):
                self.bootstrap.prepare_directories(str(area), self.plan['release_id'], os.getuid())
            with self.assertRaises(RuntimeError):
                self.bootstrap.prepare_directories(str(area), '../escape', os.getuid())

    def test_process_ownership_and_reused_pid_never_signalled(self):
        row = dict(pid=1234, start=b'200', state=b'S', uid=0,
                   exe=os.path.realpath(self.bootstrap.PYTHON),
                   args=[self.bootstrap.PYTHON.encode(), b'-B', self.bootstrap.SERVICE.encode()])
        self.assertTrue(self.bootstrap.ours(row))
        for key, value in (('pid', 1), ('uid', 1000), ('exe', '/bin/sh'), ('state', b'D'),
                           ('args', [b'python3', b'-B', b'/unrelated.py'])):
            altered = dict(row, **{key: value})
            self.assertFalse(self.bootstrap.ours(altered))
        with mock.patch.object(self.bootstrap, 'process', return_value=dict(row, start=b'201')), \
                mock.patch.object(self.bootstrap.os, 'kill') as kill:
            self.bootstrap.stop_row(row)
            kill.assert_not_called()
        with mock.patch.object(self.bootstrap, 'process', return_value=dict(row, exe='/bin/sh')), \
                mock.patch.object(self.bootstrap.os, 'kill') as kill:
            with self.assertRaises(RuntimeError):
                self.bootstrap.stop_row(row)
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
