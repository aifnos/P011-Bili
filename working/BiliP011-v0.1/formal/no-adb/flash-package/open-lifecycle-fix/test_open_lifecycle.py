"""HOST fault injection only: DLL loading, USB inventory and serial I/O mocked."""
import ctypes
import gzip
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
PACK = HERE.parent
sys.path[:0] = [str(HERE), str(PACK / 'out/P011-Bili-NoADB-v4-ready-20261014/app')]
import engine
import flash
win = engine.win
sys.path.extend([str(PACK), str(PACK / 'reenum-fix'), str(PACK / 'initial-ready-fix'), str(PACK.parent)])
from test_win32_transport import FakeAPI, TransportTests, TransportAdditionalTests
from test_reenum import OLD, NEW, Clock, ReenumerationTests
from test_reenum import ScriptedSerial, reply
from test_initial_ready import InitialReadyTests
from test_package import PackageTests


class FaultAPI(FakeAPI):
    def __init__(self, stage, code=433, occurrence=1, persistent=False, cleanup_fail=False):
        super().__init__()
        self.stage, self.code, self.occurrence = stage, code, occurrence
        self.persistent, self.cleanup_fail = persistent, cleanup_fail
        self.hits = 0

    def __getattribute__(self, name):
        original = super().__getattribute__(name)
        if name not in ('CreateFileW', 'GetCommState', 'SetCommState', 'SetCommTimeouts',
                        'ClearCommError', 'WriteFile', 'CloseHandle'):
            return original
        def call(*args):
            if name == 'CloseHandle' and self.cleanup_fail:
                self.closed.append(args[0])
                ctypes.set_last_error(6)
                return False
            if name == self.stage:
                self.hits += 1
                if self.hits == self.occurrence or self.persistent and self.hits >= self.occurrence:
                    ctypes.set_last_error(self.code)
                    return win.INVALID_HANDLE_VALUE if name == 'CreateFileW' else False
            return original(*args)
        return call


class OpenLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for p in (patch.object(engine.time, 'monotonic', self.clock.monotonic),
                  patch.object(engine.time, 'sleep', self.clock.sleep)):
            p.start()
            self.addCleanup(p.stop)

    def session(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        session = engine.Session(folder.name)
        self.addCleanup(session.close)
        return session

    def run_open(self, session, api, **kwargs):
        with patch.object(win, 'inventory', return_value=[OLD]), patch.object(win, '_get_api', return_value=api):
            session.open(OLD, send_mode=True, **kwargs)

    def test_433_at_every_open_api_closes_failed_handle_then_sends_mode_once(self):
        for stage in ('CreateFileW', 'GetCommState', 'SetCommState', 'SetCommTimeouts', 'ClearCommError'):
            with self.subTest(api=stage):
                session, api = self.session(), FaultAPI(stage)
                self.run_open(session, api)
                self.assertEqual(session.state['open_attempts'], 2)
                self.assertEqual(session.state['port_open_retries'], 1)
                self.assertEqual(session.state['mode_attempts'], 1)
                self.assertFalse(session.state['protocol_retry'])
                self.assertEqual([r[1] for r in api.calls if r[0] == 'write'], [engine.MODE])
                self.assertEqual(len(api.closed), int(stage != 'CreateFileW'))
                self.assertEqual(session.state['last_open_failure']['api'], stage)
                self.assertEqual(session.state['last_open_failure']['winerror'], 433)
                self.assertTrue(session.state['last_open_failure']['handle_closed'])

    def test_device_not_connected_1167_is_bounded_and_recoverable(self):
        session, api = self.session(), FaultAPI('GetCommState', code=1167)
        self.run_open(session, api)
        self.assertEqual(session.state['mode_attempts'], 1)
        self.assertEqual(session.state['open_attempts'], 2)

    def test_access_denied_and_unknown_errors_are_not_retried(self):
        for code in (5, 87, 2, 31):
            with self.subTest(code=code):
                session, api = self.session(), FaultAPI('CreateFileW', code=code)
                with self.assertRaises(OSError) as caught:
                    self.run_open(session, api)
                self.assertEqual(caught.exception.winerror, code)
                self.assertEqual(session.state['open_attempts'], 1)
                self.assertEqual(session.attempts, 0)

    def test_persistent_disappearance_keeps_absolute_deadline_and_zero_tx(self):
        session, api = self.session(), FaultAPI('GetCommState', persistent=True)
        with self.assertRaisesRegex(RuntimeError, '打开超时'):
            self.run_open(session, api, deadline=.1)
        self.assertLess(self.clock.now, .121)
        self.assertGreater(session.state['open_attempts'], 1)
        self.assertEqual(len(api.closed), session.state['open_attempts'])
        self.assertEqual(session.attempts, 0)
        self.assertTrue(session.state['host_handle_closed'])

    def test_failed_cleanup_is_reported_and_prevents_retry(self):
        session, api = self.session(), FaultAPI('GetCommState', cleanup_fail=True)
        with self.assertRaises(OSError) as caught:
            self.run_open(session, api)
        self.assertEqual(caught.exception.winerror, 433)
        self.assertEqual(caught.exception.cleanup_winerror, 6)
        self.assertTrue(session.state['cleanup_uncertain'])
        self.assertFalse(session.state['host_handle_closed'])
        self.assertEqual(session.state['open_attempts'], 1)
        self.assertEqual(session.attempts, 0)

    def test_disappearance_after_open_before_mode_is_recovered_without_duplicate_tx(self):
        session, api = self.session(), FaultAPI('ClearCommError', occurrence=2)
        self.run_open(session, api)
        self.assertEqual(session.state['open_attempts'], 2)
        self.assertEqual(len(api.closed), 1)
        self.assertEqual(session.attempts, 1)
        self.assertEqual([r[1] for r in api.calls if r[0] == 'write'], [engine.MODE])

    def test_mode_write_error_or_short_write_consumes_attempt_and_never_reopens(self):
        for short in (False, True):
            with self.subTest(short=short):
                session = self.session()
                api = FakeAPI() if short else FaultAPI('WriteFile')
                api.short_write = short
                with self.assertRaises((OSError, RuntimeError)):
                    self.run_open(session, api)
                self.assertEqual(session.state['open_attempts'], 1)
                self.assertEqual(session.state['mode_attempts'], 1)
                self.assertTrue(session.failed)
                self.assertEqual(session.state['port_open_retries'], 0)

    def test_recovery_requires_same_single_download_identity(self):
        for rows in ([dict(OLD, id='DIFFERENT')], [OLD, NEW], [dict(OLD, pid='4064')]):
            with self.subTest(rows=rows):
                session, api = self.session(), FaultAPI('CreateFileW')
                with patch.object(win, 'inventory', side_effect=[[OLD], rows]), patch.object(win, '_get_api', return_value=api):
                    with self.assertRaises(RuntimeError):
                        session.open(OLD, send_mode=True)
                self.assertEqual(session.state['open_attempts'], 1)
                self.assertEqual(session.attempts, 0)

    def test_reenumerated_same_device_uses_new_port_after_failed_open(self):
        session, api = self.session(), FaultAPI('CreateFileW')
        with patch.object(win, 'inventory', side_effect=[[OLD], [NEW], [NEW], [NEW], [NEW]]), \
                patch.object(win, '_get_api', return_value=api):
            session.open(OLD, send_mode=True)
        self.assertEqual(session.node, NEW)
        self.assertEqual([r[1] for r in api.calls if r[0] == 'open'], ['\\\\.\\COM15'])
        self.assertEqual(session.state['mode_attempts'], 1)

    def test_post_mode_open_recovers_without_resending_mode_or_sync(self):
        session, api = self.session(), FaultAPI('SetCommState')
        session.state['mode_attempts'], session.attempts = 1, 1
        with patch.object(win, 'inventory', return_value=[NEW]), patch.object(win, '_get_api', return_value=api):
            session.open(NEW)
        self.assertEqual(session.state['open_attempts'], 2)
        self.assertEqual(session.state['mode_attempts'], 1)
        self.assertEqual(session.state['sync_attempts'], 0)
        self.assertFalse(any(r[0] == 'write' for r in api.calls))

    def test_retry_is_forbidden_after_sync_or_storage_or_failed_protocol(self):
        for key, value in [('sync_attempts', 1), ('write_started', True), ('fdl2_ready', True)]:
            with self.subTest(key=key):
                session = self.session()
                session.state[key] = value
                with patch.object(win, '_get_api', side_effect=AssertionError('Must not call API')):
                    with self.assertRaisesRegex(RuntimeError, '禁止重新打开'):
                        session.open(OLD, send_mode=True)
                self.assertEqual(session.state['open_attempts'], 0)
        session = self.session()
        session.failed = True
        with self.assertRaisesRegex(RuntimeError, '禁止重新打开'):
            session.open(OLD, send_mode=True)

    def test_full_connect_recovers_both_open_stages_with_one_mode_and_one_sync(self):
        session = self.session()
        mode_serial = ScriptedSerial([(engine.MODE, b'')])
        stages = [('CONNECT_CRC16', 0x80, b''), ('EXEC_BUILTIN_CRC16', 0x80, b''),
            ('SYNC_SUM16_VERSION', 0x81, engine.codec.AUTOD_PAYLOAD), ('CONNECT_SUM16', 0x80, b''),
            ('KEEP_CHARGE_SUM16', 0x80, b''), ('EXEC_BUILTIN_SUM16', 0x96, engine.codec.OBSERVED_CAPABILITY_PAYLOAD),
            ('DISABLE_TRANSCODE_SUM16', 0x80, b'')]
        script = [(b'\x7e', reply(0x81, engine.codec.AUTOD_PAYLOAD, engine.codec.CRC16, True))]
        script += [(engine.codec.build_fixed(name), reply(code, data,
            engine.codec.CRC16 if name.endswith('CRC16') else engine.codec.SUM16, True)) for name, code, data in stages]
        data_serial = ScriptedSerial(script)
        count = 0
        def rows():
            nonlocal count
            count += 1
            if count == 1:
                return []
            return [NEW if session.state['mode_attempts'] else OLD]
        def open_node(node):
            attempt = session.state['open_attempts']
            if attempt in (1, 3):
                exc = ctypes.WinError(433)
                exc.api_stage, exc.open_handle_closed = 'CreateFileW', True
                raise exc
            return mode_serial if attempt == 2 else data_serial
        with patch.object(win, 'inventory', side_effect=rows), patch.object(win, 'open_download', side_effect=open_node):
            session.connect()
        self.assertEqual(session.state['open_attempts'], 4)
        self.assertEqual(session.state['port_open_retries'], 2)
        self.assertEqual(session.state['mode_attempts'], 1)
        self.assertEqual(session.state['sync_attempts'], 1)
        self.assertEqual(mode_serial.calls, [engine.MODE])
        self.assertEqual(data_serial.script, [])
        self.assertTrue(session.state['fdl2_ready'])
        self.assertFalse(session.state['write_started'])

    def test_blocking_open_past_deadline_does_not_send_mode(self):
        session = self.session()
        serial = ScriptedSerial([(engine.MODE, b'')])
        def delayed(node):
            self.clock.now = 1
            return serial
        with patch.object(win, 'open_download', side_effect=delayed):
            with self.assertRaisesRegex(RuntimeError, '未发送 MODE'):
                session.open(OLD, send_mode=True, deadline=.1)
        self.assertEqual(serial.calls, [])
        self.assertEqual(session.state['mode_attempts'], 0)
        session.close_handle()
        self.assertTrue(serial.closed)

    def test_initial_readiness_and_open_share_deadline(self):
        session, api = self.session(), FaultAPI('GetCommState', persistent=True)
        count = 0
        def rows():
            nonlocal count
            count += 1
            if count == 1:
                return []
            return [dict(OLD, started=False)] if self.clock.now < .08 else [OLD]
        with patch.object(win, 'inventory', side_effect=rows), patch.object(win, '_get_api', return_value=api):
            initial = session.wait_initial_ready(1, .1)
            with self.assertRaisesRegex(RuntimeError, '打开超时'):
                session.open(initial, send_mode=True, deadline=session.initial_open_deadline)
        self.assertLess(self.clock.now, .121)
        self.assertEqual(session.attempts, 0)

    def test_metadata_433_during_initial_observation_is_bounded(self):
        session = self.session()
        with patch.object(win, 'inventory', side_effect=[[], ctypes.WinError(433), [OLD]]), \
                patch.object(win, '_get_api', side_effect=AssertionError('Observation only')):
            self.assertEqual(session.wait_initial_ready(1, .2), OLD)
        self.assertEqual(session.attempts, 0)

    def test_metadata_433_does_not_prove_mode_transition(self):
        session = self.session()
        session.node, session.state['mode_attempts'], session.attempts = OLD, 1, 1
        count = 0
        def rows():
            nonlocal count
            count += 1
            if count == 1:
                raise ctypes.WinError(433)
            return [OLD]
        with patch.object(win, 'inventory', side_effect=rows):
            with self.assertRaisesRegex(RuntimeError, '重枚举超时'):
                session.wait_mode_reenumeration(.2)
        self.assertEqual(session.state['open_attempts'], 0)

    def test_traceback_and_api_are_retained_before_any_partition_command(self):
        session = self.session()
        failure = ctypes.WinError(433)
        failure.api_stage = 'GetCommState'
        with patch.object(flash, 'verify_package'), patch.object(session, 'connect', side_effect=failure):
            result = flash.execute('install', session.folder, session_factory=lambda output: session)
        self.assertEqual(result['winerror'], 433)
        self.assertEqual(result['error_api'], 'GetCommState')
        self.assertFalse(result['transport']['write_started'])
        self.assertIn('Traceback', (session.folder / 'exception.txt').read_text(encoding='utf-8'))
        self.assertEqual(gzip.open(session.folder / 'wire.tx.raw.gz', 'rb').read(), b'')


def main():
    suite = unittest.TestSuite()
    # Retest changed native opening/identity, initial acquisition, reenumeration
    # and the affected full connection. Reuse storage regression evidence except
    # for the two no-replay checks directly relevant to the new recovery boundary.
    for cls in (OpenLifecycleTests, TransportTests, TransportAdditionalTests, InitialReadyTests, ReenumerationTests):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    for name in ('test_short_write_cannot_retry', 'test_nack_and_duplicate_response_stop'):
        suite.addTest(PackageTests(name))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    report = dict(scope='HOST_MOCKED_NO_DLL_NO_PNP_NO_SERIAL_NO_TX', tests=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors), passed=result.wasSuccessful(),
                  files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},
                  system_device_acceptance=False, real_433_recovery_verified=False)
    (HERE / 'host-tests-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
