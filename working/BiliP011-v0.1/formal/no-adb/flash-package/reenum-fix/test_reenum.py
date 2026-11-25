"""Targeted fake PnP timelines: no real devices, sleeps, driver or flashing."""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / 'out/P011-Bili-NoADB-v2-driver-final-20261014/app'))
import engine
sys.path.append(str(HERE.parent))
from test_package import ScriptedSerial, reply

OLD = dict(id='HOST_ONLY_USB_ID', pid='4D00', started=True, problem=0, port='COM14', devinst=1)
NEW = dict(OLD, devinst=2, port='COM15')


class Clock:
    now = 0.0
    def monotonic(self):
        return self.now
    def sleep(self, value):
        self.now += value


class ReenumerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = engine.Session(self.temp.name)
        self.addCleanup(self.session.close)
        self.session.node = dict(OLD)
        self.session.state['mode_attempts'] = 1
        self.clock = Clock()
        self.patchers = [patch.object(engine.time, 'monotonic', self.clock.monotonic), patch.object(engine.time, 'sleep', self.clock.sleep)]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def wait(self, inventory, seconds=2):
        with patch.object(engine.win, 'inventory', side_effect=inventory):
            return self.session.wait_mode_reenumeration(seconds)

    def test_old_node_survives_half_second_then_disconnect_same_devinst(self):
        def rows():
            return [OLD] if self.clock.now < .8 else ([] if self.clock.now < 1.0 else [OLD])
        row = self.wait(rows)
        self.assertEqual(row, OLD)
        self.assertGreaterEqual(self.clock.now, 1.2)
        self.assertEqual(self.session.attempts, 0)

    def test_new_devinst_counts_as_reenumeration_even_if_gap_missed(self):
        row = self.wait(lambda: [OLD] if self.clock.now < .7 else [NEW])
        self.assertEqual(row, NEW)
        self.assertGreaterEqual(self.clock.now, .9)

    def test_configuration_transient_requires_real_transition(self):
        def rows():
            if self.clock.now < .1:
                raise engine.win.TransportRefusal('PnP status unavailable (CONFIGRET 13)')
            return [OLD]
        with self.assertRaisesRegex(RuntimeError, '重枚举超时'):
            self.wait(rows, .5)
        self.assertEqual(self.session.state['sync_attempts'], 0)

    def test_driver_not_ready_then_ready_stability(self):
        def rows():
            if self.clock.now < .1:
                return []
            return [dict(NEW, started=False, problem=28)] if self.clock.now < .4 else [NEW]
        self.assertEqual(self.wait(rows), NEW)
        self.assertGreaterEqual(self.clock.now, .6)

    def test_multiple_runtime_and_changed_identity_stop_without_tx(self):
        cases = [[NEW, dict(NEW, id='OTHER')], [dict(NEW, pid='4064')], [dict(NEW, id='OTHER')]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                self.wait(lambda: rows)
        self.assertEqual(self.session.attempts, 0)

    def test_post_handshake_disconnect_still_refused(self):
        self.session.state['fdl2_ready'] = True
        with patch.object(engine.win, 'inventory', return_value=[]):
            with self.assertRaises(engine.win.TransportRefusal):
                self.session.ensure_identity(True)

    def test_pre_tx_refusal_does_not_count_sync_attempt(self):
        with patch.object(self.session, 'ensure_identity', side_effect=engine.win.TransportRefusal('gone')):
            with self.assertRaises(engine.win.TransportRefusal):
                self.session.send_once(b'\x7e', 'SYNC_CRC', True)
        self.assertEqual(self.session.state['sync_attempts'], 0)

    def test_full_sequence_reopens_only_after_delayed_reenumeration(self):
        self.session.state['mode_attempts'] = 0
        mode_serial = ScriptedSerial([(engine.MODE, b'')])
        stages = [('CONNECT_CRC16', 0x80, b''), ('EXEC_BUILTIN_CRC16', 0x80, b''),
            ('SYNC_SUM16_VERSION', 0x81, engine.codec.AUTOD_PAYLOAD), ('CONNECT_SUM16', 0x80, b''),
            ('KEEP_CHARGE_SUM16', 0x80, b''), ('EXEC_BUILTIN_SUM16', 0x96, engine.codec.OBSERVED_CAPABILITY_PAYLOAD),
            ('DISABLE_TRANSCODE_SUM16', 0x80, b'')]
        script = [(b'\x7e', reply(0x81, engine.codec.AUTOD_PAYLOAD, engine.codec.CRC16, True))]
        script += [(engine.codec.build_fixed(name), reply(code, data,
            engine.codec.CRC16 if name.endswith('CRC16') else engine.codec.SUM16, True)) for name, code, data in stages]
        data_serial = ScriptedSerial(script)
        inventories = 0
        def rows():
            nonlocal inventories
            inventories += 1
            if inventories == 1:
                return []
            return [OLD] if self.clock.now < .8 else ([] if self.clock.now < 1 else [NEW])
        def open_node(node):
            if self.session.state['open_attempts'] == 1:
                return mode_serial
            self.assertGreaterEqual(self.clock.now, 1.2)
            self.assertTrue(mode_serial.closed)
            self.assertEqual(node, NEW)
            return data_serial
        with patch.object(engine.win, 'inventory', side_effect=rows), patch.object(engine.win, 'open_download', side_effect=open_node):
            self.session.connect()
        self.assertTrue(self.session.state['fdl2_ready'])
        self.assertEqual(self.session.state['mode_attempts'], 1)
        self.assertEqual(self.session.state['sync_attempts'], 1)
        self.assertEqual(self.session.state['open_attempts'], 2)
        self.assertEqual(data_serial.script, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
