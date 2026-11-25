"""One original-byte sysdumpdb rewrite in an already established FDL2 session.

Fixed ordinary START/MIDST/END only. No initialization, loader, retry, erase,
repartition, reset, write-enable or other partition writer. Import is HOST only.
Wire source: TomKing062/spreadtrum_flash commit 2a202404, common.c 768-786,
817-880, 1266-1291. Same-byte readback does not prove changed-bit persistence.
"""
import argparse
import ctypes
import hashlib
import json
import os
import pathlib
import struct
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))
import storage_read_codec as codec
import read_preflight as pre

SIZE = 0xa00000
STEP = 0x1000
UBOOT_SHA = '3d8bfddf254aad299fe5b7d4f7f73cb0e94736c5e5c2f1e7407cba5688db11d0'
FILES = {'user_partition': ('pgpt.bin', 32768, 'gpt'),
         'uboot': ('uboot.before.img', 0x100000, 'uboot'),
         'miscdata': ('miscdata.before.img', 0x100000, 'miscdata'),
         'uboot_log': ('uboot_log.before.img', 0x400000, 'uboot_log'),
         'sysdumpdb': ('sysdumpdb.before1.img', SIZE, 'sysdump_before1')}
SOURCE_PATHS = {p.name: p for p in (
    pathlib.Path(__file__), BASE / 'run_sysdump_rewrite.py', BASE / 'read_preflight.py',
    BASE.parent / 'storage_read_codec.py', BASE.parent / 'win32_download_transport.py',
    BASE.parent / 'gpt_readback.py', BASE.parent / 'run_early_mode_probe.py')}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def source_hashes():
    return {name: sha(p.read_bytes()) for name, p in SOURCE_PATHS.items()}


def load_preflight(folder):
    folder = pathlib.Path(folder)
    require(folder.is_dir() and not folder.is_symlink(), 'preflight must be a regular directory')
    result_raw = (folder / 'read-result.json').read_bytes()
    result = json.loads(result_raw)
    require(result['schema'] == 'p011.autod.read-preflight.v1' and
            result['status'] == 'READ_PREFLIGHT_COMPLETE_VERIFIED' and
            result['wrapper_exit'] == 0 and result['sysdump_same'] is True,
            'fresh complete fixed-read preflight required')
    child = result['child']
    require(child['host_handle_closed'] and child['host_process_stopped'] and
            child['streams_complete'] and not child['timeout'] and not child['interrupted'] and
            not child['capture_errors'] and not child['termination_error'], 'preflight child not closed cleanly')
    require(result['sources']['before'] == result['sources']['after'] and
            not result['sources']['changed'] and result['tool'] == result['tool_after'] == pre.tool_manifest(),
            'preflight source/tool changed')
    for name, expected in result['sources']['after'].items():
        require(name in SOURCE_PATHS and sha(SOURCE_PATHS[name].read_bytes()) == expected and
                sha((folder / 'sources' / name).read_bytes()) == expected, 'preflight source snapshot mismatch')
    originals = {}
    for name, (filename, size, key) in FILES.items():
        path = folder / filename
        require(path.is_file() and not path.is_symlink(), 'missing original: ' + filename)
        raw = path.read_bytes()
        require(len(raw) == size == result[key]['bytes'] and sha(raw) == result[key]['sha256'],
                'original hash/length mismatch: ' + filename)
        originals[name] = raw
    second = folder / 'sysdumpdb.before2.img'
    require(not second.is_symlink() and second.read_bytes() == originals['sysdumpdb'] and
            result['sysdump_before2']['sha256'] == sha(originals['sysdumpdb']), 'dual full original mismatch')
    require(sha(originals['uboot']) == UBOOT_SHA, 'current bootloader differs from audited identity')
    gpt = pre.validate_gpt(folder, pre.REFERENCE.read_bytes())
    require(gpt == result['gpt'], 'current GPT report mismatch')
    partition = next(p for p in gpt['partitions'] if p['name'] == 'sysdumpdb')
    require(partition['size_bytes'] == SIZE, 'wrong target size')
    binding = dict(preflight_fingerprint=sha(result_raw),
                   original_sha256=sha(originals['sysdumpdb']), target_partition=partition,
                   target_identity_hash=result['target']['identity_hash'], port=result['target']['port'],
                   uboot_sha256=UBOOT_SHA)
    return originals, binding


def approval_for(binding):
    return dict(schema='p011.sysdumpdb-original-rewrite.approval.v1', **binding,
                sources=source_hashes(), permit_original_rewrite=True, max_open=1,
                no_retry=True, target_bytes=SIZE, target_name='sysdumpdb',
                user_authorization='先测试是否能在下载模式刷入；继续',
                limitations=['same-byte rewrite does not establish changed-bit persistence',
                             'not a system-image write or Bili installation test'])


def _packet(code, payload=b''):
    return codec._packet(code, payload, codec.SUM16, codec.UNESCAPED)


def _select(code, name, size):
    require(name in FILES and (code == 0x10 or (code == 1 and name == 'sysdumpdb' and size == SIZE)),
            'partition operation outside fixed scope')
    return _packet(code, name.encode('utf-16-le').ljust(72, b'\0') + struct.pack('<I', size))


class Wire:
    """Single-handle request transport. Every failed attempt remains consumed."""
    def __init__(self, serial, out, current_check):
        self.serial, self.out, self.current_check = serial, pathlib.Path(out), current_check
        self.count = 0
        self.failed = False
        self.tx = (self.out / 'wire.tx.raw').open('xb')
        self.rx = (self.out / 'wire.rx.raw').open('xb')
        self.events = (self.out / 'wire.events.jsonl').open('x', encoding='utf-8')

    def event(self, **fields):
        self.events.write(json.dumps(dict(monotonic=time.monotonic(), **fields)) + '\n')
        self.events.flush()

    def exchange(self, request, *, response_type=0x80, response_size=0, label):
        require(not self.failed, 'transport previously failed; no retry permitted')
        try:
            self.current_check()
            require(self.serial.pending() == 0, 'pending RX before TX; stopping without purge')
            self.count += 1
            self.event(attempt=self.count, label=label, tx_offset=self.tx.tell(),
                       tx_bytes=len(request), rx_offset=self.rx.tell(), state='ATTEMPT_CONSUMED')
            self.tx.write(request)
            self.tx.flush()
            # Private fixed runner only: do not expand the public handshake whitelist.
            self.serial.send_fixed_once(request)
            decoder = codec.Decoder(codec.SUM16, codec.UNESCAPED)
            deadline = time.monotonic() + 3
            while True:
                require(time.monotonic() < deadline, 'response timeout; attempt consumed, no retry')
                raw = self.serial.read_available()
                if not raw:
                    time.sleep(.001)
                    continue
                self.rx.write(raw)
                self.rx.flush()
                frames = decoder.feed(raw)
                if not frames:
                    continue
                complete = decoder.finish()
                require(len(complete) == 1 and len(decoder.raw) == response_size + 8,
                        'duplicate/trailing/short response')
                frame = complete[0]
                require(frame.packet_type == response_type and len(frame.payload) == response_size,
                        'unexpected response type/length: 0x%04x/%d' % (frame.packet_type, len(frame.payload)))
                self.event(attempt=self.count, state='RESPONSE_VERIFIED', rx_bytes=len(decoder.raw))
                return frame.payload
        except BaseException:
            self.failed = True
            raise

    def close_logs(self):
        for stream in (self.tx, self.rx, self.events):
            stream.close()


class WindowsFixedSerial:
    def __init__(self, node):
        import win32_download_transport as win
        self.win = win
        self.serial = win.open_download(node)

    def pending(self):
        return self.serial.pending()

    def read_available(self):
        return self.serial.read_available()

    def send_fixed_once(self, data):
        value = self.serial
        written = self.win.DWORD()
        buffer = ctypes.create_string_buffer(data)
        if not value._api.WriteFile(value._handle_open(), buffer, len(data), ctypes.byref(written), None):
            raise self.win._win_error()
        require(written.value == len(data), 'short WriteFile; no retry permitted')

    def close(self):
        self.serial.close()


def read_fixed(wire, name, phase, out):
    filename, size, _ = FILES[name]
    wire.exchange(_select(0x10, name, size), label=phase + ':READ_START:' + name)
    result = bytearray()
    path = pathlib.Path(out) / (phase + '.' + filename)
    with path.open('xb') as file:
        for offset in range(0, size, STEP):
            raw = wire.exchange(_packet(0x11, struct.pack('<II', STEP, offset)),
                response_type=0x93, response_size=STEP, label=phase + ':READ:' + name + ':' + str(offset))
            file.write(raw)
            result.extend(raw)
        file.flush()
        os.fsync(file.fileno())
    wire.exchange(_packet(0x12), label=phase + ':READ_END:' + name)
    require(len(result) == size, 'read length mismatch')
    return bytes(result)


def run_sequence(wire, originals, out, status):
    require(len(originals['sysdumpdb']) == SIZE, 'wrong original size')
    for phase in ('before', 'after'):
        for name in FILES:
            print('STAGE=' + phase.upper() + '_READ_' + name, flush=True)
            raw = read_fixed(wire, name, phase, out)
            status.setdefault(phase, {})[name] = dict(bytes=len(raw), sha256=sha(raw), matches_original=raw == originals[name])
            require(raw == originals[name], phase + ' read differs from original: ' + name)
        if phase == 'after':
            break
        print('STAGE=WRITE_ORIGINAL_SYSDUMPDB_START', flush=True)
        status['write_start_attempted'] = True
        wire.exchange(_select(1, 'sysdumpdb', SIZE), label='WRITE_START_SYSDUMPDB')
        status['write_start_ack'] = True
        for offset in range(0, SIZE, STEP):
            status['write_data_attempts'] += 1
            wire.exchange(_packet(2, originals['sysdumpdb'][offset:offset + STEP]), label='WRITE_ORIGINAL:' + str(offset))
            status['write_bytes_acked'] += STEP
            if status['write_bytes_acked'] % 0x100000 == 0:
                print('WRITE_BYTES_ACKED=' + str(status['write_bytes_acked']), flush=True)
        require(status['write_bytes_acked'] == SIZE, 'incomplete write; END forbidden')
        status['write_end_attempted'] = True
        wire.exchange(_packet(3), label='WRITE_END_SYSDUMPDB')
        status['write_end_ack'] = True
    status['status'] = 'ORIGINAL_REWRITE_ACK_AND_READBACK_MATCHED'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=pathlib.Path, required=True)
    parser.add_argument('--approval', type=pathlib.Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(exist_ok=False)
    status = dict(status='NOT_COMPLETE', adb_invoked=False, changed_bit_persistence_proven=False,
        system_write_verified=False, physical_restoration_verified=False, open_attempts=0,
        host_handle_closed=False, write_start_attempted=False, write_start_ack=False,
        write_data_attempts=0, write_bytes_acked=0, write_end_attempted=False, write_end_ack=False,
        auto_retry=False, automatic_restore=False, started_unix=time.time())
    wire = serial = None
    try:
        originals, binding = load_preflight(args.preflight)
        require(not args.approval.is_symlink(), 'approval cannot be a symlink')
        raw = args.approval.read_bytes()
        require(sha(raw) == args.approval_sha256 and json.loads(raw) == approval_for(binding),
                'approval not bound to current originals/source/target')
        import win32_download_transport as win
        node, safe = pre.ready_target(win.inventory)
        require(safe['identity_hash'] == binding['target_identity_hash'] and safe['port'] == binding['port'],
                'preflight target identity changed')
        status['binding'] = binding
        status['sources_before'] = source_hashes()
        # Persistent one-shot claim precedes any serial open; failures cannot auto-retry.
        with (args.preflight / '.original-rewrite.claim').open('x', encoding='utf-8') as claim:
            claim.write(json.dumps(dict(approval_sha256=args.approval_sha256,
                started_unix=status['started_unix'], output=str(args.output))))
            claim.flush()
            os.fsync(claim.fileno())
        status['open_attempts'] = 1
        serial = WindowsFixedSerial(node)
        wire = Wire(serial, args.output, lambda: win._current_exact(win._identity(node)))
        run_sequence(wire, originals, args.output, status)
    except BaseException as exc:
        status['status'] = 'NOT_COMPLETE'
        status['error'] = type(exc).__name__ + ': ' + str(exc)
        print('STOP=' + status['error'], flush=True)
    finally:
        if serial is not None:
            try:
                serial.close()
                status['host_handle_closed'] = True
            except Exception as exc:
                status['close_error'] = type(exc).__name__ + ': ' + str(exc)
                status['status'] = 'NOT_COMPLETE'
        if wire is not None:
            status['transactions_attempted'] = wire.count
            wire.close_logs()
        status['sources_after'] = source_hashes()
        if status.get('sources_before', status['sources_after']) != status['sources_after']:
            status['status'] = 'NOT_COMPLETE'
            status['source_changed'] = True
        status['elapsed_seconds'] = time.time() - status['started_unix']
        pre.write_json(args.output / 'result.json', status)
        print('RESULT=' + status['status'], flush=True)
    return 0 if status['status'] == 'ORIGINAL_REWRITE_ACK_AND_READBACK_MATCHED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
