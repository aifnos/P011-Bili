"""New HOST-only codec tests, including original AutoD wire captures."""
import binascii
import pathlib
import re
import unittest
import zipfile

import storage_read_codec as codec


CAPTURE = pathlib.Path(__file__).resolve().parents[4] / '05_Logs/original-archives/P011-AutoD-PartitionList-20260914-031854984.zip'


def captured_packets():
    with zipfile.ZipFile(CAPTURE) as bundle:
        text = bundle.read('tool-stderr.txt').decode('utf-8')
    packets = []
    lines = iter(text.splitlines())
    for line in lines:
        match = re.fullmatch(r'(send|recv|read) \((\d+)\):', line)
        if not match:
            continue
        length, raw = int(match[2]), bytearray()
        while len(raw) < length:
            value = next(lines)
            if not value.strip():
                continue
            octets = value.split('|', 1)[0].split()
            if not all(re.fullmatch('[0-9a-fA-F]{2}', item) for item in octets):
                raise AssertionError('original raw capture HEX layout changed')
            raw.extend(int(item, 16) for item in octets)
        if len(raw) != length:
            raise AssertionError('original raw capture byte count changed')
        packets.append((match[1], bytes(raw)))
    return packets


def response(packet_type, payload, mode, wire_mode=codec.ESCAPED):
    """Independent HOST fixture maker; never a production outbound API."""
    body = packet_type.to_bytes(2, 'big') + len(payload).to_bytes(2, 'big') + payload
    if mode == codec.CRC16:
        check = binascii.crc_hqx(body, 0)
    else:
        if len(body) & 1:
            value = sum(int.from_bytes(body[n:n + 2], 'little') for n in range(0, len(body), 2))
            while value >> 16:
                value = (value & 0xffff) + (value >> 16)
            check = int.from_bytes((~value & 0xffff).to_bytes(2, 'little'), 'big')
        else:
            value = sum(int.from_bytes(body[n:n + 2], 'big') for n in range(0, len(body), 2))
            while value >> 16:
                value = (value & 0xffff) + (value >> 16)
            check = ~value & 0xffff
    body += check.to_bytes(2, 'big')
    if wire_mode == codec.ESCAPED:
        body = body.replace(b'\x7d', b'\x7d\x5d').replace(b'\x7e', b'\x7d\x5e')
    return b'\x7e' + body + b'\x7e'


class StorageReadCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = captured_packets()
        cls.crc_version = next(raw for direction, raw in cls.packets if direction == 'recv' and raw.hex().endswith('fd8b7e'))
        cls.sum_version = next(raw for direction, raw in cls.packets if direction == 'recv' and raw.hex().endswith('2bbf7e'))
        cls.crc_ack = bytes.fromhex('7e008000003b5a7e')
        cls.sum_ack = bytes.fromhex('7e00800000ff7f7e')
        cls.capability = next(raw for direction, raw in cls.packets if direction == 'recv' and len(raw) == 264)
        cls.read_start = next(raw for direction, raw in cls.packets if direction == 'send' and len(raw) == 84)
        cls.read_midst = next(raw for direction, raw in cls.packets if direction == 'send' and len(raw) == 16)

    def test_exact_original_stage_and_control_frames(self):
        self.assertEqual(codec.expect_autod_version(self.crc_version, codec.CRC16).payload, codec.AUTOD_PAYLOAD)
        self.assertEqual(codec.expect_autod_version(self.sum_version, codec.SUM16).checksum, 0x2bbf)
        self.assertEqual(codec.expect_ack(self.crc_ack, codec.CRC16).packet_type, 0x80)
        self.assertEqual(codec.expect_ack(self.sum_ack, codec.SUM16).packet_type, 0x80)
        sent = {raw for direction, raw in self.packets if direction == 'send'}
        for operation in ('CONNECT_CRC16', 'EXEC_BUILTIN_CRC16', 'CONNECT_SUM16',
                          'EXEC_BUILTIN_SUM16', 'KEEP_CHARGE_SUM16', 'DISABLE_TRANSCODE_SUM16'):
            with self.subTest(operation=operation):
                self.assertIn(codec.build_fixed(operation), sent)
        self.assertEqual(codec.build_fixed('EXEC_BUILTIN_CRC16').hex(), '7e00040000dcc07e')
        self.assertEqual(codec.build_fixed('EXEC_BUILTIN_SUM16').hex(), '7e00040000fffb7e')

    def test_exact_original_capability_and_read_layouts(self):
        frame = codec.expect_capabilities(self.capability)
        self.assertEqual(frame.payload, codec.OBSERVED_CAPABILITY_PAYLOAD)
        self.assertEqual(frame.checksum, 0xf75f)
        # GPT reads were intentionally not hexdumped by the original tool.
        # Its captured misc read independently proves the 76/8-byte layouts;
        # the future fixed GPT parameters come from pinned common.c.
        old_start = codec.decode(self.read_start, codec.SUM16)[0]
        old_midst = codec.decode(self.read_midst, codec.SUM16)[0]
        self.assertEqual(old_start.packet_type, 0x10)
        self.assertEqual(len(old_start.payload), 76)
        self.assertEqual(old_start.payload[:72].decode('utf-16-le').rstrip('\0'), 'misc')
        self.assertEqual(int.from_bytes(old_start.payload[72:], 'little'), 0x820)
        self.assertEqual(old_midst.packet_type, 0x11)
        self.assertEqual(old_midst.payload, bytes.fromhex('2000000000080000'))
        new_start = codec.decode(codec.build_fixed('READ_START_GPT'), codec.SUM16)[0]
        new_midst = codec.decode(codec.build_fixed('READ_MIDST_GPT', chunk_index=0), codec.SUM16)[0]
        self.assertEqual(new_start.body[:4], old_start.body[:4])
        self.assertEqual(new_midst.body[:4], old_midst.body[:4])
        self.assertEqual(new_start.payload[:72].decode('utf-16-le').rstrip('\0'), 'user_partition')
        self.assertEqual(new_start.payload[72:], bytes.fromhex('00800000'))
        self.assertEqual(new_midst.payload, bytes.fromhex('0010000000000000'))
        self.assertEqual(codec.build_fixed('READ_MIDST_GPT', chunk_index=0).hex(),
                         '7e001100080010000000000000ffd67e')

    def test_checksum_flavors_and_odd_length_direction(self):
        self.assertEqual(codec.crc16(b'123456789'), 0x31c3)
        self.assertEqual(codec.sum16(bytes.fromhex('010203'), direction='TX'), 0xfdfb)
        self.assertEqual(codec.sum16(bytes.fromhex('010203'), direction='RX'), 0xfbfd)
        self.assertEqual(codec.sum16(bytes.fromhex('0102'), direction='TX'), 0xfefd)
        for raw, mode in ((self.crc_version, codec.SUM16), (self.sum_version, codec.CRC16)):
            with self.assertRaisesRegex(codec.CodecError, 'CHECKSUM_MISMATCH'):
                codec.expect_autod_version(raw, mode)
        odd = response(0x93, b'\x03', codec.SUM16)
        self.assertEqual(codec.decode(odd, codec.SUM16)[0].payload, b'\x03')

    def test_every_version_split_and_truncation(self):
        for raw, mode in ((self.crc_version, codec.CRC16), (self.sum_version, codec.SUM16)):
            for cut in range(1, len(raw)):
                with self.subTest(mode=mode, cut=cut):
                    parser = codec.Decoder(mode)
                    self.assertEqual(parser.feed(raw[:cut]), ())
                    self.assertEqual(len(parser.feed(raw[cut:])), 1)
                    self.assertEqual(len(parser.finish()), 1)
                    self.assertEqual(parser.raw, raw)
                    with self.assertRaises(codec.CodecError):
                        codec.expect_autod_version(raw[:cut], mode)

    def test_unescaped_payload_flags_are_data_and_split_by_length(self):
        payload = bytes(range(256)) * 16
        raw = response(0x93, payload, codec.SUM16, codec.UNESCAPED)
        parser = codec.Decoder(codec.SUM16, codec.UNESCAPED)
        emitted = []
        for byte in raw:
            emitted.extend(parser.feed(bytes((byte,))))
        self.assertEqual(len(emitted), 1)
        self.assertEqual(parser.finish()[0].payload, payload)
        self.assertEqual(parser.raw, raw)
        self.assertEqual(codec.expect_read_chunk(raw).payload, payload)

    def test_escaped_payload_and_repeated_boundaries(self):
        payload = bytes((0x7d, 0x7e)) * (codec.GPT_CHUNK // 2)
        raw = response(0x93, payload, codec.SUM16)
        self.assertIn(b'\x7d\x5d\x7d\x5e', raw)
        self.assertEqual(codec.expect_read_chunk(raw, codec.ESCAPED).payload, payload)
        self.assertEqual(len(codec.decode(b'\x7e' + self.sum_ack + b'\x7e', codec.SUM16)), 1)

    def test_corrupt_length_crc_escape_and_mixed_responses_rejected(self):
        bad_crc = bytearray(self.crc_version)
        bad_crc[-2] ^= 1
        bad_length = bytearray(self.crc_version)
        bad_length[4] += 1
        for raw in (bytes(bad_crc), bytes(bad_length), b'junk' + self.crc_version,
                    self.crc_version[:-1] + b'\x7d\x00\x7e', self.crc_version + b'\x01'):
            with self.subTest(raw=raw.hex()):
                with self.assertRaises(codec.CodecError):
                    codec.expect_autod_version(raw, codec.CRC16)
        for raw in (self.sum_ack + self.sum_ack, self.sum_ack + self.sum_version,
                    response(0x80, b'\0', codec.SUM16), bytes.fromhex('7e008b0000ff747e')):
            with self.assertRaises(codec.CodecError):
                codec.expect_ack(raw, codec.SUM16)
        parser = codec.Decoder(codec.CRC16)
        with self.assertRaises(codec.CodecError):
            parser.feed(bytes(bad_crc))
        self.assertEqual(parser.raw, bytes(bad_crc))
        with self.assertRaisesRegex(codec.CodecError, 'ALREADY_FAILED'):
            parser.feed(self.crc_version)

    def test_unknown_capability_not_guessed(self):
        payload = bytearray(codec.OBSERVED_CAPABILITY_PAYLOAD)
        payload[0] = 5
        with self.assertRaisesRegex(codec.CodecError, 'UNSUPPORTED_CAPABILITY_LAYOUT'):
            codec.expect_capabilities(response(0x96, payload, codec.SUM16))
        with self.assertRaisesRegex(codec.CodecError, 'UNEXPECTED_CAPABILITY_FRAME'):
            codec.expect_capabilities(response(0x96, bytes(255), codec.SUM16))

    def test_raw_frame_payload_and_chunk_budgets(self):
        with self.assertRaisesRegex(codec.CodecError, 'RAW_LIMIT'):
            codec.Decoder(codec.SUM16).feed(b'\x7e' * (codec.MAX_RAW_BYTES + 1))
        with self.assertRaisesRegex(codec.CodecError, 'PAYLOAD_LIMIT'):
            codec.Decoder(codec.SUM16).feed(bytes.fromhex('7e00931001'))
        with self.assertRaisesRegex(codec.CodecError, 'FRAME_COUNT_LIMIT'):
            codec.decode(self.sum_ack * 17, codec.SUM16)
        for value in (-1, 8, True, 1.0, None):
            with self.assertRaisesRegex(codec.CodecError, 'CHUNK_INDEX'):
                codec.build_fixed('READ_MIDST_GPT', chunk_index=value)

    def test_public_builder_cannot_construct_write_erase_or_arbitrary_packet(self):
        for operation in ('START_DATA', 'MIDST_DATA', 'END_DATA', 'WRITE', 'ERASE',
                          'REPARTITION', 'ENABLE_WRITE_FLASH', 'READ_FLASH_INFO', 'RESET', 1, 0x0a):
            with self.assertRaisesRegex(codec.CodecError, 'NOT_IN_FIXED_READ_ALLOWLIST'):
                codec.build_fixed(operation)
        with self.assertRaises(TypeError):
            codec.build_fixed('READ_START_GPT', payload=b'system')
        with self.assertRaises(codec.CodecError):
            codec.build_fixed('EXEC_BUILTIN_SUM16', wire_mode=codec.UNESCAPED)

    def test_full_host_gate_crc_sum_capability_and_exact_gpt_budget(self):
        gate = codec.StorageReadGate(self.crc_version)
        chunks, operations = [], []
        while not gate.complete:
            request = gate.request()
            operations.append(request.operation)
            with self.assertRaises(codec.CodecError):
                gate.request()  # No second attempt before a response.
            if request.operation == 'SYNC_SUM16_VERSION':
                reply = self.sum_version
            elif request.operation == 'EXEC_BUILTIN_SUM16':
                reply = self.capability
            elif request.operation == 'READ_MIDST_GPT':
                payload = bytes(((request.chunk_index + value) & 0xff for value in range(codec.GPT_CHUNK)))
                chunks.append(payload)
                reply = response(0x93, payload, codec.SUM16, codec.UNESCAPED)
                self.assertEqual(request.response_wire_mode, codec.UNESCAPED)
            else:
                reply = self.crc_ack if request.response_checksum == codec.CRC16 else self.sum_ack
            gate.accept(reply)
        self.assertEqual(len(operations), 17)
        self.assertEqual(operations.count('READ_MIDST_GPT'), 8)
        self.assertEqual(gate.gpt_bytes, b''.join(chunks))
        self.assertEqual(len(gate.gpt_bytes), 0x8000)
        self.assertEqual(gate.wire_mode, codec.UNESCAPED)
        with self.assertRaises(codec.CodecError):
            gate.request()

    def test_wrong_stage_flavor_fails_closed_before_storage(self):
        gate = codec.StorageReadGate(self.crc_version)
        gate.request()
        gate.accept(self.crc_ack)
        gate.request()
        gate.accept(self.crc_ack)
        self.assertEqual(gate.request().operation, 'SYNC_SUM16_VERSION')
        with self.assertRaisesRegex(codec.CodecError, 'CHECKSUM_MISMATCH'):
            gate.accept(self.crc_version)
        self.assertTrue(gate.failed)
        with self.assertRaises(codec.CodecError):
            gate.request()
        with self.assertRaises(codec.CodecError):
            _ = gate.gpt_bytes


if __name__ == '__main__':
    unittest.main(verbosity=2)
