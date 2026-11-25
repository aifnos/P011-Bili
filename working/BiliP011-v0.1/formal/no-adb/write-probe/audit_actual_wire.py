"""Offline audit of saved TX/RX, independent of live runner result booleans."""
import collections
import hashlib
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from storage_read_codec import sum16


def frames(raw, direction):
    cursor = 0
    while cursor < len(raw):
        assert raw[cursor] == 0x7e
        code, size = struct.unpack_from('>HH', raw, cursor + 1)
        end = cursor + size + 8
        assert end <= len(raw) and raw[end - 1] == 0x7e
        body = raw[cursor + 1:end - 3]
        assert sum16(body, direction=direction) == int.from_bytes(raw[end - 3:end - 1], 'big')
        yield code, raw[cursor + 5:end - 3]
        cursor = end
    assert cursor == len(raw)


def audit(run, original_dir):
    tx = list(frames((run / 'device-probe/wire.tx.raw').read_bytes(), 'TX'))
    rx = list(frames((run / 'device-probe/wire.rx.raw').read_bytes(), 'RX'))
    assert len(tx) == len(rx) == 10790
    counts = collections.Counter(code for code, _ in tx)
    assert counts == {0x10: 10, 0x11: 8208, 0x12: 10, 1: 1, 2: 2560, 3: 1}
    expected_reads = [('user_partition', 'pgpt.bin', 32768), ('uboot', 'uboot.before.img', 1048576),
        ('miscdata', 'miscdata.before.img', 1048576), ('uboot_log', 'uboot_log.before.img', 4194304),
        ('sysdumpdb', 'sysdumpdb.before1.img', 10485760)]
    position = 0
    for phase in range(2):
        for name, filename, size in expected_reads:
            assert tx[position] == (0x10, name.encode('utf-16-le').ljust(72, b'\0') + struct.pack('<I', size))
            assert rx[position] == (0x80, b'')
            position += 1
            data = bytearray()
            for offset in range(0, size, 4096):
                assert tx[position] == (0x11, struct.pack('<II', 4096, offset))
                assert rx[position][0] == 0x93 and len(rx[position][1]) == 4096
                data.extend(rx[position][1])
                position += 1
            assert tx[position] == (0x12, b'') and rx[position] == (0x80, b'')
            position += 1
            assert data == (original_dir / filename).read_bytes()
        if phase == 0:
            assert tx[position] == (1, b's\0y\0s\0d\0u\0m\0p\0d\0b\0'.ljust(72, b'\0') + struct.pack('<I', 10485760))
            assert rx[position] == (0x80, b'')
            position += 1
            data = bytearray()
            for _ in range(2560):
                assert tx[position][0] == 2 and len(tx[position][1]) == 4096
                assert rx[position] == (0x80, b'')
                data.extend(tx[position][1])
                position += 1
            assert data == (original_dir / 'sysdumpdb.before1.img').read_bytes()
            assert tx[position] == (3, b'') and rx[position] == (0x80, b'')
            position += 1
    assert position == len(tx)
    return dict(status='OFFLINE_RAW_WIRE_AUDIT_PASSED', transactions=position,
        tx_counts={hex(code): count for code, count in sorted(counts.items())},
        checksums_verified=True, ordered_reads_equal_originals=True,
        write_payload_equal_complete_original=True, write_ack_count=2562,
        original_sha256=hashlib.sha256(data).hexdigest(), device_accessed=False)


if __name__ == '__main__':
    result = audit(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
    output = pathlib.Path(sys.argv[3])
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
