"""Pure HOST codec/gate for one proposed built-in AutoD + 32 KiB GPT read.

No USB/serial/ADB imports, execution, files, clocks, or device side effects.
Builders expose named fixed requests only, never a command number/address/data
API. EXEC and charger/transcode settings remain active operations requiring a
separate authorized hardware runner; constructing their bytes authorizes none.

Wire definitions checked against the 2026-09-14 captured partition-list raw and:
https://raw.githubusercontent.com/TomKing062/spreadtrum_flash/2a202404a7512026d146b62624f089aceb408520/common.c
https://raw.githubusercontent.com/TomKing062/spreadtrum_flash/2a202404a7512026d146b62624f089aceb408520/spd_dump.c
TX SUM uses CHK_FIXZERO=1; RX SUM uses CHK_ORIG=2. Odd-length handling differs.
Capability support is deliberately limited to the exact observed 256-byte body.
This is not a complete storage client, permission test, writer, or GPT validator.
"""
from dataclasses import dataclass


CRC16 = 'CRC16'
SUM16 = 'SUM16'
ESCAPED = 'ESCAPED'
UNESCAPED = 'UNESCAPED'
GPT_LENGTH = 0x8000
GPT_CHUNK = 0x1000
GPT_CHUNKS = GPT_LENGTH // GPT_CHUNK
MAX_PAYLOAD = GPT_CHUNK
MAX_RAW_BYTES = 2 * (GPT_LENGTH + 16 * 8)
MAX_FRAMES = 16
AUTOD_PAYLOAD = b'SPRD4:AutoD\0'
OBSERVED_CAPABILITY_PAYLOAD = bytes.fromhex('04 00 00 00 01 00 00 00 02 02 00 00 00 08 00 00') + bytes(240)


class CodecError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise CodecError(message)


def _bytes(value):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError('wire data must be bytes, bytearray, or memoryview')
    return bytes(value)


def crc16(data):
    """CRC-16/XMODEM, initial 0, polynomial 0x1021, no final XOR."""
    value = 0
    for octet in _bytes(data):
        value ^= octet << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xffff
    return value


def sum16(data, *, direction):
    """Exact pinned spd_checksum, including distinct TX/RX odd-byte rules."""
    _require(direction in ('TX', 'RX'), 'UNSUPPORTED_SUM_DIRECTION')
    data = _bytes(data)
    value = sum(data[n] | data[n + 1] << 8 for n in range(0, len(data) - 1, 2))
    remaining = len(data) & 1
    if remaining:
        value += data[-1]
    value = (value >> 16) + (value & 0xffff)
    value += value >> 16
    value = ~value & 0xffff
    final = 1 if direction == 'TX' else 2
    if remaining < final:
        value = (value >> 8) | ((value & 0xff) << 8)
    return value


def _checksum(data, mode, direction):
    _require(mode in (CRC16, SUM16), 'UNSUPPORTED_CHECKSUM_MODE')
    return crc16(data) if mode == CRC16 else sum16(data, direction=direction)


@dataclass(frozen=True)
class Frame:
    packet_type: int
    payload: bytes
    wire: bytes
    body: bytes
    checksum: int
    checksum_mode: str
    wire_mode: str


class Decoder:
    """Incremental strict decoder with sticky failure and exact raw retention.

    feed returns only newly completed frames. finish rejects incomplete frames;
    idle/repeated boundary flags are accepted. In UNESCAPED mode the length
    header, not in-payload 7E/7D bytes, determines the trailing boundary.
    """
    def __init__(self, checksum_mode, wire_mode=ESCAPED):
        _require(checksum_mode in (CRC16, SUM16), 'UNSUPPORTED_CHECKSUM_MODE')
        _require(wire_mode in (ESCAPED, UNESCAPED), 'UNSUPPORTED_WIRE_MODE')
        self.checksum_mode, self.wire_mode = checksum_mode, wire_mode
        self._raw, self._wire, self._body = bytearray(), bytearray(), bytearray()
        self._head, self._escape, self._expected = False, False, None
        self.frames = []
        self.error = None

    @property
    def raw(self):
        return bytes(self._raw)

    def _fail(self, reason):
        self.error = reason
        raise CodecError(reason)

    def _append_body(self, octet):
        self._body.append(octet)
        if len(self._body) == 4:
            size = int.from_bytes(self._body[2:4], 'big')
            if size > MAX_PAYLOAD:
                self._fail('PAYLOAD_LIMIT_EXCEEDED')
            self._expected = size + 6
        if self._expected is not None and len(self._body) > self._expected:
            self._fail('LENGTH_MISMATCH')

    def _complete(self):
        if len(self._body) < 6 or len(self._body) != self._expected:
            self._fail('LENGTH_MISMATCH')
        if len(self.frames) >= MAX_FRAMES:
            self._fail('FRAME_COUNT_LIMIT_EXCEEDED')
        received = int.from_bytes(self._body[-2:], 'big')
        expected = _checksum(self._body[:-2], self.checksum_mode, 'RX')
        if received != expected:
            self._fail('CHECKSUM_MISMATCH')
        frame = Frame(int.from_bytes(self._body[:2], 'big'), bytes(self._body[4:-2]),
                      bytes(self._wire), bytes(self._body), received, self.checksum_mode, self.wire_mode)
        self.frames.append(frame)
        self._body.clear()
        self._wire = bytearray(b'\x7e')  # Boundary can also start the next frame.
        self._expected, self._escape = None, False
        return frame

    def feed(self, data):
        if self.error:
            raise CodecError('DECODER_ALREADY_FAILED: ' + self.error)
        data = _bytes(data)
        if len(self._raw) + len(data) > MAX_RAW_BYTES:
            self._fail('RAW_LIMIT_EXCEEDED')
        self._raw.extend(data)
        completed = []
        for octet in data:
            if not self._head:
                if octet != 0x7e:
                    self._fail('LEADING_JUNK')
                self._head = True
                self._wire = bytearray(b'\x7e')
                continue
            if self.wire_mode == ESCAPED:
                self._wire.append(octet)
                if octet == 0x7e:
                    if self._escape:
                        self._fail('DANGLING_ESCAPE')
                    if not self._body:
                        self._wire = bytearray(b'\x7e')
                        continue
                    completed.append(self._complete())
                elif self._escape:
                    if octet not in (0x5d, 0x5e):
                        self._fail('INVALID_ESCAPE')
                    self._escape = False
                    self._append_body(octet ^ 0x20)
                elif octet == 0x7d:
                    self._escape = True
                else:
                    self._append_body(octet)
            else:
                if not self._body and octet == 0x7e:
                    self._wire = bytearray(b'\x7e')
                    continue
                self._wire.append(octet)
                if self._expected is not None and len(self._body) == self._expected:
                    if octet != 0x7e:
                        self._fail('MISSING_END_FLAG')
                    completed.append(self._complete())
                else:
                    self._append_body(octet)
        return tuple(completed)

    def finish(self):
        if self.error:
            raise CodecError('DECODER_ALREADY_FAILED: ' + self.error)
        if self._body or self._escape:
            self._fail('INCOMPLETE_FRAME')
        return tuple(self.frames)


def decode(data, checksum_mode, wire_mode=ESCAPED):
    decoder = Decoder(checksum_mode, wire_mode)
    decoder.feed(data)
    return decoder.finish()


def _single(data, checksum_mode, wire_mode):
    frames = decode(data, checksum_mode, wire_mode)
    _require(len(frames) == 1, 'EXACTLY_ONE_RESPONSE_REQUIRED')
    return frames[0]


def expect_autod_version(data, checksum_mode, wire_mode=ESCAPED):
    frame = _single(data, checksum_mode, wire_mode)
    _require(frame.packet_type == 0x81 and frame.payload == AUTOD_PAYLOAD, 'UNEXPECTED_AUTOD_VERSION')
    return frame


def expect_ack(data, checksum_mode, wire_mode=ESCAPED):
    frame = _single(data, checksum_mode, wire_mode)
    _require(frame.packet_type == 0x80 and frame.payload == b'', 'UNEXPECTED_ACK')
    return frame


def expect_capabilities(data):
    frame = _single(data, SUM16, ESCAPED)
    _require(frame.packet_type == 0x96 and len(frame.payload) == 256, 'UNEXPECTED_CAPABILITY_FRAME')
    _require(frame.payload == OBSERVED_CAPABILITY_PAYLOAD, 'UNSUPPORTED_CAPABILITY_LAYOUT')
    return frame


def expect_read_chunk(data, wire_mode=UNESCAPED):
    frame = _single(data, SUM16, wire_mode)
    _require(frame.packet_type == 0x93 and len(frame.payload) == GPT_CHUNK, 'UNEXPECTED_READ_CHUNK')
    return frame


def _packet(packet_type, payload, checksum_mode, wire_mode):
    """Internal primitive; public builders below never accept type/payload."""
    _require(wire_mode in (ESCAPED, UNESCAPED), 'UNSUPPORTED_WIRE_MODE')
    body = packet_type.to_bytes(2, 'big') + len(payload).to_bytes(2, 'big') + payload
    body += _checksum(body, checksum_mode, 'TX').to_bytes(2, 'big')
    if wire_mode == ESCAPED:
        body = b''.join(bytes((0x7d, value ^ 0x20)) if value in (0x7d, 0x7e)
                        else bytes((value,)) for value in body)
    return b'\x7e' + body + b'\x7e'


def build_fixed(operation, *, chunk_index=None, wire_mode=ESCAPED):
    """Only fixed stage items and eight 4096-byte reads of user_partition+0."""
    control = {
        'CONNECT_CRC16': (0, CRC16), 'EXEC_BUILTIN_CRC16': (4, CRC16),
        'CONNECT_SUM16': (0, SUM16), 'EXEC_BUILTIN_SUM16': (4, SUM16),
        'KEEP_CHARGE_SUM16': (0x13, SUM16), 'DISABLE_TRANSCODE_SUM16': (0x21, SUM16),
    }
    _require(wire_mode in (ESCAPED, UNESCAPED), 'UNSUPPORTED_WIRE_MODE')
    if operation in control:
        _require(chunk_index is None and wire_mode == ESCAPED, 'INVALID_FIXED_CONTROL_ARGUMENT')
        packet_type, mode = control[operation]
        return _packet(packet_type, b'', mode, ESCAPED)
    if operation == 'SYNC_SUM16_VERSION':
        _require(chunk_index is None and wire_mode == ESCAPED, 'INVALID_FIXED_SYNC_ARGUMENT')
        return b'\x7e'
    if operation == 'READ_START_GPT':
        _require(chunk_index is None, 'INVALID_FIXED_READ_ARGUMENT')
        name = 'user_partition'.encode('utf-16-le').ljust(72, b'\0')
        return _packet(0x10, name + GPT_LENGTH.to_bytes(4, 'little'), SUM16, wire_mode)
    if operation == 'READ_MIDST_GPT':
        _require(type(chunk_index) is int and 0 <= chunk_index < GPT_CHUNKS, 'GPT_CHUNK_INDEX_OUT_OF_RANGE')
        payload = GPT_CHUNK.to_bytes(4, 'little') + (chunk_index * GPT_CHUNK).to_bytes(4, 'little')
        return _packet(0x11, payload, SUM16, wire_mode)
    if operation == 'READ_END_GPT':
        _require(chunk_index is None, 'INVALID_FIXED_READ_ARGUMENT')
        return _packet(0x12, b'', SUM16, wire_mode)
    raise CodecError('OPERATION_NOT_IN_FIXED_READ_ALLOWLIST')


@dataclass(frozen=True)
class Request:
    operation: str
    data: bytes
    response_checksum: str
    response_wire_mode: str
    chunk_index: object = None


class StorageReadGate:
    """HOST-only sequencing proof, not a transport or permission to execute.

    request() consumes that stage's one attempt before a future writer would
    run. Any rejected response permanently fails the gate. Caller must also
    stop on write/read/log errors and independently bind a current device.
    """
    _STAGES = (
        ('CONNECT_CRC16', 'ACK', CRC16), ('EXEC_BUILTIN_CRC16', 'ACK', CRC16),
        ('SYNC_SUM16_VERSION', 'VERSION', SUM16), ('CONNECT_SUM16', 'ACK', SUM16),
        ('KEEP_CHARGE_SUM16', 'ACK', SUM16), ('EXEC_BUILTIN_SUM16', 'CAPABILITIES', SUM16),
        ('DISABLE_TRANSCODE_SUM16', 'ACK', SUM16), ('READ_START_GPT', 'ACK', SUM16),
    ) + tuple(('READ_MIDST_GPT', 'READ', SUM16) for _ in range(GPT_CHUNKS)) + (('READ_END_GPT', 'ACK', SUM16),)

    def __init__(self, initial_crc_version):
        expect_autod_version(initial_crc_version, CRC16)
        self.index = 0
        self.awaiting_response = False
        self.failed = False
        self.wire_mode = ESCAPED
        self._gpt = bytearray()

    @property
    def complete(self):
        return not self.failed and self.index == len(self._STAGES)

    @property
    def gpt_bytes(self):
        _require(self.complete and len(self._gpt) == GPT_LENGTH, 'GPT_READ_NOT_COMPLETE')
        return bytes(self._gpt)

    def request(self):
        _require(not self.failed and not self.complete and not self.awaiting_response, 'STAGE_REQUEST_NOT_ALLOWED')
        operation, _, checksum = self._STAGES[self.index]
        chunk = self.index - 8 if operation == 'READ_MIDST_GPT' else None
        data = build_fixed(operation, chunk_index=chunk, wire_mode=self.wire_mode)
        self.awaiting_response = True
        return Request(operation, data, checksum, self.wire_mode, chunk)

    def accept(self, response):
        try:
            _require(not self.failed and not self.complete and self.awaiting_response, 'STAGE_RESPONSE_NOT_ALLOWED')
            operation, expected, checksum = self._STAGES[self.index]
            if expected == 'ACK':
                expect_ack(response, checksum, self.wire_mode)
            elif expected == 'VERSION':
                expect_autod_version(response, checksum, self.wire_mode)
            elif expected == 'CAPABILITIES':
                expect_capabilities(response)
            else:
                frame = expect_read_chunk(response, self.wire_mode)
                _require(len(self._gpt) + len(frame.payload) <= GPT_LENGTH, 'GPT_LENGTH_BUDGET_EXCEEDED')
                self._gpt.extend(frame.payload)
            if operation == 'DISABLE_TRANSCODE_SUM16':
                self.wire_mode = UNESCAPED
            self.index += 1
            self.awaiting_response = False
        except Exception:
            self.failed = True
            raise
