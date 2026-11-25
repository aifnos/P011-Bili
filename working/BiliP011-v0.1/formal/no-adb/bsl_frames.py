"""Bounded, host-only decoding for the observed P011 CRC16 AutoD handshake.

No transport is opened here.  The constants describe the captured protocol;
decoding a banner or ACK does not establish firmware identity or flash access.
"""

MAX_RAW_BYTES = 16384
CONNECT_FRAME = bytes.fromhex("7e 00 00 00 00 00 00 7e")
AUTOD_VERSION_PAYLOAD = b"SPRD4:AutoD\x00"
AUTOD_VERSION_FRAME = bytes.fromhex(
    "7e 00 81 00 0c 53 50 52 44 34 3a 41 75 74 6f 44 00 fd 8b 7e"
)
ACK_FRAME = bytes.fromhex("7e 00 80 00 00 3b 5a 7e")


def crc16(data):
    """CRC-16/XMODEM: init 0, poly 0x1021, no reflection or final XOR."""
    crc = 0
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def decode(raw):
    """Return frames and all rejected/unconsumed wire bytes without I/O.

    Only bytes, bytearray, and memoryview inputs are accepted.  ``raw`` is an
    immutable copy.  ``junk`` precedes the first flag; ``half``/``trailing``
    contains an unfinished wire frame including its opening flag.  ``invalid``
    retains malformed complete frames.  A CRC mismatch remains a parsed frame
    with crc_ok=False.  Oversized input is retained but never parsed.
    """
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError("raw must be bytes, bytearray, or memoryview")
    raw = bytes(raw)
    result = {
        "raw": raw,
        "frames": [],
        "junk": b"",
        "half": b"",
        "trailing": b"",
        "dangling_escape": False,
        "invalid": [],
        "over_limit": len(raw) > MAX_RAW_BYTES,
    }
    if result["over_limit"]:
        return result

    start = None
    body = bytearray()
    escaped = False
    first_flag = raw.find(b"\x7e")
    if first_flag < 0:
        result["junk"] = raw
        return result
    result["junk"] = raw[:first_flag]

    for offset in range(first_flag, len(raw)):
        value = raw[offset]
        if value == 0x7E:
            if start is not None and offset > start + 1:
                wire = raw[start : offset + 1]
                if escaped:
                    result["dangling_escape"] = True
                    result["invalid"].append({"raw": wire, "reason": "DANGLING_ESCAPE"})
                elif len(body) < 6:
                    result["invalid"].append({"raw": wire, "reason": "SHORT_FRAME"})
                else:
                    size = (body[2] << 8) | body[3]
                    if len(body) != size + 6:
                        result["invalid"].append({"raw": wire, "reason": "LENGTH_MISMATCH"})
                    else:
                        packet_type = (body[0] << 8) | body[1]
                        payload = bytes(body[4:-2])
                        received_crc = (body[-2] << 8) | body[-1]
                        computed_crc = crc16(body[:-2])
                        kind = "UNKNOWN"
                        if packet_type == 0x0081 and payload == AUTOD_VERSION_PAYLOAD:
                            kind = "AUTOD_VERSION"
                        elif packet_type == 0x0080 and size == 0:
                            kind = "ACK"
                        result["frames"].append(
                            {
                                "raw": wire,
                                "body": bytes(body),
                                "type": packet_type,
                                "size": size,
                                "payload": payload,
                                "received_crc": received_crc,
                                "computed_crc": computed_crc,
                                "crc_ok": received_crc == computed_crc,
                                "kind": kind,
                            }
                        )
            # A flag terminates the previous frame and can start the next one.
            # Repeated idle flags contain no frame and are accepted.
            start = offset
            body.clear()
            escaped = False
        elif escaped:
            body.append(value ^ 0x20)
            escaped = False
        elif value == 0x7D:
            escaped = True
        else:
            body.append(value)

    if start is not None and start < len(raw) - 1:
        result["half"] = raw[start:]
        result["trailing"] = result["half"]
    result["dangling_escape"] = result["dangling_escape"] or escaped
    return result


def classify_version(raw):
    """Authorize one CONNECT only for clean, exact CRC16 AutoD version frames.

    This function makes no transmission.  It rejects ACKs, 008B errors, other
    banners, malformed frames, partial input, and any mixed response classes.
    The transport must independently verify the same live 1782:4D00 handle.
    """
    decoded = decode(raw)
    reason = "AUTOD_VERSION_CONFIRMED"
    if decoded["over_limit"]:
        reason = "RAW_LIMIT_EXCEEDED"
    elif decoded["junk"]:
        reason = "LEADING_JUNK"
    elif decoded["dangling_escape"]:
        reason = "DANGLING_ESCAPE"
    elif decoded["invalid"]:
        reason = "INVALID_FRAME"
    elif decoded["half"]:
        reason = "INCOMPLETE_FRAME"
    elif not decoded["frames"]:
        reason = "NO_VERSION_FRAME"
    elif any(not frame["crc_ok"] for frame in decoded["frames"]):
        reason = "CRC_MISMATCH"
    elif any(frame["kind"] != "AUTOD_VERSION" for frame in decoded["frames"]):
        reason = "UNEXPECTED_FRAME"
    authorized = reason == "AUTOD_VERSION_CONFIRMED"
    return {
        "authorized": authorized,
        "reason": reason,
        "version": "SPRD4:AutoD" if authorized else None,
        "decoded": decoded,
    }
