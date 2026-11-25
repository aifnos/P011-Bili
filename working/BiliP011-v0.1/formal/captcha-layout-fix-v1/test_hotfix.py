"""Host tests exercise the production five-file transaction, including faults."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
loader = importlib.util.spec_from_file_location('captcha_host_patch', HERE / 'run_patch.py')
HOST = importlib.util.module_from_spec(loader)
loader.loader.exec_module(HOST)
DEVICE_SOURCE = (HERE / 'device_patch.py').read_text(encoding='utf-8')


class PatchTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(prefix='p011-captcha-host-')
        self.addCleanup(temp.cleanup)
        area = Path(temp.name)
        formal = area / 'formal'
        base = area / 'base'
        release = formal / 'releases' / HOST.RELEASE_ID
        runtime = area / 'runtime'
        original_backup = formal / 'backups' / (HOST.RELEASE_ID + '-host-test')
        for directory in (base / 'app', release, runtime, original_backup):
            directory.mkdir(parents=True)
        original = b'original-z03-host-fixture'
        patched = b'patched-z03-host-fixture'
        target = area / 'Z03'
        target.write_bytes(patched)
        (original_backup / 'Z03.original').write_bytes(original)
        startup = area / 'startup'
        startup.write_bytes(b'unchanged-startup')
        old_sources = {name: ('// old ' + name).encode() for name in HOST.QML_NAMES}
        for name, raw in old_sources.items():
            (base / 'app' / name).write_bytes(raw)
        (base / 'app' / 'unchanged.py').write_bytes(b'unchanged-library')
        source = {'client/' + name: HOST.spec(raw) for name, raw in old_sources.items()}
        (base / 'source-manifest.json').write_bytes(HOST.canonical(source))
        manifest = {'app/' + name: HOST.spec(raw) for name, raw in old_sources.items()}
        manifest['app/unchanged.py'] = HOST.spec(b'unchanged-library')
        # Match the fixed release identity for assembly; point the real device
        # verifier at matching fixture bytes afterwards, without weakening it.
        manifest['Z03.patched'] = HOST.spec(patched)
        manifest['source-manifest.json'] = HOST.spec((base / 'source-manifest.json').read_bytes())
        (base / 'manifest.json').write_bytes(HOST.canonical(manifest))
        meta = dict(release_id=HOST.RELEASE_ID, patched_sha256=HOST.PATCHED_SHA,
                    source_identity_sha256=HOST.RELEASE_ID + 'c' * 40,
                    manifest_sha256=HOST.sha((base / 'manifest.json').read_bytes()),
                    remote=str(runtime), patch_revision_sha256='preserved-playback-revision')
        (base / 'build-result.json').write_bytes(HOST.canonical(meta))
        new_sources = {name: ('// new ' + name + '\nItem {}').encode()
                       for name in HOST.QML_NAMES}
        patch, changes = HOST.build_changes(base, new_sources, DEVICE_SOURCE.encode())
        patch['patched_sha256'] = HOST.sha(patched)
        # The fixture metadata uses the fixture executable, while production
        # metadata and PATCH both retain the actual pinned executable hash.
        for root, state in ((base, 'before'),):
            value = json.loads((root / 'build-result.json').read_bytes())
            value['patched_sha256'] = HOST.sha(patched)
            raw = HOST.canonical(value)
            (root / 'build-result.json').write_bytes(raw)
            patch[state]['build-result.json'] = HOST.spec(raw)
        new_meta = json.loads(changes['build-result.json'])
        new_meta['patched_sha256'] = HOST.sha(patched)
        changes['build-result.json'] = HOST.canonical(new_meta)
        patch['after']['build-result.json'] = HOST.spec(changes['build-result.json'])
        shutil.copytree(base, release, dirs_exist_ok=True)
        stage = formal / 'ui-patches' / patch['revision_sha256'][:24]
        for name, raw in changes.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        live = dict(boot='host-boot', mounts={'options': ['ro']},
                    startup=dict(kind='sysv', path=str(startup)),
                    app=dict(pid=100, parent=99, start='1000', exe=str(target), args=['Z03']),
                    launcher=dict(pid=99, parent=1, start='990', exe='sh', args=['launch']))
        receipt = dict(installed=True, release_id=HOST.RELEASE_ID,
                       patched_sha256=HOST.sha(patched), backup=original_backup.as_posix(),
                       startup=live['startup'], startup_sha256=HOST.sha(startup.read_bytes()),
                       playback_patch=dict(revision='preserve-this'))
        receipt_path = formal / 'install-receipt.json'
        receipt_path.write_bytes(HOST.canonical(receipt))
        (runtime / 'lease.json').write_bytes(HOST.canonical(dict(session=HOST.RELEASE_ID, active=False)))
        old_receipt = receipt_path.read_bytes()
        faults = dict(name=None, after_replace=False, seen=False)
        writes = []

        def require(value, reason):
            if not value:
                raise RuntimeError(reason)

        def read(path, limit=1048576):
            raw = Path(path).read_bytes()
            require(len(raw) <= limit, 'read limit')
            return raw

        def digest(path):
            return HOST.sha(Path(path).read_bytes())

        def atomic(path, raw, mode=0o600):
            path = Path(path)
            failure_name = faults['name']
            failure_path = (receipt_path if failure_name == 'install-receipt.json'
                            else release / failure_name if failure_name else None)
            new_bytes = (raw != old_receipt if failure_name == 'install-receipt.json'
                         else raw == changes.get(failure_name))
            trigger = (failure_name is not None and path == failure_path and
                       new_bytes and not faults['seen'])
            if trigger and not faults['after_replace']:
                faults['seen'] = True
                raise OSError('synthetic pre-replace failure')
            path.write_bytes(raw)
            writes.append(str(path))
            os.chmod(path, mode)
            if trigger:
                faults['seen'] = True
                raise OSError('synthetic post-replace failure')

        def regular(path):
            require(Path(path).is_file() and not Path(path).is_symlink(), 'regular file')

        def directory(path, create=False):
            if create:
                Path(path).mkdir(parents=True, exist_ok=True)
            require(Path(path).is_dir() and not Path(path).is_symlink(), 'directory')

        env = dict(os=os, stat=stat, json=json, hashlib=hashlib, re=__import__('re'),
            BASE=release.as_posix(), FORMAL=formal.as_posix(), TARGET=str(target), PATCH=patch,
            PINS={str(target):HOST.sha(original)}, require=require, read=read, digest=digest,
            atomic=atomic, save=lambda p,v:atomic(p, HOST.canonical(v)),
            directory=directory, regular=regular,
            metadata=lambda:(json.loads((release / 'build-result.json').read_bytes()),
                             HOST.RELEASE_ID,release.as_posix(),runtime.as_posix()),
            live_gate=lambda *a:copy.deepcopy(live), service_rows=lambda p:[{}],
            processes=lambda:[], transaction_lock=lambda:os.open(area / 'lock', os.O_WRONLY | os.O_CREAT, 0o600))
        exec(compile(DEVICE_SOURCE, 'device_patch.py', 'exec'), env)
        return dict(env=env, release=release, runtime=runtime, patch=patch, changes=changes,
                    receipt_path=receipt_path, old_receipt=old_receipt, base=base,
                    backup=original_backup / ('captcha-layout-' + patch['revision_sha256'][:24]),
                    faults=faults, writes=writes)

    def apply(self, fixture):
        with contextlib.redirect_stdout(io.StringIO()):
            return fixture['env']['qml_apply']()

    def assert_unchanged(self, fixture):
        for name, row in fixture['patch']['before'].items():
            self.assertEqual(HOST.spec((fixture['release'] / name).read_bytes()), row)
        self.assertEqual(fixture['receipt_path'].read_bytes(), fixture['old_receipt'])

    def test_python35_syntax(self):
        ast.parse(DEVICE_SOURCE, feature_version=(3,5))

    def test_commit_full_chain_and_preserve_playback_patch(self):
        f = self.fixture()
        self.assertTrue(f['env']['qml_inspect']()['ready'])
        result = self.apply(f)
        self.assertTrue(result['applied'])
        self.assertTrue(f['env']['qml_verify']()['verified'])
        receipt = json.loads(f['receipt_path'].read_bytes())
        self.assertEqual(receipt['playback_patch'], {'revision':'preserve-this'})
        for name, row in f['patch']['after'].items():
            self.assertEqual(HOST.spec((f['release'] / name).read_bytes()), row)

    def test_every_write_rolls_back_before_or_after_replacement(self):
        for name in HOST.ORDER + ['install-receipt.json']:
            for after_replace in (False, True):
                with self.subTest(name=name, after_replace=after_replace):
                    f = self.fixture()
                    f['faults'].update(name=name, after_replace=after_replace)
                    with self.assertRaises(OSError):
                        self.apply(f)
                    self.assert_unchanged(f)
                    journal = json.loads((f['backup'] / 'transaction.json').read_bytes())
                    self.assertTrue(journal['rolled_back'])
                    self.assertFalse(journal['applied'])

    def test_real_v8_package_host_verification_and_provenance(self):
        reader = HOST.load_reader(HOST.BASE_PACKAGE / 'install_formal.py')
        meta, listed = reader.verify_package(HOST.BASE_PACKAGE)
        self.assertEqual(meta['release_id'], HOST.RELEASE_ID)
        sources = {name:(HOST.BASE_PACKAGE / 'app' / name).read_bytes() + b'\n// Host-only fixture\n'
                   for name in HOST.QML_NAMES}
        patch, changes = HOST.build_changes(HOST.BASE_PACKAGE, sources, DEVICE_SOURCE.encode())
        self.assertEqual(patch['order'], HOST.ORDER)
        manifest = json.loads(changes['manifest.json'])
        new_meta = json.loads(changes['build-result.json'])
        self.assertEqual(new_meta['manifest_sha256'], HOST.sha(changes['manifest.json']))
        self.assertEqual(new_meta['patched_sha256'], meta['patched_sha256'])
        self.assertEqual(new_meta['patch_revision_sha256'], meta['patch_revision_sha256'])
        for name, raw in changes.items():
            if name not in ('manifest.json', 'build-result.json'):
                self.assertEqual(manifest[name], HOST.spec(raw))

    def test_unchanged_payload_drift_refused_before_backup(self):
        f = self.fixture()
        (f['release'] / 'app/unchanged.py').write_bytes(b'drift')
        with self.assertRaisesRegex(RuntimeError, 'payload drift'):
            self.apply(f)
        self.assertEqual(f['writes'], [])
        self.assertFalse(f['backup'].exists())

    def test_active_session_refused_before_write(self):
        f = self.fixture()
        (f['runtime'] / 'lease.json').write_bytes(HOST.canonical(dict(session=HOST.RELEASE_ID, active=True)))
        self.assertFalse(f['env']['qml_inspect']()['ready'])
        with self.assertRaisesRegex(RuntimeError, 'session cleanup'):
            self.apply(f)
        self.assertEqual(f['writes'], [])
        self.assert_unchanged(f)

    def test_existing_backup_left_untouched(self):
        f = self.fixture()
        f['backup'].mkdir()
        journal = f['backup'] / 'transaction.json'
        journal.write_bytes(b'old transaction evidence')
        with self.assertRaisesRegex(RuntimeError, 'prior UI patch transaction'):
            self.apply(f)
        self.assertEqual(journal.read_bytes(), b'old transaction evidence')
        self.assertEqual(f['writes'], [])

    def test_verify_rejects_later_payload_drift(self):
        f = self.fixture()
        self.apply(f)
        (f['release'] / 'app/unchanged.py').write_bytes(b'later drift')
        with self.assertRaisesRegex(RuntimeError, 'payload drift'):
            f['env']['qml_verify']()

    def test_prepare_assembly_rejects_extra_qml(self):
        f = self.fixture()
        meta = json.loads((f['base'] / 'build-result.json').read_bytes())
        meta['patched_sha256'] = HOST.PATCHED_SHA
        (f['base'] / 'build-result.json').write_bytes(HOST.canonical(meta))
        sources = {name:b'// changed Item {}' for name in HOST.QML_NAMES}
        sources['BiliInput.qml'] = b'forbidden'
        with self.assertRaisesRegex(AssertionError, 'two fixed QML'):
            HOST.build_changes(f['base'], sources, DEVICE_SOURCE.encode())


if __name__ == '__main__':
    unittest.main()
