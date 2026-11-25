"""Restricted Windows transport for the P011 AutoD handshake.

Importing this module performs no Windows API or device calls. ``inventory``
only reads present PnP metadata. Opening the download serial port is a separate,
explicit operation; normal-system PID 4064 is never opened. This module cannot
transmit loaders, partition commands, reset commands, or arbitrary bytes.

Microsoft definitions used (checked 2026-10-14):
https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-dcb
https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-commtimeouts
https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-comstat
https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupdigetclassdevsw
https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_get_devnode_status

The caller owns protocol sequencing, deadlines, raw logs and the attempted-TX
counter. Count an attempt BEFORE calling ``write``: a failed/short WriteFile can
already have transmitted bytes and must not be retried automatically.
"""

import ctypes
import os
import re
import sys


DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BYTE = ctypes.c_uint8
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
ULONG_PTR = ctypes.c_size_t
LPDWORD = ctypes.POINTER(DWORD)
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FE82 = bytes.fromhex("7e000000000800fe827e")
SYNC = b"\x7e"
CONNECT = bytes.fromhex("7e0000000000007e")
ALLOWED_TX = frozenset((FE82, SYNC, CONNECT))
MAX_READ = 4096

_PID_RE = re.compile(r"(?:^|[\\&])VID_1782&PID_(4D00|4064)(?=[\\&]|$)", re.I)
_PORT_RE = re.compile(r"COM[1-9][0-9]*\Z", re.I)
_API = None
_CREATE_TOKEN = object()


class GUID(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD),
                ("Data4", BYTE * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("ClassGuid", GUID), ("DevInst", DWORD),
                ("Reserved", ULONG_PTR)]


class DCB(ctypes.Structure):
    # The documented DWORD bit-field group occupies one DWORD. Explicit flags
    # avoid Python/compiler bit-field layout differences, including on x64.
    _fields_ = [("DCBlength", DWORD), ("BaudRate", DWORD), ("flags", DWORD),
                ("wReserved", WORD), ("XonLim", WORD), ("XoffLim", WORD),
                ("ByteSize", BYTE), ("Parity", BYTE), ("StopBits", BYTE),
                ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
                ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char),
                ("EvtChar", ctypes.c_char), ("wReserved1", WORD)]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [("ReadIntervalTimeout", DWORD),
                ("ReadTotalTimeoutMultiplier", DWORD),
                ("ReadTotalTimeoutConstant", DWORD),
                ("WriteTotalTimeoutMultiplier", DWORD),
                ("WriteTotalTimeoutConstant", DWORD)]


class COMSTAT(ctypes.Structure):
    _fields_ = [("flags", DWORD), ("cbInQue", DWORD), ("cbOutQue", DWORD)]


class TransportRefusal(RuntimeError):
    """A safety/identity gate refused an operation; contains no instance ID."""


def _win_error(code=None):
    # Capture GetLastError before another API/cleanup can overwrite it.
    return ctypes.WinError(ctypes.get_last_error() if code is None else code)


def _bind(library, name, arguments, result):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


class _WindowsAPI:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows is required for P011 transport")
        setup = ctypes.WinDLL("setupapi", use_last_error=True)
        config = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        registry = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        devptr = ctypes.POINTER(SP_DEVINFO_DATA)
        self.SetupDiGetClassDevsW = _bind(setup, "SetupDiGetClassDevsW",
            [ctypes.POINTER(GUID), ctypes.c_wchar_p, HANDLE, DWORD], HANDLE)
        self.SetupDiEnumDeviceInfo = _bind(setup, "SetupDiEnumDeviceInfo",
            [HANDLE, DWORD, devptr], BOOL)
        self.SetupDiGetDeviceInstanceIdW = _bind(setup, "SetupDiGetDeviceInstanceIdW",
            [HANDLE, devptr, ctypes.c_wchar_p, DWORD, LPDWORD], BOOL)
        self.SetupDiGetDeviceRegistryPropertyW = _bind(setup,
            "SetupDiGetDeviceRegistryPropertyW",
            [HANDLE, devptr, DWORD, LPDWORD, ctypes.c_void_p, DWORD, LPDWORD], BOOL)
        self.SetupDiOpenDevRegKey = _bind(setup, "SetupDiOpenDevRegKey",
            [HANDLE, devptr, DWORD, DWORD, DWORD, DWORD], HANDLE)
        self.SetupDiDestroyDeviceInfoList = _bind(setup, "SetupDiDestroyDeviceInfoList",
            [HANDLE], BOOL)
        self.CM_Get_DevNode_Status = _bind(config, "CM_Get_DevNode_Status",
            [LPDWORD, LPDWORD, DWORD, DWORD], DWORD)
        self.RegQueryValueExW = _bind(registry, "RegQueryValueExW",
            [HANDLE, ctypes.c_wchar_p, LPDWORD, LPDWORD, ctypes.c_void_p, LPDWORD],
            ctypes.c_int32)
        self.RegCloseKey = _bind(registry, "RegCloseKey", [HANDLE], ctypes.c_int32)
        self.CreateFileW = _bind(kernel, "CreateFileW",
            [ctypes.c_wchar_p, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE],
            HANDLE)
        self.GetCommState = _bind(kernel, "GetCommState",
            [HANDLE, ctypes.POINTER(DCB)], BOOL)
        self.SetCommState = _bind(kernel, "SetCommState",
            [HANDLE, ctypes.POINTER(DCB)], BOOL)
        self.SetCommTimeouts = _bind(kernel, "SetCommTimeouts",
            [HANDLE, ctypes.POINTER(COMMTIMEOUTS)], BOOL)
        self.ClearCommError = _bind(kernel, "ClearCommError",
            [HANDLE, LPDWORD, ctypes.POINTER(COMSTAT)], BOOL)
        self.ReadFile = _bind(kernel, "ReadFile",
            [HANDLE, ctypes.c_void_p, DWORD, LPDWORD, ctypes.c_void_p], BOOL)
        self.WriteFile = _bind(kernel, "WriteFile",
            [HANDLE, ctypes.c_void_p, DWORD, LPDWORD, ctypes.c_void_p], BOOL)
        self.CloseHandle = _bind(kernel, "CloseHandle", [HANDLE], BOOL)


def _get_api():
    global _API
    if _API is None:
        _API = _WindowsAPI()
    return _API


def _property(api, info, node, number):
    buffer = ctypes.create_string_buffer(4096)
    kind, needed = DWORD(), DWORD()
    if not api.SetupDiGetDeviceRegistryPropertyW(
            info, ctypes.byref(node), number, ctypes.byref(kind), buffer,
            len(buffer), ctypes.byref(needed)):
        error = ctypes.get_last_error()
        if error in (13, 1168):  # Property absent, not an unreadable registry.
            return ""
        if error != 122 or not 0 < needed.value <= 65536:
            raise _win_error(error)
        buffer = ctypes.create_string_buffer(needed.value)
        if not api.SetupDiGetDeviceRegistryPropertyW(
                info, ctypes.byref(node), number, ctypes.byref(kind), buffer,
                len(buffer), ctypes.byref(needed)):
            raise _win_error()
    if kind.value not in (1, 2):
        return ""
    return bytes(buffer)[:needed.value].decode("utf-16-le", "strict").rstrip("\0")


def _port(api, info, node):
    # DICS_FLAG_GLOBAL=1, DIREG_DEV=1, KEY_QUERY_VALUE=1: never request write.
    key = api.SetupDiOpenDevRegKey(info, ctypes.byref(node), 1, 0, 1, 1)
    if key in (None, INVALID_HANDLE_VALUE):
        error = ctypes.get_last_error()
        if error in (2, 13, 1168):
            return ""
        raise _win_error(error)
    try:
        kind, size = DWORD(), DWORD()
        result = api.RegQueryValueExW(key, "PortName", None, ctypes.byref(kind),
                                     None, ctypes.byref(size))
        if result == 2:
            return ""
        if result:
            raise _win_error(result)
        if kind.value != 1 or not 2 <= size.value <= 1024:
            return ""
        buffer = ctypes.create_string_buffer(size.value)
        result = api.RegQueryValueExW(key, "PortName", None, ctypes.byref(kind),
                                     buffer, ctypes.byref(size))
        if result:
            raise _win_error(result)
        port = bytes(buffer)[:size.value].decode("utf-16-le", "strict").rstrip("\0")
        return port.upper() if _PORT_RE.fullmatch(port) else ""
    finally:
        # Preserve the original failure if cleanup also reports a failure.
        failed = sys.exc_info()[0] is not None
        result = api.RegCloseKey(key)
        if result and not failed:
            raise _win_error(result)


def inventory():
    """Read present VID 1782 / PID 4D00 or 4064 PnP nodes, without COM I/O.

    ``id`` is an internal identity value and must not be printed or put in public
    reports. ``started`` is DN_STARTED; ``problem`` is the CM problem code.
    A disconnected node or any unreadable metadata fails the current inventory
    rather than being treated as proof of a unique/usable download interface.
    """
    api = _get_api()
    info = api.SetupDiGetClassDevsW(None, None, None, 0x02 | 0x04)
    if info in (None, INVALID_HANDLE_VALUE):
        raise _win_error()
    nodes = []
    try:
        index = 0
        while True:
            data = SP_DEVINFO_DATA()
            data.cbSize = ctypes.sizeof(data)
            if not api.SetupDiEnumDeviceInfo(info, index, ctypes.byref(data)):
                error = ctypes.get_last_error()
                if error == 259:  # ERROR_NO_MORE_ITEMS
                    break
                raise _win_error(error)
            index += 1
            identity = ctypes.create_unicode_buffer(4096)
            needed = DWORD()
            if not api.SetupDiGetDeviceInstanceIdW(info, ctypes.byref(data),
                    identity, len(identity), ctypes.byref(needed)):
                raise _win_error()
            identifier = identity.value
            match = _PID_RE.search(identifier)
            if match is None:
                continue
            status, problem = DWORD(), DWORD()
            result = api.CM_Get_DevNode_Status(ctypes.byref(status),
                       ctypes.byref(problem), data.DevInst, 0)
            if result:
                raise TransportRefusal("PnP status unavailable (CONFIGRET %d)" % result)
            name = (_property(api, info, data, 12) or
                    _property(api, info, data, 0))
            nodes.append({"id": identifier, "devinst": int(data.DevInst),
                          "pid": match.group(1).upper(),
                          "port": _port(api, info, data),
                          "started": bool(status.value & 0x00000008),
                          "problem": int(problem.value), "name": name})
        return nodes
    finally:
        failed = sys.exc_info()[0] is not None
        if not api.SetupDiDestroyDeviceInfoList(info):
            error = ctypes.get_last_error()
            if not failed:
                raise _win_error(error)


def _identity(node):
    if not isinstance(node, dict):
        raise TransportRefusal("A PnP inventory node is required")
    if (node.get("pid") != "4D00" or not isinstance(node.get("id"), str)
            or not node["id"] or type(node.get("devinst")) is not int
            or node["devinst"] <= 0 or not isinstance(node.get("port"), str)
            or not _PORT_RE.fullmatch(node["port"])
            or node.get("started") is not True or node.get("problem") != 0):
        raise TransportRefusal("Only a started, problem-free 4D00 COM node is allowed")
    return (node["id"], node["devinst"], node["port"])


def _current_exact(expected):
    current = inventory()
    if any(node.get("pid") == "4064" for node in current):
        raise TransportRefusal("Normal-system and download nodes must not coexist")
    downloads = [node for node in current if node.get("pid") == "4D00"]
    if len(downloads) != 1:
        raise TransportRefusal("Exactly one present 4D00 node is required")
    actual = _identity(downloads[0])
    if actual != expected:
        raise TransportRefusal("Download node identity changed")


def _configure(api, handle):
    dcb = DCB()
    dcb.DCBlength = ctypes.sizeof(DCB)
    if not api.GetCommState(handle, ctypes.byref(dcb)):
        raise _win_error()
    dcb.DCBlength = ctypes.sizeof(DCB)
    dcb.BaudRate = 115200
    # fBinary=1, fDtrControl=ENABLE(1), fRtsControl=ENABLE(1).
    # fNull=0, no software/hardware handshaking, no parity or error substitution.
    dcb.flags = 0x00000001 | (1 << 4) | (1 << 12)
    dcb.wReserved = 0
    dcb.wReserved1 = 0
    dcb.ByteSize, dcb.Parity, dcb.StopBits = 8, 0, 0
    dcb.XonChar, dcb.XoffChar = b"\x11", b"\x13"
    dcb.ErrorChar, dcb.EofChar, dcb.EvtChar = b"\0", b"\0", b"\0"
    if not api.SetCommState(handle, ctypes.byref(dcb)):
        raise _win_error()
    # MAXDWORD/0/0 means immediate ReadFile; writes have a 1000 ms bound.
    timeouts = COMMTIMEOUTS(0xFFFFFFFF, 0, 0, 0, 1000)
    if not api.SetCommTimeouts(handle, ctypes.byref(timeouts)):
        raise _win_error()


def open_download(node):
    """Explicitly open only the current unique exact 4D00 identity, exclusive.

    No retry, purge, escape/control command, reset, or TX is performed here.
    """
    expected = _identity(node)
    _current_exact(expected)
    api = _get_api()
    # GENERIC_READ|GENERIC_WRITE, share=0, OPEN_EXISTING, synchronous I/O.
    handle = api.CreateFileW("\\\\.\\" + expected[2], 0xC0000000, 0,
                             None, 3, 0, None)
    if handle in (None, INVALID_HANDLE_VALUE):
        raise _win_error()
    try:
        _configure(api, handle)
        _current_exact(expected)
        serial = Serial(api, handle, expected, _CREATE_TOKEN)
        serial.pending()  # Validate the handle, retaining every queued RX byte.
        return serial
    except BaseException:
        # Keep the original WinError code/exception even if CloseHandle fails.
        api.CloseHandle(handle)
        raise


class Serial:
    def __init__(self, api, handle, identity, token):
        if token is not _CREATE_TOKEN:
            raise TransportRefusal("Use open_download with a fresh inventory node")
        self._api, self._handle, self._identity = api, handle, identity

    @property
    def is_open(self):
        return self._handle is not None

    def _handle_open(self):
        if not self.is_open:
            raise TransportRefusal("Download handle is closed")
        return self._handle

    def pending(self):
        handle = self._handle_open()
        errors, status = DWORD(), COMSTAT()
        if not self._api.ClearCommError(handle, ctypes.byref(errors), ctypes.byref(status)):
            raise _win_error()
        if errors.value:
            raise TransportRefusal("Serial error flags 0x%08x" % errors.value)
        return int(status.cbInQue)

    def read_available(self):
        count = min(self.pending(), MAX_READ)
        if count == 0:
            return b""
        buffer, received = ctypes.create_string_buffer(count), DWORD()
        if not self._api.ReadFile(self._handle_open(), buffer, count,
                                  ctypes.byref(received), None):
            raise _win_error()
        if received.value > count:
            raise TransportRefusal("ReadFile returned an invalid byte count")
        return buffer.raw[:received.value]

    def write(self, data):
        """Send one whitelisted handshake item once; never retry short writes."""
        if type(data) is not bytes or data not in ALLOWED_TX:
            raise TransportRefusal("TX is limited to FE82, one sync flag, and CONNECT")
        handle = self._handle_open()
        _current_exact(self._identity)
        if self.pending() != 0:
            raise TransportRefusal("Unread RX bytes prevent TX; preserve and inspect input")
        buffer, written = ctypes.create_string_buffer(data), DWORD()
        if not self._api.WriteFile(handle, buffer, len(data), ctypes.byref(written), None):
            raise _win_error()
        if written.value != len(data):
            raise TransportRefusal("Short WriteFile: attempt is consumed; do not retry")

    def close(self):
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        if not self._api.CloseHandle(handle):
            raise _win_error()


def self_check():
    """Pure HOST ABI checks; does not load DLLs, enumerate or open devices."""
    assert ctypes.sizeof(DCB) == 28
    assert ctypes.sizeof(COMMTIMEOUTS) == 20
    assert ctypes.sizeof(COMSTAT) == 12
    assert ctypes.sizeof(SP_DEVINFO_DATA) == (32 if ctypes.sizeof(HANDLE) == 8 else 28)
    assert DCB.flags.offset == 8 and DCB.ByteSize.offset == 18
    assert DCB.wReserved1.offset == 26
    return {"DCB": 28, "COMMTIMEOUTS": 20, "COMSTAT": 12,
            "SP_DEVINFO_DATA": ctypes.sizeof(SP_DEVINFO_DATA),
            "pointer_bytes": ctypes.sizeof(HANDLE)}


if __name__ == "__main__":
    import argparse
    import hashlib
    import json
    import pathlib

    parser = argparse.ArgumentParser(description="HOST ABI check; optional read-only PnP")
    parser.add_argument("--inventory", action="store_true", help="Read PnP metadata only")
    options = parser.parse_args()
    report = {"scope": "HOST_ONLY_NO_SERIAL_OPEN_NO_TX", "abi": self_check(),
              "source_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}
    if options.inventory:
        # Deliberately exclude instance ID, devinst and descriptive strings.
        report["pnp"] = [{key: node[key] for key in ("pid", "port", "started", "problem")}
                         for node in inventory()]
    print(json.dumps(report, ensure_ascii=False, indent=2))
