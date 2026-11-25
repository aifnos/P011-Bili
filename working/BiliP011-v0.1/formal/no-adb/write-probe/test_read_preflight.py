"""HOST-only subprocess fixtures. No serial imports or device access."""
import pathlib
import sys
import tempfile
import unittest

import read_preflight as p

FIXTURE = r'''
import pathlib, sys, time
mode, source = sys.argv[1:]
pathlib.Path('pgpt.bin').write_bytes(pathlib.Path(source).read_bytes())
print('FDL2> ', flush=True)
for index, line in enumerate(sys.stdin):
    with open('received.txt', 'a') as f:
        f.write(line)
    action, name, offset, length, filename = line.split()
    assert action == 'read_part' and offset == '0'
    size = int(length, 16)
    if mode == 'short' and index == 1:
        size -= 1
    pathlib.Path(filename).write_bytes(bytes(size))
    sys.stdout.buffer.write(b'read done\r\r\n\x1b[32mFDL2> \x1b[0m')
    sys.stdout.buffer.flush()
time.sleep(20)
'''
TARGET = dict(pid='4D00', port='COM9', id='HOST_FIXTURE', devinst=999,
              started=True, problem=0)


class ReadPreflightTests(unittest.TestCase):
    def run_case(self, mode, observer):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            command = [sys.executable, '-u', '-c', FIXTURE, mode, str(p.REFERENCE)]
            result = p.capture_session(command, root, p.REFERENCE.read_bytes(),
                                       observer, watchdog_seconds=10)
            supplied = (root / 'received.txt').read_text().splitlines() if (root / 'received.txt').exists() else []
            raw = (root / 'host.stdout.raw').read_bytes()
            return result, supplied, raw

    def test_complete_reads_close_child_and_keep_raw(self):
        result, supplied, raw = self.run_case('ok', lambda: [dict(TARGET)])
        self.assertEqual(result['status'], 'READ_PREFLIGHT_COMPLETE_VERIFIED')
        self.assertEqual(len(supplied), 5)
        self.assertTrue(result['sysdump_same'])
        self.assertTrue(result['child']['host_handle_closed'])
        self.assertIn(b'\r\r\n\x1b[32m', raw)
        self.assertTrue(all(line.startswith('read_part ') for line in supplied))

    def test_transient_boot_node_does_not_approve_or_stop_reading(self):
        failure = type('TransportRefusal', (RuntimeError,), {})
        calls = [0]
        def observer():
            calls[0] += 1
            if calls[0] == 1:
                raise failure('PnP status unavailable (CONFIGRET 13)')
            return [dict(TARGET)]
        result, supplied, _ = self.run_case('ok', observer)
        self.assertEqual(result['status'], 'READ_PREFLIGHT_COMPLETE_VERIFIED')
        self.assertEqual(len(supplied), 5)

    def test_node_loss_after_fdl2_is_fatal(self):
        failure = type('TransportRefusal', (RuntimeError,), {})
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            def observer():
                if (root / 'received.txt').exists():
                    raise failure('PnP status unavailable (CONFIGRET 13)')
                return [dict(TARGET)]
            result = p.capture_session([sys.executable, '-u', '-c', FIXTURE, 'ok', str(p.REFERENCE)],
                root, p.REFERENCE.read_bytes(), observer, watchdog_seconds=10)
            self.assertEqual(result['status'], 'READ_PREFLIGHT_NOT_COMPLETE')
            self.assertIn('gpt', result)
            self.assertEqual(len(result['commands']), 1)
            self.assertIn('CONFIGRET 13', result['error'])

    def test_short_file_stops_before_next_command(self):
        result, supplied, _ = self.run_case('short', lambda: [dict(TARGET)])
        self.assertEqual(result['status'], 'READ_PREFLIGHT_NOT_COMPLETE')
        self.assertEqual(len(supplied), 2)
        self.assertIn('short/oversized', result['error'])
        self.assertTrue(result['child']['host_handle_closed'])

    def test_runtime_interface_refused_before_read_command(self):
        result, supplied, _ = self.run_case('ok', lambda: [dict(TARGET, pid='4064')])
        self.assertEqual(result['status'], 'READ_PREFLIGHT_NOT_COMPLETE')
        self.assertEqual(supplied, [])
        self.assertIn('runtime interface', result['error'])
        self.assertTrue(result['child']['host_handle_closed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
