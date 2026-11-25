"""HOST-only timeline simulations; no Win32/USB/serial import or operation."""
import unittest

import bsl_frames as bsl
import early_mode_probe as ep


def node(port='COM14', identity='USB\\VID_1782&PID_4D00\\HOST_FIXTURE'):
    return dict(pid='4D00', port=port, started=True, problem=0,
                id=identity, devinst=14)


NORMAL = dict(pid='4064', port='COM15', started=True, problem=0,
              id='USB\\VID_1782&PID_4064\\HOST_FIXTURE', devinst=15)


class Clock:
    def __init__(self):
        self.value = 0.

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Serial:
    def __init__(self, world, session):
        self.world, self.session = world, session
        self.is_open = True
        self.queued = []
        self.loss_at = None
        self.fail_mode = False
        self.on_write = None
        self.after_read = None

    def queue(self, after, data):
        self.queued.append((self.world.clock.now() + after, bytes(data)))

    def check(self):
        if not self.is_open or (self.loss_at is not None and
                                self.world.clock.now() >= self.loss_at):
            error = OSError('HOST fixture: device removed')
            error.winerror = 1167
            raise error

    def pending(self):
        self.check()
        return sum(len(data) for at, data in self.queued if at <= self.world.clock.now())

    def read_available(self):
        self.check()
        due = [(at, data) for at, data in self.queued if at <= self.world.clock.now()]
        self.queued = [(at, data) for at, data in self.queued if at > self.world.clock.now()]
        raw = b''.join(data for _, data in due)
        if raw and self.after_read:
            self.after_read(raw)
        return raw

    def write(self, data):
        self.check()
        data = bytes(data)
        self.world.transmitted.append((self.session, data))
        if data == ep.MODE_FRAME and self.fail_mode:
            raise OSError('HOST fixture: possibly partial MODE write')
        if self.on_write:
            self.on_write(data)

    def close(self):
        self.is_open = False


class World:
    def __init__(self, setup=None):
        self.clock = Clock()
        self.records, self.transmitted, self.handles = [], [], []
        self.setup = setup
        self.inventory_override = None
        self.open_errors = []
        self.gap = None
        self.sink_error_name = None

    def inventory(self):
        if self.inventory_override:
            return self.inventory_override()
        now = self.clock.now()
        if now < .05:
            return [dict(NORMAL)]
        if self.gap and self.gap[0] <= now < self.gap[1]:
            return []
        return [node()]

    def opener(self, current):
        if self.open_errors:
            raise self.open_errors.pop(0)
        self.assert_download(current)
        serial = Serial(self, len(self.handles) + 1)
        self.handles.append(serial)
        if self.setup:
            self.setup(serial)
        return serial

    @staticmethod
    def assert_download(current):
        assert current['pid'] == '4D00' and current['problem'] == 0 and current['started']

    def sink(self, kind, value):
        self.records.append((kind, value))
        if kind == 'rx' and value['name'] == self.sink_error_name:
            raise OSError('HOST fixture: log filesystem failed')

    def probe(self, permit=True, wait=1):
        return ep.Probe(self.inventory, self.opener, self.sink, permit_mode=permit,
                        clock=self.clock.now, sleep=self.clock.sleep, wait_seconds=wait)

    def writes(self, value):
        return [(session, data) for session, data in self.transmitted if data == value]


def respond_live(serial):
    def write(data):
        if data == ep.MODE_FRAME:
            serial.queue(.04, bsl.AUTOD_VERSION_FRAME[:8])
            serial.queue(.08, bsl.AUTOD_VERSION_FRAME[8:])
        elif data == bsl.CONNECT_FRAME:
            serial.queue(.02, bsl.ACK_FRAME)
    serial.on_write = write


class ProbeTimelineTests(unittest.TestCase):
    def assert_closed(self, world):
        self.assertTrue(all(not item.is_open for item in world.handles))
        self.assertTrue(any(kind == 'result' for kind, _ in world.records))

    def test_live_mode_then_split_version_then_ack(self):
        world = World(respond_live)
        probe = world.probe()
        result = probe.run()
        self.assertEqual(result['status'], 'AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS')
        self.assertEqual(world.transmitted, [(1, ep.MODE_FRAME), (1, bsl.CONNECT_FRAME)])
        self.assertTrue(result['mode_write_returned'])
        self.assertTrue(result['connect_ack_verified'])
        self.assertFalse(result['storage_access_attempted'])
        self.assert_closed(world)

    def test_open_433_loss_reenumerate_same_com_requires_new_version(self):
        def setup(serial):
            if serial.session == 1:
                def write(data):
                    if data == ep.MODE_FRAME:
                        serial.loss_at = world.clock.now() + .04
                        world.gap = (serial.loss_at, serial.loss_at + .1)
                serial.on_write = write
            else:
                def write(data):
                    if data == ep.SYNC_FRAME:
                        serial.queue(.02, bsl.AUTOD_VERSION_FRAME[:9])
                        serial.queue(.06, bsl.AUTOD_VERSION_FRAME[9:])
                    elif data == bsl.CONNECT_FRAME:
                        serial.queue(.02, bsl.ACK_FRAME)
                serial.on_write = write
        world = World(setup)
        error = OSError('HOST fixture: enumerated before ready')
        error.winerror = 433
        world.open_errors.append(error)
        result = world.probe().run()
        self.assertEqual(result['open_failures'], 1)
        self.assertEqual(result['sessions_opened'], 2)
        self.assertEqual(world.transmitted,
                         [(1, ep.MODE_FRAME), (2, ep.SYNC_FRAME), (2, bsl.CONNECT_FRAME)])
        self.assert_closed(world)

    def test_passive_exact_version_skips_mode_and_sync(self):
        def setup(serial):
            serial.queue(.02, bsl.AUTOD_VERSION_FRAME)
            serial.on_write = lambda data: serial.queue(.02, bsl.ACK_FRAME)
        world = World(setup)
        result = world.probe().run()
        self.assertFalse(result['mode_attempted'])
        self.assertEqual(world.transmitted, [(1, bsl.CONNECT_FRAME)])
        self.assert_closed(world)

    def test_unsolicited_bad_partial_ack_never_send(self):
        bad_crc = bytearray(bsl.AUTOD_VERSION_FRAME)
        bad_crc[-2] ^= 1
        for raw in (b'unknown', bsl.AUTOD_VERSION_FRAME[:7], bsl.ACK_FRAME,
                    bytes(bad_crc), ep.MODE_FRAME):
            with self.subTest(raw=raw.hex()):
                world = World(lambda serial: serial.queue(.02, raw))
                with self.assertRaises(ep.Refused):
                    world.probe().run()
                self.assertEqual(world.transmitted, [])
                self.assert_closed(world)

    def test_silent_version_uses_at_most_four_sync(self):
        world = World()
        probe = world.probe()
        with self.assertRaises(ep.Refused):
            probe.run()
        self.assertEqual(len(world.writes(ep.MODE_FRAME)), 1)
        self.assertEqual(len(world.writes(ep.SYNC_FRAME)), 4)
        self.assertEqual(world.writes(bsl.CONNECT_FRAME), [])
        self.assertEqual(probe.state['sync_attempted'], 4)
        self.assert_closed(world)

    def test_possibly_partial_mode_write_is_not_retried(self):
        world = World(lambda serial: setattr(serial, 'fail_mode', True))
        probe = world.probe()
        with self.assertRaises(OSError):
            probe.run()
        self.assertTrue(probe.state['mode_attempted'])
        self.assertFalse(probe.state['mode_write_returned'])
        self.assertEqual(world.transmitted, [(1, ep.MODE_FRAME)])
        self.assertEqual(len(world.handles), 1)
        self.assert_closed(world)

    def test_old_session_valid_version_cannot_authorize_new_handle(self):
        def setup(serial):
            if serial.session == 1:
                serial.on_write = lambda data: serial.queue(.02, bsl.AUTOD_VERSION_FRAME)
                def lose_after_version(raw):
                    serial.loss_at = world.clock.now()
                    world.gap = (serial.loss_at, serial.loss_at + .1)
                serial.after_read = lose_after_version
            # Session 2 deliberately never sends a fresh version.
        world = World(setup)
        probe = world.probe()
        with self.assertRaises(ep.Refused):
            probe.run()
        self.assertEqual(len(world.handles), 2)
        self.assertEqual(world.writes(bsl.CONNECT_FRAME), [])
        self.assertEqual(len(world.writes(ep.SYNC_FRAME)), 4)
        self.assertFalse(probe.state['autod_version_verified'])
        self.assert_closed(world)

    def test_data_arriving_at_passive_deadline_prevents_mode(self):
        world = World(lambda serial: serial.queue(.1, bsl.ACK_FRAME))
        with self.assertRaises(ep.Refused):
            world.probe().run()
        self.assertEqual(world.transmitted, [])
        self.assert_closed(world)

    def test_runtime_only_never_opens_or_transmits(self):
        world = World()
        world.inventory_override = lambda: [dict(NORMAL)]
        with self.assertRaises(ep.Refused):
            world.probe().run()
        self.assertEqual(world.handles, [])
        self.assertEqual(world.transmitted, [])

    def test_initial_download_must_not_open_preexisting_session(self):
        world = World()
        world.inventory_override = lambda: [node()]
        with self.assertRaises(ep.Refused):
            world.probe().run()
        self.assertEqual(world.handles, [])
        self.assertEqual(world.transmitted, [])

    def test_permission_false_prevents_mode(self):
        world = World()
        with self.assertRaises(ep.Refused):
            world.probe(permit=False).run()
        self.assertEqual(world.transmitted, [])
        self.assert_closed(world)

    def test_after_mode_unexpected_frame_cannot_lead_to_sync(self):
        def setup(serial):
            serial.on_write = lambda data: serial.queue(.02, bsl.ACK_FRAME)
        world = World(setup)
        with self.assertRaises(ep.Refused):
            world.probe().run()
        self.assertEqual(world.transmitted, [(1, ep.MODE_FRAME)])
        self.assert_closed(world)

    def test_ack_corrupt_partial_or_mixed_cannot_confirm(self):
        bad_crc = bytearray(bsl.ACK_FRAME)
        bad_crc[-2] ^= 1
        for ack in (bytes(bad_crc), bsl.ACK_FRAME[:-1],
                    bsl.ACK_FRAME + bsl.AUTOD_VERSION_FRAME, b'noise'):
            with self.subTest(ack=ack.hex()):
                def setup(serial):
                    def write(data):
                        serial.queue(.02, bsl.AUTOD_VERSION_FRAME if data == ep.MODE_FRAME else ack)
                    serial.on_write = write
                world = World(setup)
                probe = world.probe()
                with self.assertRaises(ep.Refused):
                    probe.run()
                self.assertTrue(probe.state['connect_attempted'])
                self.assertFalse(probe.state['connect_ack_verified'])
                self.assertEqual(len(world.writes(bsl.CONNECT_FRAME)), 1)
                self.assert_closed(world)

    def test_second_download_device_before_connect_refuses(self):
        def setup(serial):
            respond_live(serial)
            def after_read(raw):
                if raw.endswith(bsl.AUTOD_VERSION_FRAME[8:]):
                    world.inventory_override = lambda: [node(), node('COM99', 'SECOND_HOST_FIXTURE')]
            serial.after_read = after_read
        world = World(setup)
        with self.assertRaises(ep.Refused):
            world.probe().run()
        self.assertEqual(world.writes(bsl.CONNECT_FRAME), [])
        self.assert_closed(world)

    def test_log_failure_after_mode_must_not_reopen_or_sync(self):
        world = World()
        world.sink_error_name = 'after-mode'
        with self.assertRaises(OSError):
            world.probe().run()
        self.assertEqual(len(world.handles), 1)
        self.assertEqual(world.transmitted, [(1, ep.MODE_FRAME)])
        self.assert_closed(world)

    def test_success_result_is_returned_only_after_host_handle_closes(self):
        world = World(respond_live)
        result = world.probe().run()
        self.assertTrue(result['host_handle_closed'])
        self.assertTrue(result['connect_ack_verified'])
        self.assertEqual(result['status'], 'AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS')
        emitted = [value for kind, value in world.records if kind == 'result']
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], result)
        self.assert_closed(world)

    def test_close_failure_preserves_ack_but_refuses_overall_success(self):
        close_calls = []
        def setup(serial):
            respond_live(serial)
            def failed_close():
                close_calls.append(serial.session)
                raise OSError('HOST fixture: CloseHandle failed; release unconfirmed')
            serial.close = failed_close
        world = World(setup)
        probe = world.probe()
        with self.assertRaises(OSError):
            probe.run()
        self.assertEqual(close_calls, [1])
        self.assertTrue(probe.state['connect_ack_verified'])
        self.assertFalse(probe.state['host_handle_closed'])
        self.assertEqual(probe.state['status'], 'HOST_CLOSE_UNCONFIRMED')
        emitted = [value for kind, value in world.records if kind == 'result']
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]['status'], 'HOST_CLOSE_UNCONFIRMED')
        self.assertTrue(emitted[0]['connect_ack_verified'])
        self.assertEqual(len(world.writes(bsl.CONNECT_FRAME)), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
