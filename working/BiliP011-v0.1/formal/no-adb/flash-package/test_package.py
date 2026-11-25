"""HOST tests against packaged code, never real USB. Do not invoke run.py install."""
import ctypes
import hashlib
import json
import pathlib
import random
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
PACKAGE = HERE / 'out/P011-Bili-NoADB-v1-20261014'
sys.path.insert(0, str(PACKAGE / 'app'))
import engine
import flash


def reply(code, payload=b'', mode=engine.codec.SUM16, escaped=False):
    body = struct.pack('>HH', code, len(payload)) + payload
    body += engine.codec._checksum(body, mode, 'RX').to_bytes(2, 'big')
    if escaped:
        body = b''.join(bytes((0x7d, b ^ 0x20)) if b in (0x7d, 0x7e) else bytes((b,)) for b in body)
    return b'\x7e' + body + b'\x7e'


class ScriptedSerial:
    def __init__(self, script, short=False):
        self.script = script
        self.short = short
        self.buffer = []
        self.calls = []
        self.closed = False
        self._api = types.SimpleNamespace(WriteFile=self.write_file)
    def _handle_open(self):
        return 123
    def write_file(self, handle, buffer, length, pointer, unused):
        raw = ctypes.string_at(buffer, length)
        self.calls.append(raw)
        expected, response = self.script.pop(0)
        assert raw == expected
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = length - 1 if self.short else length
        self.buffer = [response[:3], response[3:]] if response else []
        return True
    def pending(self):
        return sum(map(len, self.buffer))
    def read_available(self):
        return self.buffer.pop(0) if self.buffer else b''
    def close(self):
        self.closed = True


class PackageTests(unittest.TestCase):
    def test_checksum_matches_reference_even_odd_and_embedded_flags(self):
        random_source = random.Random(1941)
        for size in (0, 1, 2, 3, 7, 76, 255, 4096):
            raw = bytes(random_source.randrange(256) for _ in range(size))
            for direction in ('TX', 'RX'):
                self.assertEqual(engine.checksum(raw, direction), engine.codec.sum16(raw, direction=direction))

    def test_connect_exact_mode_and_stage_sequence(self):
        codec = engine.codec
        stages = [('CONNECT_CRC16', 0x80, b''), ('EXEC_BUILTIN_CRC16', 0x80, b''),
                  ('SYNC_SUM16_VERSION', 0x81, codec.AUTOD_PAYLOAD), ('CONNECT_SUM16', 0x80, b''),
                  ('KEEP_CHARGE_SUM16', 0x80, b''), ('EXEC_BUILTIN_SUM16', 0x96, codec.OBSERVED_CAPABILITY_PAYLOAD),
                  ('DISABLE_TRANSCODE_SUM16', 0x80, b'')]
        mode_serial = ScriptedSerial([(engine.MODE, b'')])
        script = [(b'\x7e', reply(0x81, codec.AUTOD_PAYLOAD, codec.CRC16, True))]
        script += [(codec.build_fixed(name), reply(code, data,
                    codec.CRC16 if name.endswith('CRC16') else codec.SUM16, True)) for name, code, data in stages]
        data_serial = ScriptedSerial(script)
        node = dict(id='HOST_ONLY', pid='4D00', started=True, problem=0, port='COM19', devinst=1)
        with tempfile.TemporaryDirectory() as temp, patch.object(engine.win, 'inventory', side_effect=[[], [node], [node]]), \
                patch.object(engine.win, 'open_download', side_effect=[mode_serial, data_serial]), \
                patch.object(engine.win, '_current_exact'), patch.object(engine.time, 'sleep'):
            session = engine.Session(temp)
            try:
                session.connect()
                self.assertTrue(session.state['fdl2_ready'])
                self.assertEqual(session.state['mode_attempts'], 1)
                self.assertEqual(session.state['open_attempts'], 2)
                self.assertEqual(data_serial.script, [])
                self.assertTrue(mode_serial.closed)
            finally:
                session.close()
        self.assertTrue(data_serial.closed)

    def test_short_write_cannot_retry(self):
        request = engine.select(1, 'system')
        fake = ScriptedSerial([(request, b'')], short=True)
        with tempfile.TemporaryDirectory() as temp:
            session = engine.Session(temp)
            session.serial = fake
            session.ensure_identity = lambda force=False: None
            try:
                with self.assertRaisesRegex(RuntimeError, '部分写入'):
                    session.exchange(request, 'WRITE_START')
                with self.assertRaisesRegex(RuntimeError, '禁止重试'):
                    session.exchange(request, 'WRITE_START')
                self.assertEqual(len(fake.calls), 1)
            finally:
                session.close()

    def test_nack_and_duplicate_response_stop(self):
        request = engine.select(1, 'system')
        for response in (reply(0x82), reply(0x80) + reply(0x80)):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                session = engine.Session(temp)
                fake = ScriptedSerial([(request, response)])
                session.serial = fake
                session.ensure_identity = lambda force=False: None
                try:
                    with self.assertRaises(RuntimeError):
                        session.exchange(request, 'WRITE_START')
                    self.assertTrue(session.failed)
                    self.assertEqual(len(fake.calls), 1)
                finally:
                    session.close()

    def test_delta_roundtrip_and_wrong_base_no_candidate(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(engine.SIZES, system=8192):
            root = pathlib.Path(temp)
            original = root / 'original.img'
            original.write_bytes(b'A' * 8192)
            payload = root / 'patch.bin'
            payload.write_bytes(b'P011DIF1' + struct.pack('<I', 1) + struct.pack('<QI', 4096, 4096) + b'B' * 4096)
            expected = b'A' * 4096 + b'B' * 4096
            flash.apply_delta(original, payload, root / 'good.img', hashlib.sha256(b'A' * 8192).hexdigest(), hashlib.sha256(expected).hexdigest())
            self.assertEqual((root / 'good.img').read_bytes(), expected)
            with self.assertRaisesRegex(RuntimeError, '底包'):
                flash.apply_delta(original, payload, root / 'bad.img', '0' * 64, '0' * 64)
            self.assertFalse((root / 'bad.img').exists())

    def test_overlap_delta_refused_before_copy(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(engine.SIZES, system=8192):
            root = pathlib.Path(temp)
            original = root / 'original.img'
            original.write_bytes(bytes(8192))
            payload = root / 'patch.bin'
            payload.write_bytes(b'P011DIF1' + struct.pack('<I', 2) +
                (struct.pack('<QI', 0, 4096) + bytes(4096)) * 2)
            with self.assertRaisesRegex(RuntimeError, '重叠'):
                flash.apply_delta(original, payload, root / 'out.img', hashlib.sha256(bytes(8192)).hexdigest(), '0' * 64)
            self.assertFalse((root / 'out.img').exists())

    def test_restore_requires_matching_device_gpt_and_prodnv(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(engine.SIZES, system=4096):
            root = pathlib.Path(temp)
            backup = root / 'one'
            backup.mkdir()
            (backup / 'system.before.img').write_bytes(bytes(4096))
            digest = hashlib.sha256(bytes(4096)).hexdigest()
            record = dict(schema='p011.system-backup.v1', device_identity='correct', prodnv_sha256='unit',
                          gpt_sha256='gpt', system_sha256=digest, uboot_sha256=flash.UBOOT_SHA)
            (backup / 'backup-complete.json').write_text(json.dumps(record))
            self.assertEqual(flash.select_backup(root, 'correct', 'unit', 'gpt', digest), backup / 'system.before.img')
            for identity, prodnv, gpt in [('other', 'unit', 'gpt'), ('correct', 'other', 'gpt'), ('correct', 'unit', 'other')]:
                with self.assertRaises(RuntimeError):
                    flash.select_backup(root, identity, prodnv, gpt, digest)

    def test_only_system_can_receive_write_start(self):
        for name in engine.SIZES:
            if name == 'system':
                continue
            with self.assertRaises(RuntimeError):
                engine.select(1, name)


class TransactionTests(unittest.TestCase):
    def run_transaction(self, wrong_system=False, after_changed=False):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'data').mkdir()
            gpt = (PACKAGE / 'data/reference-gpt.bin').read_bytes()
            (root / 'data/reference-gpt.bin').write_bytes(gpt)
            original, candidate = b'A' * 8192, b'A' * 4096 + b'B' * 4096
            old_sha, new_sha = hashlib.sha256(original).hexdigest(), hashlib.sha256(candidate).hexdigest()
            (root / 'data/system.delta').write_bytes(b'P011DIF1' + struct.pack('<I', 1) +
                struct.pack('<QI', 4096, 4096) + b'B' * 4096)
            data = {'user_partition': gpt, 'uboot': b'U' * 4096, 'prodnv': b'P' * 4096,
                    'miscdata': bytes(8192), 'uboot_log': b'L' * 4096,
                    'system': b'X' * 8192 if wrong_system else original}
            write_calls = []
            instances = []
            class MemorySession:
                def __init__(self, folder):
                    self.folder = pathlib.Path(folder)
                    self.state = dict(target_id_hash='f' * 64, write_started=False, host_handle_closed=False)
                    instances.append(self)
                def connect(self):
                    pass
                def read_partition(self, name, path):
                    raw = data[name]
                    if after_changed and 'after' in pathlib.Path(path).parts and name == 'miscdata':
                        raw = b'X' + raw[1:]
                    pathlib.Path(path).write_bytes(raw)
                    return hashlib.sha256(raw).hexdigest()
                def write_system(self, path, expected, allowed):
                    assert expected in allowed
                    assert (self.folder / 'write-scope.json').is_file()
                    backups = list((root / 'backups').rglob('backup-complete.json'))
                    assert len(backups) == 1
                    assert (backups[0].parent / 'system.before.img').read_bytes() == original
                    assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() == expected
                    self.state['write_started'] = True
                    write_calls.append(expected)
                    data['system'] = pathlib.Path(path).read_bytes()
                def close(self):
                    self.state['host_handle_closed'] = True
            apply_real, select_real = flash.apply_delta, flash.select_backup
            def apply(source, delta, dest):
                return apply_real(source, delta, dest, old_sha, new_sha)
            def select(root, identity, prodnv, gpt):
                return select_real(root, identity, prodnv, gpt, old_sha)
            with patch.object(flash, 'verify_package'), patch.object(flash.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=10**12)), \
                    patch.dict(engine.SIZES, {name: len(raw) for name, raw in data.items()}), \
                    patch.object(flash, 'BASE_SHA', old_sha), patch.object(flash, 'CANDIDATE_SHA', new_sha), \
                    patch.object(flash, 'UBOOT_SHA', hashlib.sha256(data['uboot']).hexdigest()), \
                    patch.object(flash, 'apply_delta', side_effect=apply), patch.object(flash, 'select_backup', side_effect=select):
                install_out = root / 'install'
                install_out.mkdir()
                installed = flash.execute('install', install_out, root, MemorySession)
                if wrong_system:
                    self.assertEqual(installed['status'], 'NOT_COMPLETE')
                    self.assertEqual(write_calls, [])
                elif after_changed:
                    self.assertEqual(installed['status'], 'NOT_COMPLETE')
                    self.assertIn('关联对象变化', installed['error'])
                    self.assertEqual(write_calls, [new_sha])
                else:
                    self.assertEqual(installed['status'], 'SYSTEM_IMAGE_WRITTEN_AND_FULL_READBACK_VERIFIED')
                    restore_out = root / 'restore'
                    restore_out.mkdir()
                    restored = flash.execute('restore', restore_out, root, MemorySession)
                    self.assertEqual(restored['status'], 'SYSTEM_IMAGE_WRITTEN_AND_FULL_READBACK_VERIFIED')
                    self.assertEqual(write_calls, [new_sha, old_sha])
                    self.assertEqual(data['system'], original)
                self.assertTrue(all(item.state['host_handle_closed'] for item in instances))
    def test_full_install_and_same_device_restore(self):
        self.run_transaction()
    def test_unsupported_system_stops_before_write(self):
        self.run_transaction(wrong_system=True)
    def test_collateral_change_does_not_report_success_or_auto_repair(self):
        self.run_transaction(after_changed=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
