"""HOST fixtures and retained historical captures only; no hardware imports."""
import pathlib
import struct
import unittest
import uuid

import gpt_readback as g


def fixture():
    raw = bytearray(g.CAPTURE_BYTES)
    start = 1024
    for index, (name, first, last) in enumerate((('uboot', 2048, 4095), ('system', 4096, 8191))):
        at = start + index * 128
        raw[at:at + 16] = uuid.UUID(int=1).bytes_le
        raw[at + 16:at + 32] = uuid.UUID(int=index + 100).bytes_le
        struct.pack_into('<QQQ', raw, at + 32, first, last, 0)
        encoded = name.encode('utf-16-le')
        raw[at + 56:at + 56 + len(encoded)] = encoded
    raw[512:512 + g.HEADER.size] = g.HEADER.pack(
        b'EFI PART', 0x10000, 92, 0, 0, 1, 32767, 34, 32734,
        uuid.UUID(int=50).bytes_le, 2, 128, 128, 0)
    return reseal(raw)


def reseal(raw):
    raw = bytearray(raw)
    struct.pack_into('<I', raw, 512 + 88, g.crc32(raw[1024:1024 + 16384]))
    struct.pack_into('<I', raw, 512 + 16, 0)
    struct.pack_into('<I', raw, 512 + 16, g.crc32(raw[512:512 + 92]))
    return bytes(raw)


class GPTTests(unittest.TestCase):
    def test_valid_fixture_and_independent_capacity(self):
        result = g.parse_primary(fixture(), 32768 * 512)
        self.assertEqual([p['name'] for p in result['partitions']], ['uboot', 'system'])
        self.assertTrue(result['media_capacity_independently_verified'])
        self.assertFalse(result['backup_gpt_verified'])
        with self.assertRaises(g.InvalidGPT):
            g.parse_primary(fixture(), 32769 * 512)

    def test_historical_primary_captures_validate_without_hardware(self):
        project = pathlib.Path(__file__).resolve().parents[4]
        for relative in ('06_Firmware/metadata/pgpt.bin',
                         '06_Firmware/backups/v2.4.0-20260923-162730/gpt-primary-64sectors.bin'):
            with self.subTest(capture=relative):
                result = g.parse_primary((project / relative).read_bytes())
                self.assertEqual(result['partition_count'], 40)
                system = next(p for p in result['partitions'] if p['name'] == 'system')
                self.assertEqual(system['index'], 29)
                self.assertEqual(system['size_bytes'], 1073741824)

    def test_corruption_of_either_crc_is_rejected(self):
        for at in (512 + 56, 1024 + 56):
            raw = bytearray(fixture())
            raw[at] ^= 1
            with self.subTest(offset=at), self.assertRaises(g.InvalidGPT):
                g.parse_primary(bytes(raw))

    def test_logically_invalid_ranges_even_with_valid_crcs(self):
        for first, last in ((2048, 5000), (33, 2000), (5000, 4999), (32734, 32735)):
            raw = bytearray(fixture())
            struct.pack_into('<QQ', raw, 1024 + 128 + 32, first, last)
            with self.subTest(first=first, last=last), self.assertRaises(g.InvalidGPT):
                g.parse_primary(reseal(raw))

    def test_duplicate_names_and_guids_rejected(self):
        for start, length in ((16, 16), (56, 72)):
            raw = bytearray(fixture())
            raw[1024 + 128 + start:1024 + 128 + start + length] = raw[1024 + start:1024 + start + length]
            with self.subTest(start=start), self.assertRaises(g.InvalidGPT):
                g.parse_primary(reseal(raw))

    def test_fixed_capture_and_entry_array_bounds(self):
        for raw in (fixture()[:-1], fixture() + b'\0'):
            with self.assertRaises(g.InvalidGPT):
                g.parse_primary(raw)
        for offset, value in ((72, 64), (80, 4096), (84, 256)):
            raw = bytearray(fixture())
            struct.pack_into('<Q' if offset == 72 else '<I', raw, 512 + offset, value)
            with self.subTest(offset=offset), self.assertRaises(g.InvalidGPT):
                g.parse_primary(reseal(raw))

    def test_malformed_utf16_and_nonzero_padding_rejected(self):
        for value in (b'\x00\xd8', 'a\0b'.encode('utf-16-le')):
            raw = bytearray(fixture())
            raw[1024 + 56:1024 + 128] = value + bytes(72 - len(value))
            with self.subTest(value=value.hex()), self.assertRaises(g.InvalidGPT):
                g.parse_primary(reseal(raw))


if __name__ == '__main__':
    unittest.main(verbosity=2)
