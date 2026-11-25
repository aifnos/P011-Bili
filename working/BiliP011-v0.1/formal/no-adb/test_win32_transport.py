"""HOST fixtures only. All inventory and Win32 serial calls are replaced.

No test loads Windows DLLs, reads live PnP state, or opens a device/COM port.
"""

import ctypes
import unittest
from unittest.mock import patch

import win32_download_transport as transport


def node(**changes):
    result = {"id": "USB\\VID_1782&PID_4D00\\HOST-FIXTURE",
              "devinst": 123, "pid": "4D00", "port": "COM8",
              "started": True, "problem": 0, "name": "HOST fixture"}
    result.update(changes)
    return result


def contents(pointer, kind):
    return ctypes.cast(pointer, ctypes.POINTER(kind)).contents


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.input = b""
        self.errors = 0
        self.short_write = False
        self.config_failure = False
        self.closed = []
        self.dcb = None
        self.timeouts = None

    def CreateFileW(self, path, access, sharing, security, disposition, flags, template):
        self.calls.append(("open", path, access, sharing, disposition, flags))
        return 0x12345678ABCDEF01

    def GetCommState(self, handle, state):
        self.calls.append(("get_state", handle))
        return True

    def SetCommState(self, handle, state):
        self.dcb = transport.DCB.from_buffer_copy(contents(state, transport.DCB))
        if self.config_failure:
            raise OSError(5, "HOST fixture configuration failure")
        return True

    def SetCommTimeouts(self, handle, state):
        self.timeouts = transport.COMMTIMEOUTS.from_buffer_copy(
            contents(state, transport.COMMTIMEOUTS))
        return True

    def ClearCommError(self, handle, errors, status):
        self.calls.append(("pending", handle))
        contents(errors, transport.DWORD).value = self.errors
        contents(status, transport.COMSTAT).cbInQue = len(self.input)
        return True

    def ReadFile(self, handle, buffer, count, received, overlapped):
        self.calls.append(("read", count, overlapped))
        data = self.input[:count]
        self.input = self.input[count:]
        ctypes.memmove(buffer, data, len(data))
        contents(received, transport.DWORD).value = len(data)
        return True

    def WriteFile(self, handle, buffer, count, written, overlapped):
        self.calls.append(("write", ctypes.string_at(buffer, count), overlapped))
        contents(written, transport.DWORD).value = count - int(self.short_write)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.nodes = [node()]
        self.inventory_patch = patch.object(transport, "inventory", side_effect=lambda: self.nodes)
        self.api_patch = patch.object(transport, "_get_api", return_value=self.api)
        self.inventory_patch.start()
        self.api_patch.start()
        self.addCleanup(self.inventory_patch.stop)
        self.addCleanup(self.api_patch.stop)

    def test_abi_without_api(self):
        with patch.object(transport, "_get_api", side_effect=AssertionError("unexpected API")):
            self.assertEqual(transport.self_check()["DCB"], 28)
            self.assertEqual(transport.self_check()["COMMTIMEOUTS"], 20)

    def test_normal_system_never_opened(self):
        for candidate in [node(pid="4064"), node(started=False), node(problem=28),
                          node(port="COM8\\invalid"), node(port=""), node(devinst=0)]:
            with self.assertRaises(transport.TransportRefusal):
                transport.open_download(candidate)
        self.assertEqual(self.api.calls, [])

    def test_uniqueness_and_exact_identity_before_open(self):
        candidate = node()
        for nodes in [[], [node(), node(devinst=124)], [node(devinst=124)],
                      [node(port="COM9")], [node(id="USB\\OTHER")]]:
            self.nodes = nodes
            with self.assertRaises(transport.TransportRefusal):
                transport.open_download(candidate)
        self.assertEqual(self.api.calls, [])

    def test_exclusive_synchronous_configuration_no_input_loss(self):
        self.api.input = b"\0\x7eHOST\0"
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        self.assertTrue(serial.is_open)
        self.assertEqual(self.api.calls[0],
                         ("open", "\\\\.\\COM8", 0xC0000000, 0, 3, 0))
        self.assertEqual(self.api.dcb.BaudRate, 115200)
        self.assertEqual(self.api.dcb.ByteSize, 8)
        self.assertEqual(self.api.dcb.Parity, 0)
        self.assertEqual(self.api.dcb.StopBits, 0)
        self.assertEqual(self.api.dcb.flags, 0x1011)
        self.assertEqual(list(bytes(self.api.timeouts)),
                         list(bytes(transport.COMMTIMEOUTS(0xFFFFFFFF, 0, 0, 0, 1000))))
        self.assertEqual(self.api.input, b"\0\x7eHOST\0")
        self.assertFalse(any(call[0] in ("read", "write") for call in self.api.calls))

    def test_configuration_exception_disposes_only_opened_handle(self):
        self.api.config_failure = True
        with self.assertRaisesRegex(OSError, "configuration failure"):
            transport.open_download(node())
        self.assertEqual(self.api.closed, [0x12345678ABCDEF01])

    def test_changed_identity_after_open_disposes_handle(self):
        with patch.object(transport, "inventory", side_effect=[[node()], [node(devinst=999)]]):
            with self.assertRaises(transport.TransportRefusal):
                transport.open_download(node())
        self.assertEqual(len(self.api.closed), 1)

    def test_pending_read_cap_and_zero_bytes_preserved(self):
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        self.api.input = (b"\0\x7eHOST" * 1000)
        before = self.api.input
        self.assertEqual(serial.pending(), len(before))
        self.assertEqual(self.api.input, before)
        self.assertEqual(serial.read_available(), before[:4096])
        self.assertEqual(serial.read_available(), before[4096:])
        self.assertEqual(serial.read_available(), b"")
        self.assertTrue(all(call[1] <= 4096 for call in self.api.calls if call[0] == "read"))

    def test_nonzero_error_flags_stop_read_and_tx(self):
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        self.api.input = b"HOST"
        self.api.errors = 0x0002
        with self.assertRaises(transport.TransportRefusal):
            serial.read_available()
        with self.assertRaises(transport.TransportRefusal):
            serial.write(transport.SYNC)
        self.assertEqual(self.api.input, b"HOST")
        self.assertFalse(any(call[0] in ("read", "write") for call in self.api.calls))

    def test_only_three_tx_constants_no_implicit_retry(self):
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        for forbidden in (b"", b"loader", transport.SYNC * 2, bytearray(transport.SYNC)):
            with self.assertRaises(transport.TransportRefusal):
                serial.write(forbidden)
        for permitted in (transport.FE82, transport.SYNC, transport.CONNECT):
            self.assertIsNone(serial.write(permitted))
        self.assertEqual([call[1] for call in self.api.calls if call[0] == "write"],
                         [transport.FE82, transport.SYNC, transport.CONNECT])
        self.api.short_write = True
        with self.assertRaisesRegex(transport.TransportRefusal, "Short WriteFile"):
            serial.write(transport.CONNECT)
        self.assertEqual(len([call for call in self.api.calls if call[0] == "write"]), 4)

    def test_every_write_rechecks_present_exact_identity(self):
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        for changed in [[], [node(devinst=124)], [node(started=False)],
                        [node(), node(devinst=124)], [node(pid="4064")]]:
            self.nodes = changed
            with self.assertRaises(transport.TransportRefusal):
                serial.write(transport.SYNC)
        self.assertFalse(any(call[0] == "write" for call in self.api.calls))

    def test_close_idempotent_and_closed_handle_refuses(self):
        serial = transport.open_download(node())
        serial.close()
        serial.close()
        self.assertFalse(serial.is_open)
        self.assertEqual(len(self.api.closed), 1)
        with self.assertRaises(transport.TransportRefusal):
            serial.pending()
        with self.assertRaises(transport.TransportRefusal):
            serial.write(transport.SYNC)


class TransportAdditionalTests(unittest.TestCase):
    # Reuse fixture setup without inheriting/re-running the original 11 tests.
    setUp = TransportTests.setUp

    def test_normal_and_download_coexistence_refuses_open_and_write(self):
        normal = node(pid="4064", id="USB\\VID_1782&PID_4064\\HOST-FIXTURE-2")
        self.nodes = [node(), normal]
        with self.assertRaises(transport.TransportRefusal):
            transport.open_download(node())
        self.assertEqual(self.api.calls, [])
        self.nodes = [node()]
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        self.nodes.append(normal)
        with self.assertRaises(transport.TransportRefusal):
            serial.write(transport.SYNC)
        self.assertFalse(any(call[0] == "write" for call in self.api.calls))

    def test_late_unread_input_refuses_tx_without_consuming_bytes(self):
        serial = transport.open_download(node())
        self.addCleanup(serial.close)
        self.api.input = b"\x7e\x00"
        with self.assertRaisesRegex(transport.TransportRefusal, "Unread RX bytes"):
            serial.write(transport.CONNECT)
        self.assertEqual(self.api.input, b"\x7e\x00")
        self.assertFalse(any(call[0] in ("read", "write") for call in self.api.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
