"""HOST simulation of the actual fixed runner, including negative wire paths."""
import collections
import ctypes
import pathlib
import struct
import tempfile
import types
import unittest

import sysdump_original_rewrite as p


def response(code, payload=b''):
    body = struct.pack('>HH', code, len(payload)) + payload
    return b'\x7e' + body + p.codec.sum16(body, direction='RX').to_bytes(2, 'big') + b'\x7e'


class MemoryDevice:
    def __init__(self, original, failure=None):
        self.data = dict(original)
        self.failure = failure
        self.queue = []
        self.codes = []
        self.written = bytearray()

    def pending(self):
        return sum(map(len, self.queue))

    def read_available(self):
        return self.queue.pop(0) if self.queue else b''

    def send_fixed_once(self, wire):
        assert wire[:1] == wire[-1:] == b'\x7e'
        code, size = struct.unpack('>HH', wire[1:5])
        assert len(wire) == size + 8
        assert int.from_bytes(wire[-3:-1], 'big') == p.codec.sum16(wire[1:-3], direction='TX')
        self.codes.append(code)
        payload = wire[5:-3]
        result = response(0x80)
        if code in (1, 0x10):
            name = payload[:72].decode('utf-16-le').rstrip('\0')
            size = struct.unpack('<I', payload[72:])[0]
            assert size == len(self.data[name])
            self.selected = name
            if code == 1:
                assert name == 'sysdumpdb' and size == p.SIZE
                if self.failure == 'nack-start':
                    result = response(0x82)
        elif code == 0x11:
            length, offset = struct.unpack('<II', payload)
            assert length == p.STEP
            result = response(0x93, self.data[self.selected][offset:offset + length])
        elif code == 2:
            assert self.selected == 'sysdumpdb' and len(payload) == p.STEP
            self.written.extend(payload)
            if self.failure == 'bad-midst-ack':
                result = result[:-2] + bytes([result[-2] ^ 1]) + result[-1:]
        elif code == 3:
            assert len(self.written) == p.SIZE
            self.data['sysdumpdb'] = bytes(self.written)
        else:
            assert code == 0x12
        self.queue = [result[:3], result[3:]]


class FixedWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = {name: bytes(range(256)) * (size // 256)
                         for name, (_, size, _) in p.FILES.items()}

    def run_case(self, failure=None, corrupt_before=False):
        device = MemoryDevice(self.originals, failure)
        if corrupt_before:
            device.data['miscdata'] = b'X' + device.data['miscdata'][1:]
        status = dict(write_data_attempts=0, write_bytes_acked=0)
        with tempfile.TemporaryDirectory() as folder:
            wire = p.Wire(device, folder, lambda: None)
            error = None
            try:
                p.run_sequence(wire, self.originals, folder, status)
            except Exception as exc:
                error = str(exc)
                previous_count = len(device.codes)
                with self.assertRaises(RuntimeError):
                    wire.exchange(p._packet(3), label='FORBIDDEN_AFTER_FAILURE')
                self.assertEqual(len(device.codes), previous_count)
            finally:
                wire.close_logs()
            raw = (pathlib.Path(folder) / 'wire.rx.raw').read_bytes()
        return device, status, error, raw

    def test_full_roundtrip_and_all_2560_blocks(self):
        device, status, error, _ = self.run_case()
        self.assertIsNone(error)
        self.assertEqual(status['status'], 'ORIGINAL_REWRITE_ACK_AND_READBACK_MATCHED')
        self.assertEqual(collections.Counter(device.codes)[1], 1)
        self.assertEqual(collections.Counter(device.codes)[2], 2560)
        self.assertEqual(collections.Counter(device.codes)[3], 1)
        self.assertEqual(bytes(device.written), self.originals['sysdumpdb'])
        self.assertTrue(all(row['matches_original'] for row in status['after'].values()))

    def test_start_nack_never_sends_data_or_end(self):
        device, status, error, raw = self.run_case('nack-start')
        self.assertIn('unexpected response', error)
        self.assertNotIn(2, device.codes)
        self.assertNotIn(3, device.codes)
        self.assertEqual(status['write_bytes_acked'], 0)
        self.assertTrue(raw.endswith(response(0x82)))

    def test_bad_midst_ack_stops_after_one_data_without_end(self):
        device, status, error, _ = self.run_case('bad-midst-ack')
        self.assertIn('CHECKSUM_MISMATCH', error)
        self.assertEqual(device.codes.count(2), 1)
        self.assertNotIn(3, device.codes)
        self.assertEqual(status['write_data_attempts'], 1)
        self.assertEqual(status['write_bytes_acked'], 0)

    def test_changed_precheck_never_starts_write(self):
        # Semantic mismatch leaves transport valid, but the fixed orchestrator
        # aborts before WRITE_START. Do not call transport directly afterward.
        device = MemoryDevice(self.originals)
        device.data['miscdata'] = b'X' + device.data['miscdata'][1:]
        with tempfile.TemporaryDirectory() as folder:
            wire = p.Wire(device, folder, lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, 'before read differs'):
                    p.run_sequence(wire, self.originals, folder, dict(write_data_attempts=0, write_bytes_acked=0))
                self.assertNotIn(1, device.codes)
            finally:
                wire.close_logs()

    def test_short_windows_write_consumes_one_attempt(self):
        calls = []
        def write_file(handle, buffer, length, pointer, overlapped):
            calls.append(length)
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = length - 1
            return True
        serial = object.__new__(p.WindowsFixedSerial)
        serial.win = types.SimpleNamespace(DWORD=ctypes.c_uint32)
        serial.serial = types.SimpleNamespace(_api=types.SimpleNamespace(WriteFile=write_file),
            _handle_open=lambda: 123, pending=lambda: 0)
        with tempfile.TemporaryDirectory() as folder:
            wire = p.Wire(serial, folder, lambda: None)
            try:
                with self.assertRaisesRegex(RuntimeError, 'short WriteFile'):
                    wire.exchange(p._select(1, 'sysdumpdb', p.SIZE), label='START')
                with self.assertRaisesRegex(RuntimeError, 'previously failed'):
                    wire.exchange(p._select(1, 'sysdumpdb', p.SIZE), label='RETRY_FORBIDDEN')
                self.assertEqual(calls, [84])
                self.assertEqual(wire.count, 1)
            finally:
                wire.close_logs()


if __name__ == '__main__':
    unittest.main(verbosity=2)
