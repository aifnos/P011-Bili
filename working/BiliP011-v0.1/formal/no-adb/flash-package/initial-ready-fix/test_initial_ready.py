"""New initial PnP readiness tests plus the affected complete connection flow."""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / 'out/P011-Bili-NoADB-v3-reenum-20261014/app'))
import engine
sys.path.append(str(HERE.parent / 'reenum-fix'))
from test_reenum import Clock, OLD, ReenumerationTests


class InitialReadyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = engine.Session(self.temp.name)
        self.addCleanup(self.session.close)
        self.clock = Clock()
        for p in (patch.object(engine.time, 'monotonic', self.clock.monotonic), patch.object(engine.time, 'sleep', self.clock.sleep)):
            p.start()
            self.addCleanup(p.stop)

    def run_gate(self, timeline, bound=.5):
        initial = True
        def inventory():
            nonlocal initial
            if initial:
                initial = False
                return []
            return timeline()
        with patch.object(engine.win, 'inventory', side_effect=inventory), patch.object(engine.win, 'open_download', side_effect=AssertionError('Gate must not open serial')):
            return self.session.wait_initial_ready(2, bound)

    def test_node_appears_before_started_and_port(self):
        def rows():
            return [dict(OLD, started=False, port='')] if self.clock.now < .08 else [OLD]
        self.assertEqual(self.run_gate(rows), OLD)
        self.assertLess(self.clock.now, .11)
        self.assertEqual(self.session.state['open_attempts'], 0)
        self.assertEqual(self.session.state['mode_attempts'], 0)

    def test_started_before_com_assignment(self):
        self.assertEqual(self.run_gate(lambda: [dict(OLD, port='')] if self.clock.now < .12 else [OLD]), OLD)
        self.assertGreaterEqual(self.clock.now, .12)

    def test_ready_immediately_has_no_extra_stability_delay(self):
        self.assertEqual(self.run_gate(lambda: [OLD]), OLD)
        self.assertEqual(self.clock.now, 0)

    def test_permanent_problem_reports_actual_code_without_mode(self):
        with self.assertRaisesRegex(RuntimeError, r'problem=28.*COM=\(无\)'):
            self.run_gate(lambda: [dict(OLD, started=False, problem=28, port='')], .2)
        self.assertEqual(self.session.state['mode_attempts'], 0)
        self.assertEqual(self.session.state['open_attempts'], 0)
        self.assertLess(self.clock.now, .23)

    def test_flapping_does_not_extend_readiness_deadline(self):
        def rows():
            return [dict(OLD, started=False)] if int(self.clock.now * 100) % 4 == 0 else []
        with self.assertRaisesRegex(RuntimeError, '持续未就绪'):
            self.run_gate(rows, .2)
        self.assertLess(self.clock.now, .23)

    def test_metadata_configret_transient_is_observation_only(self):
        def rows():
            if self.clock.now < .08:
                raise engine.win.TransportRefusal('PnP status unavailable (CONFIGRET 13)')
            return [OLD]
        self.assertEqual(self.run_gate(rows), OLD)
        self.assertEqual(self.session.attempts, 0)

    def test_multiple_or_normal_system_stops_before_open(self):
        for rows in ([OLD, dict(OLD, id='OTHER')], [dict(OLD, pid='4064')]):
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                self.run_gate(lambda: rows)
        self.assertEqual(self.session.state['open_attempts'], 0)

    def test_identity_change_while_waiting_is_refused(self):
        def rows():
            return [dict(OLD, started=False)] if self.clock.now < .04 else [dict(OLD, id='OTHER')]
        with self.assertRaisesRegex(RuntimeError, '身份变化'):
            self.run_gate(rows)
        self.assertEqual(self.session.state['mode_attempts'], 0)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(InitialReadyTests)
    suite.addTest(ReenumerationTests('test_full_sequence_reopens_only_after_delayed_reenumeration'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
