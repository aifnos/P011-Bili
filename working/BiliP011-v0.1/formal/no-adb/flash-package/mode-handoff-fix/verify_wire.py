"""Offline exact TX allowlist, RX checksum and complete read-payload review."""
import gzip
import hashlib
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'out/P011-Bili-NoADB-v5-open-20261014/app')]
import engine
codec = engine.codec
out = HERE / 'cold-read-v6-2'
events = [json.loads(line) for line in gzip.decompress((out / 'wire.events.jsonl.gz').read_bytes()).splitlines() if line]
attempts = [e for e in events if e['kind'] == 'ATTEMPT']
responses = {e['number']: e for e in events if e['kind'] == 'RESPONSE'}
tx, rx = [gzip.decompress((out / ('wire.' + kind + '.raw.gz')).read_bytes()) for kind in ('tx', 'rx')]
expected = [('MODE', engine.MODE, None, None, None),
            ('SYNC_CRC', b'\x7e', codec.CRC16, 0x81, codec.AUTOD_PAYLOAD)]
for name, code, payload in [('CONNECT_CRC16', 0x80, b''), ('EXEC_BUILTIN_CRC16', 0x80, b''),
    ('SYNC_SUM16_VERSION', 0x81, codec.AUTOD_PAYLOAD), ('CONNECT_SUM16', 0x80, b''),
    ('KEEP_CHARGE_SUM16', 0x80, b''), ('EXEC_BUILTIN_SUM16', 0x96, codec.OBSERVED_CAPABILITY_PAYLOAD),
    ('DISABLE_TRANSCODE_SUM16', 0x80, b'')]:
    expected.append((name, codec.build_fixed(name), codec.CRC16 if name.endswith('CRC16') else codec.SUM16, code, payload))
for part, filename in [('user_partition', 'gpt.bin'), ('uboot', 'uboot.bin')]:
    image = (out / filename).read_bytes()
    assert len(image) == engine.SIZES[part]
    expected.append(('READ_START:' + part, engine.select(0x10, part), codec.SUM16, 0x80, b''))
    for offset in range(0, len(image), engine.STEP):
        expected.append(('READ:' + part + ':' + str(offset),
            engine.packet(0x11, struct.pack('<II', engine.STEP, offset)), codec.SUM16, 0x93, image[offset:offset+engine.STEP]))
    expected.append(('READ_END:' + part, engine.packet(0x12), codec.SUM16, 0x80, b''))
assert len(attempts) == len(expected) and len(responses) == len(expected)-1
txoff = rxoff = 0
for number, (attempt, item) in enumerate(zip(attempts, expected), 1):
    label, wire, mode, code, payload = item
    assert attempt['number'] == number and attempt['label'] == label and attempt['bytes'] == len(wire)
    assert tx[txoff:txoff+len(wire)] == wire
    txoff += len(wire)
    if number == 1:
        continue
    size = responses[number]['bytes']
    response = rx[rxoff:rxoff+size]
    rxoff += size
    decoder = codec.Decoder(mode, codec.UNESCAPED if label.startswith('READ') else codec.ESCAPED)
    decoder.feed(response)
    frames = decoder.finish()
    assert len(frames) == 1 and frames[0].packet_type == code and frames[0].payload == payload
assert txoff == len(tx) and rxoff == len(rx)
result = dict(status='ALL_RAW_TX_RX_REVIEWED', tx_requests=len(expected), rx_responses=len(responses),
    tx_bytes=len(tx), rx_bytes=len(rx), mode_requests=1, initial_crc_sync_requests=1,
    write_erase_reset_requests=0, external_loader_requests=0,
    read_partitions=['user_partition','uboot'], all_read_bytes_equal_saved_files=True,
    engine_sha256=hashlib.sha256((HERE / 'engine.py').read_bytes()).hexdigest())
(HERE / 'wire-review.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
