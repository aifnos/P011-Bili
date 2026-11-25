"""Focused HOST tests for actual MODE RX handoff and invisible PnP transitions."""
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
sys.path[:0] = [str(HERE), str(PACK / 'out/P011-Bili-NoADB-v5-open-20261014/app')]
import engine
import flash
sys.path.extend([str(PACK / 'open-lifecycle-fix'), str(PACK / 'reenum-fix'), str(PACK)])
from test_open_lifecycle import OpenLifecycleTests
from test_reenum import Clock, OLD, NEW, ScriptedSerial, reply, ReenumerationTests


class ModeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = engine.Session(self.temp.name)
        self.addCleanup(self.session.close)
        self.clock = Clock()
        for p in (patch.object(engine.time, 'monotonic', self.clock.monotonic), patch.object(engine.time, 'sleep', self.clock.sleep)):
            p.start()
            self.addCleanup(p.stop)

    def mode_sent(self):
        self.session.node = OLD
        self.session.state['mode_attempts'] = 1
        self.session.attempts = 1
        self.session.mode_sent_at = 0

    def test_unchanged_ready_node_authorizes_only_probe_after_settle(self):
        self.mode_sent()
        with patch.object(engine.win, 'inventory', return_value=[OLD]):
            self.assertEqual(self.session.wait_mode_reenumeration(3), OLD)
        self.assertGreaterEqual(self.clock.now, 1.8)
        self.assertLess(self.clock.now, 1.85)
        self.assertFalse(self.session.state['mode_pnp_transition_observed'])
        self.assertEqual(self.session.state['sync_attempts'], 0)
        self.assertFalse(self.session.state.get('fdl2_ready', False))

    def test_metadata_gap_is_not_reported_as_transition(self):
        self.mode_sent()
        first = True
        def rows():
            nonlocal first
            if first:
                first = False
                raise ctypes.WinError(433)
            return [OLD]
        with patch.object(engine.win, 'inventory', side_effect=rows):
            self.session.wait_mode_reenumeration(3)
        self.assertFalse(self.session.state['mode_pnp_transition_observed'])

    def test_absent_device_stops_without_sync(self):
        self.mode_sent()
        with patch.object(engine.win, 'inventory', return_value=[]), self.assertRaisesRegex(RuntimeError, '就绪超时'):
            self.session.wait_mode_reenumeration(.3)
        self.assertEqual(self.session.state['sync_attempts'], 0)

    def passive(self, chunks, old=True):
        self.mode_sent()
        serial = ScriptedSerial([])
        serial.buffer = chunks
        self.session.serial = serial
        with patch.object(self.session, 'ensure_identity'):
            self.session.collect_mode_reply(.08, old_handle=old)
        return serial

    def test_fragmented_mode_echo_and_version_are_retained(self):
        data = engine.MODE + engine.AUTOD_VERSION
        serial = self.passive([data[:3], data[3:9], data[9:18], data[18:]], old=False)
        self.assertEqual(bytes(self.session.mode_rx), data)
        self.assertEqual(serial.calls, [])
        self.assertFalse(self.session.state.get('fdl2_ready', False))

    def test_partial_echo_can_complete_on_new_handle(self):
        self.passive([engine.MODE[:5]])
        self.session.serial.buffer = [engine.MODE[5:]]
        with patch.object(self.session, 'ensure_identity'):
            self.session.collect_mode_reply(.05, old_handle=False)
        self.assertEqual(bytes(self.session.mode_rx), engine.MODE)

    def test_unknown_duplicate_or_truncated_reply_stops_before_sync(self):
        for data in (b'junk', engine.MODE * 2, engine.MODE[:5]):
            with self.subTest(data=data):
                self.session.mode_rx = bytearray()
                with self.assertRaises(RuntimeError):
                    self.passive([data], old=False)
                self.assertEqual(self.session.state['sync_attempts'], 0)

    def test_22_after_mode_is_only_accepted_on_old_handle(self):
        self.mode_sent()
        self.session.serial = ScriptedSerial([])
        with patch.object(self.session, 'ensure_identity'), patch.object(self.session.serial, 'read_available', side_effect=ctypes.WinError(22)):
            self.session.collect_mode_reply(.1, old_handle=True)
            self.assertTrue(self.session.state['mode_old_handle_lost'])
            with self.assertRaises(OSError):
                self.session.collect_mode_reply(.1, old_handle=False)
        self.assertEqual(self.session.state['sync_attempts'], 0)

    def full_connect(self, *, version=None, old_lost=False):
        mode = ScriptedSerial([(engine.MODE, b'')])
        payload = engine.codec.AUTOD_PAYLOAD if version is None else version
        script = [(b'\x7e', reply(0x81, payload, engine.codec.CRC16, True))]
        if version is None:
            for name, code, data in [('CONNECT_CRC16', 0x80, b''), ('EXEC_BUILTIN_CRC16', 0x80, b''),
                ('SYNC_SUM16_VERSION', 0x81, engine.codec.AUTOD_PAYLOAD), ('CONNECT_SUM16', 0x80, b''),
                ('KEEP_CHARGE_SUM16', 0x80, b''), ('EXEC_BUILTIN_SUM16', 0x96, engine.codec.OBSERVED_CAPABILITY_PAYLOAD),
                ('DISABLE_TRANSCODE_SUM16', 0x80, b'')]:
                script.append((engine.codec.build_fixed(name), reply(code, data,
                    engine.codec.CRC16 if name.endswith('CRC16') else engine.codec.SUM16, True)))
        active = ScriptedSerial(script)
        first = True
        def rows():
            nonlocal first
            if first:
                first = False
                return []
            return [OLD]
        def opener(node):
            if self.session.state['open_attempts'] == 1:
                return mode
            self.assertTrue(mode.closed)
            self.assertGreaterEqual(self.clock.now, 1.8)
            return active
        if old_lost:
            mode.read_available = lambda: (_ for _ in ()).throw(ctypes.WinError(22))
        with patch.object(engine.win, 'inventory', side_effect=rows), patch.object(engine.win, 'open_download', side_effect=opener):
            if version is not None:
                with self.assertRaisesRegex(RuntimeError, '不是支持的 AutoD'):
                    self.session.connect()
            else:
                self.session.connect()
        return mode, active

    def test_full_connect_same_pnp_identity_reaches_exact_fdl2(self):
        mode, active = self.full_connect()
        self.assertEqual(mode.calls, [engine.MODE])
        self.assertEqual(self.session.state['sync_attempts'], 1)
        self.assertTrue(self.session.state['fdl2_ready'])
        self.assertEqual(active.script, [])
        self.assertFalse(self.session.state['write_started'])
        self.assertFalse(self.session.state['mode_pnp_transition_observed'])

    def test_old_handle_error_then_same_pnp_full_handshake(self):
        self.full_connect(old_lost=True)
        self.assertTrue(self.session.state['fdl2_ready'])
        self.assertTrue(self.session.state['mode_old_handle_lost'])
        self.assertEqual(self.session.state['mode_attempts'], 1)

    def test_wrong_version_on_same_node_never_sends_connect_or_exec(self):
        mode, active = self.full_connect(version=b'WRONG:AutoD\0')
        self.assertEqual(mode.calls, [engine.MODE])
        self.assertEqual(active.calls, [b'\x7e'])
        self.assertFalse(self.session.state.get('fdl2_ready', False))


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ModeHandoffTests)
    # Opening retry behavior is affected by passive handoff; old metadata test
    # required visible reenumeration, and is replaced with protocol proof above.
    for name in unittest.defaultTestLoader.getTestCaseNames(OpenLifecycleTests):
        if name != 'test_metadata_433_does_not_prove_mode_transition':
            suite.addTest(OpenLifecycleTests(name))
    for name in ('test_full_sequence_reopens_only_after_delayed_reenumeration',
                 'test_multiple_runtime_and_changed_identity_stop_without_tx',
                 'test_post_handshake_disconnect_still_refused', 'test_pre_tx_refusal_does_not_count_sync_attempt'):
        suite.addTest(ReenumerationTests(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = dict(scope='HOST_MOCKED_NO_DEVICE', tests=result.testsRun, failures=len(result.failures),
                  errors=len(result.errors), passed=result.wasSuccessful(),
                  engine_sha256=hashlib.sha256((HERE / 'engine.py').read_bytes()).hexdigest())
    (HERE / 'host-tests-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
