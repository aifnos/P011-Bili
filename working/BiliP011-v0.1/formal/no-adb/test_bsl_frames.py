"""Pure host tests; fixtures match 20260914-025933299 original RX captures."""

import binascii
import unittest

import bsl_frames as bsl


# Literal captured bytes, independent of the decoder's exported constants.
VERSION = bytes.fromhex(
    "7e 00 81 00 0c 53 50 52 44 34 3a 41 75 74 6f 44 00 fd 8b 7e"
)
ACK = bytes.fromhex("7e 00 80 00 00 3b 5a 7e")
VERIFY_ERROR = bytes.fromhex("7e 00 8b 00 00 cb ab 7e")


def make_frame(packet_type, payload):
    """Test frame builder uses the stdlib's independent CRC implementation."""
    covered = packet_type.to_bytes(2, "big") + len(payload).to_bytes(2, "big") + payload
    body = covered + binascii.crc_hqx(covered, 0).to_bytes(2, "big")
    escaped = body.replace(b"\x7d", b"\x7d\x5d").replace(b"\x7e", b"\x7d\x5e")
    return b"\x7e" + escaped + b"\x7e"


class BslFrameTests(unittest.TestCase):
    def assert_rejected(self, raw, reason=None):
        result = bsl.classify_version(raw)
        self.assertFalse(result["authorized"])
        self.assertIsNone(result["version"])
        if reason:
            self.assertEqual(result["reason"], reason)
        self.assertEqual(result["decoded"]["raw"], raw)
        return result["decoded"]

    def test_crc_reference_and_captured_frames(self):
        self.assertEqual(bsl.crc16(b"123456789"), 0x31C3)
        self.assertEqual(bsl.crc16(bytes(4)), 0)
        self.assertEqual(bsl.crc16(VERSION[1:-3]), 0xFD8B)
        self.assertEqual(bsl.crc16(ACK[1:-3]), 0x3B5A)

    def test_wire_constants_match_observed_fixtures(self):
        self.assertEqual(bsl.AUTOD_VERSION_FRAME, VERSION)
        self.assertEqual(bsl.ACK_FRAME, ACK)
        self.assertEqual(bsl.CONNECT_FRAME, bytes.fromhex("7e 00 00 00 00 00 00 7e"))
        frame = bsl.decode(bsl.CONNECT_FRAME)["frames"][0]
        self.assertTrue(frame["crc_ok"])
        self.assertEqual((frame["type"], frame["size"]), (0, 0))

    def test_exact_version_authorizes(self):
        result = bsl.classify_version(VERSION)
        self.assertTrue(result["authorized"])
        self.assertEqual(result["version"], "SPRD4:AutoD")
        frame = result["decoded"]["frames"][0]
        self.assertEqual((frame["type"], frame["size"]), (0x81, 12))
        self.assertEqual(frame["payload"], b"SPRD4:AutoD\x00")
        self.assertEqual(frame["received_crc"], 0xFD8B)
        self.assertEqual(frame["raw"], VERSION)

    def test_ack_decodes_but_never_authorizes_version(self):
        decoded = self.assert_rejected(ACK, "UNEXPECTED_FRAME")
        frame = decoded["frames"][0]
        self.assertTrue(frame["crc_ok"])
        self.assertEqual((frame["kind"], frame["type"], frame["size"]), ("ACK", 0x80, 0))

    def test_verify_error_is_not_autod(self):
        decoded = self.assert_rejected(VERIFY_ERROR, "UNEXPECTED_FRAME")
        self.assertTrue(decoded["frames"][0]["crc_ok"])
        self.assertEqual(decoded["frames"][0]["kind"], "UNKNOWN")

    def test_bad_crc_preserves_frame_and_rejects(self):
        damaged = bytearray(VERSION)
        damaged[-2] ^= 1
        decoded = self.assert_rejected(bytes(damaged), "CRC_MISMATCH")
        self.assertEqual(len(decoded["frames"]), 1)
        self.assertFalse(decoded["frames"][0]["crc_ok"])

    def test_every_truncated_version_is_rejected(self):
        for length in range(len(VERSION)):
            with self.subTest(length=length):
                self.assert_rejected(VERSION[:length])

    def test_half_frame_is_retained_in_wire_form(self):
        raw = VERSION[:-1]
        decoded = self.assert_rejected(raw, "INCOMPLETE_FRAME")
        self.assertEqual(decoded["half"], raw)
        self.assertEqual(decoded["trailing"], raw)

    def test_leading_junk_is_retained(self):
        decoded = self.assert_rejected(b"noise" + VERSION, "LEADING_JUNK")
        self.assertEqual(decoded["junk"], b"noise")
        self.assertEqual(decoded["frames"][0]["raw"], VERSION)

    def test_flagless_input_is_all_junk(self):
        decoded = self.assert_rejected(b"SPRD4:AutoD\x00", "LEADING_JUNK")
        self.assertEqual(decoded["junk"], b"SPRD4:AutoD\x00")
        self.assertFalse(decoded["frames"])

    def test_repeated_flags_and_repeated_identical_versions(self):
        for raw in (b"\x7e" + VERSION + b"\x7e", VERSION + VERSION, VERSION + VERSION[1:]):
            with self.subTest(raw=raw):
                self.assertTrue(bsl.classify_version(raw)["authorized"])

    def test_empty_and_idle_flags_do_not_authorize(self):
        self.assert_rejected(b"", "NO_VERSION_FRAME")
        self.assert_rejected(b"\x7e\x7e\x7e", "NO_VERSION_FRAME")

    def test_declared_length_mismatch_preserves_invalid_wire(self):
        raw = bytearray(VERSION)
        raw[4] = 13
        decoded = self.assert_rejected(bytes(raw), "INVALID_FRAME")
        self.assertEqual(decoded["invalid"], [{"raw": bytes(raw), "reason": "LENGTH_MISMATCH"}])

    def test_short_complete_frame_preserved(self):
        raw = b"\x7e\x00\x81\x7e"
        decoded = self.assert_rejected(raw, "INVALID_FRAME")
        self.assertEqual(decoded["invalid"], [{"raw": raw, "reason": "SHORT_FRAME"}])

    def test_dangling_escape_before_end_flag_rejected(self):
        raw = b"\x7e\x00\x81\x7d\x7e"
        decoded = self.assert_rejected(raw, "DANGLING_ESCAPE")
        self.assertTrue(decoded["dangling_escape"])
        self.assertEqual(decoded["invalid"][0]["raw"], raw)

    def test_unfinished_escape_retains_half(self):
        raw = VERSION[:-1] + b"\x7d"
        decoded = self.assert_rejected(raw, "DANGLING_ESCAPE")
        self.assertEqual(decoded["half"], raw)

    def test_escaped_bytes_decode_and_wire_is_preserved(self):
        payload = b"A\x7e\x7dB"
        raw = make_frame(0x93, payload)
        decoded = self.assert_rejected(raw, "UNEXPECTED_FRAME")
        frame = decoded["frames"][0]
        self.assertEqual(frame["payload"], payload)
        self.assertTrue(frame["crc_ok"])
        self.assertEqual(frame["raw"], raw)
        self.assertIn(b"\x7d\x5e", raw)
        self.assertIn(b"\x7d\x5d", raw)

    def test_other_banners_and_unknown_type_rejected(self):
        for packet_type, payload in (
            (0x81, b"SPRD4:AutoD"),
            (0x81, b"SPRD4:AutoD\x00\x00"),
            (0x81, b"SPRD3:AutoD\x00"),
            (0x93, b"SPRD4:AutoD\x00"),
            (0x81, b""),
        ):
            with self.subTest(packet_type=packet_type, payload=payload):
                self.assert_rejected(make_frame(packet_type, payload), "UNEXPECTED_FRAME")

    def test_clean_version_cannot_hide_mixed_frames(self):
        for extra in (ACK, VERIFY_ERROR, make_frame(0x82, b""), b"\x7e\x01\x7e"):
            for raw in (VERSION + extra, extra + VERSION):
                with self.subTest(raw=raw):
                    self.assert_rejected(raw)

    def test_clean_version_cannot_hide_partial_tail(self):
        decoded = self.assert_rejected(VERSION + b"\x7e\x00\x81", "INCOMPLETE_FRAME")
        self.assertEqual(decoded["half"], b"\x7e\x00\x81")

    def test_exact_raw_limit_and_oversize_abort(self):
        exact = VERSION + b"\x7e" * (16384 - len(VERSION))
        self.assertTrue(bsl.classify_version(exact)["authorized"])
        oversized = exact + b"\x7e"
        decoded = self.assert_rejected(oversized, "RAW_LIMIT_EXCEEDED")
        self.assertTrue(decoded["over_limit"])
        self.assertFalse(decoded["frames"])

    def test_huge_declared_length_rejects_without_payload_allocation(self):
        decoded = self.assert_rejected(bytes.fromhex("7e 00 81 ff ff 00 00 7e"), "INVALID_FRAME")
        self.assertEqual(decoded["invalid"][0]["reason"], "LENGTH_MISMATCH")

    def test_input_copy_and_bytes_like_contract(self):
        original = bytearray(VERSION)
        decoded = bsl.decode(original)
        original[1] = 0xFF
        self.assertEqual(decoded["raw"], VERSION)
        self.assertTrue(bsl.classify_version(memoryview(VERSION))["authorized"])
        for invalid in (None, "7e", [0x7E], 5):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                bsl.decode(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
