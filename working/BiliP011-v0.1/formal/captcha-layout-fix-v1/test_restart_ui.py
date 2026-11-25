"""Exercise restart checks using process and file-state fixtures on the host."""
import ast
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('captcha_ui_restart', HERE / 'restart_ui.py')
RESTART = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RESTART)


class RestartTests(unittest.TestCase):
    def fixture(self, idle=True, payload=69, drift=None):
        temp = tempfile.TemporaryDirectory(prefix='p011-ui-restart-host-')
        self.addCleanup(temp.cleanup)
        area = Path(temp.name)
        original = dict(boot='same-boot', mounts={'options':['ro']}, startup={'kind':'sysv'},
                        app=dict(pid=100, parent=99, start='1000', exe='Z03', args=['Z03']),
                        launcher=dict(pid=99, parent=1, start='990', exe='sh', args=['launch']))
        current = copy.deepcopy(original)
        service = dict(pid=20, parent=1, start='200', exe='python3', args=['formal_service.py'])
        calls = []
        switched = [False]
        def require(value, message):
            if not value:
                raise RuntimeError(message)
        def gate(require_idle=False):
            if require_idle:
                require(idle, 'session is active')
            return {},copy.deepcopy(current),'runtime',idle
        def verify():
            require(drift != 'missing_patch_receipt', 'UI patch receipt differs')
            return dict(payload=dict(payload_files_verified=payload,manifest_sha256='manifest'))
        def restart(old_hash, expected_hash, app, launcher):
            calls.append((old_hash,expected_hash,copy.deepcopy(app),copy.deepcopy(launcher)))
            switched[0] = True
            current['app']['pid'] = 101
            current['app']['start'] = '1001'
            if drift == 'same_pid':
                current['app']['pid'] = original['app']['pid']
            if drift == 'same_start':
                current['app']['start'] = original['app']['start']
            if drift == 'launcher':
                current['launcher']['start'] = 'other'
            if drift == 'mount':
                current['mounts'] = {'options':['rw']}
            return copy.deepcopy(current['app'])
        env = dict(os=os, PATCH=dict(revision_sha256='b'*64,patched_sha256='patched',
                                    manifest_keys=['file-%d'%i for i in range(69)]),
                   PINS={'/usr/bin/Z03':'unused-stock-pin','/usr/bin/control_engine':'engine'},
                   FORMAL='formal',BASE='release',require=require,qml_verify=verify,qml_gate=gate,
                   read=lambda p:(b'changed' if switched[0] and drift=='receipt' else b'receipt'),
                   digest=lambda p:('changed' if switched[0] and drift=='stock_hash' and p=='/usr/bin/control_engine'
                                    else 'patched' if '/proc/' in p or p=='/usr/bin/Z03' else 'engine'),
                   service_rows=lambda p:[dict(service,start='changed') if switched[0] and drift=='service' else dict(service)],
                   restart_ui=restart,
                   transaction_lock=lambda:os.open(area/'lock',os.O_WRONLY|os.O_CREAT,0o600))
        exec(compile(RESTART.DEVICE_RESTART,'device_restart','exec'), env)
        return env,calls

    def run_restart(self, env):
        with contextlib.redirect_stdout(io.StringIO()):
            return env['restart_verified_ui']()

    def test_python35_device_syntax(self):
        ast.parse(RESTART.DEVICE_RESTART,feature_version=(3,5))

    def test_verified_restart_and_pinned_process_arguments(self):
        env,calls = self.fixture()
        result = self.run_restart(env)
        self.assertTrue(result['ui_restarted'])
        self.assertTrue(result['root_readonly'])
        self.assertEqual(result['payload_files_verified'],69)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0:2],('patched','patched'))
        self.assertEqual(calls[0][2]['pid'],100)
        self.assertEqual(calls[0][3]['pid'],99)

    def test_active_session_rejected_before_restart(self):
        env,calls = self.fixture(idle=False)
        with self.assertRaisesRegex(RuntimeError,'session is active'):
            self.run_restart(env)
        self.assertEqual(calls,[])

    def test_wrong_payload_count_rejected_before_restart(self):
        env,calls = self.fixture(payload=68)
        with self.assertRaisesRegex(RuntimeError,'payload verification incomplete'):
            self.run_restart(env)
        self.assertEqual(calls,[])

    def test_missing_patch_receipt_rejected_before_restart(self):
        env,calls = self.fixture(drift='missing_patch_receipt')
        with self.assertRaisesRegex(RuntimeError,'UI patch receipt differs'):
            self.run_restart(env)
        self.assertEqual(calls,[])

    def test_process_filesystem_and_receipt_drift_rejected_after_restart(self):
        for drift in ('same_pid','same_start','launcher','mount','stock_hash','receipt','service'):
            with self.subTest(drift=drift):
                env,calls = self.fixture(drift=drift)
                with self.assertRaises(RuntimeError):
                    self.run_restart(env)
                self.assertEqual(len(calls),1)


if __name__ == '__main__':
    unittest.main()
