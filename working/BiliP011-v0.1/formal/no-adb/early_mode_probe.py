"""Finite AutoD mode-selection/handshake, never a flash or memory client.

Host state machine with injectable transport and clock. No hardware import or
operation occurs at import. MODE is an active boot-stage request, not passive
observation; a caller must explicitly permit it. No FDL/EXEC/storage commands.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import time
from bsl_frames import decode, classify_version, CONNECT_FRAME

MODE_FRAME = bytes.fromhex('7e 00 00 00 00 08 00 fe 82 7e')
SYNC_FRAME = b'\x7e'


class Refused(RuntimeError):
    pass


class HandleLost(Refused):
    pass


LOSS_ERRORS = (6, 21, 31, 433, 995, 1167)


def clean(decoded):
    return not (decoded['over_limit'] or decoded['junk'] or decoded['invalid'] or
                decoded['half'] or decoded['dangling_escape'])


def ack_ok(raw):
    value = decode(raw)
    return bool(clean(value) and value['frames'] and
                all(f['crc_ok'] and f['kind'] == 'ACK' and f['size'] == 0 for f in value['frames']))


class Probe:
    def __init__(self, inventory, opener, sink, permit_mode=False,
                 clock=time.monotonic, sleep=time.sleep, wait_seconds=300):
        if not 1 <= wait_seconds <= 600:
            raise ValueError('wait bound')
        self.inventory, self.opener, self.sink = inventory, opener, sink
        self.permit_mode, self.clock, self.sleep = permit_mode is True, clock, sleep
        self.wait_seconds = wait_seconds
        self.serial = self.node = None
        self.last_snapshot = None
        self.state = dict(status='PREPARING', mode_attempted=False, mode_write_returned=False,
                          sync_attempted=0, sync_write_returned=0, connect_attempted=False,
                          connect_write_returned=False, sessions_opened=0, open_failures=0,
                          autod_version_verified=False, connect_ack_verified=False,
                          adb_invoked=False, external_loader_uploaded=False,
                          storage_access_attempted=False, device_persistent_write_attempted=False,
                          physical_restoration_verified=False, host_handle_closed=True,
                          host_close_failed=False, phase='PREPARING', verified_session=None)

    def log(self, name, **fields):
        self.sink('event', dict(event=name, monotonic=self.clock(), **fields))

    def snapshot(self):
        rows = self.inventory()
        safe = [dict(pid=r['pid'], port=r['port'], started=r['started'], problem=r['problem'],
                     identity_sha256=hashlib.sha256(r['id'].encode()).hexdigest()[:16]) for r in rows]
        signature = json.dumps(safe, sort_keys=True)
        if signature != self.last_snapshot:
            self.log('USB_STATE', devices=safe)
            self.last_snapshot = signature
        early = [r for r in rows if r['pid'] == '4D00']
        if len(early) > 1:
            raise Refused('multiple download interfaces')
        if early and any(r['pid'] == '4064' for r in rows):
            raise Refused('runtime and download targets coexist')
        return early

    def wait_open(self, seconds):
        until = self.clock() + seconds
        while self.clock() < until:
            early = self.snapshot()
            if early:
                node = early[0]
                if node['problem'] not in (0, 21, 22, 24):
                    raise Refused('download driver not ready: problem=' + str(node['problem']))
                if node['started'] and node['problem'] == 0 and node['port']:
                    try:
                        serial = self.opener(node)
                    except OSError as exc:
                        self.state['open_failures'] += 1
                        self.log('OPEN_FAILED', winerror=getattr(exc, 'winerror', None))
                        if getattr(exc, 'winerror', None) not in (2, 3, 6, 21, 31, 55, 121, 433, 995, 1167):
                            raise
                    else:
                        self.serial, self.node = serial, dict(node)
                        self.state['sessions_opened'] += 1
                        self.state['host_handle_closed'] = False
                        try:
                            self.verify_handle()
                        except Exception:
                            self.close()
                            raise
                        self.log('OPENED', port=node['port'], session=self.state['sessions_opened'])
                        return
            self.sleep(.05)
        raise Refused('download interface wait expired')

    def verify_handle(self):
        early = self.snapshot()
        if (self.serial is None or not self.serial.is_open or len(early) != 1 or
                not early[0]['started'] or early[0]['problem'] != 0 or
                any(early[0][key] != self.node[key] for key in ('id', 'devinst', 'port'))):
            raise HandleLost('current download handle identity changed')
        try:
            self.serial.pending()
        except OSError as exc:
            if getattr(exc, 'winerror', None) in LOSS_ERRORS:
                raise HandleLost('download handle no longer usable') from exc
            raise

    def close(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception as exc:
                self.state['host_close_failed'] = True
                self.state['host_handle_closed'] = False
                self.state['host_close_error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            else:
                if not self.state['host_close_failed']:
                    self.state['host_handle_closed'] = True
            finally:
                self.serial = None

    def send(self, kind):
        self.verify_handle()
        if kind == 'MODE':
            if not self.permit_mode or self.state['mode_attempted'] or self.state['phase'] != 'PASSIVE_BOOT':
                raise Refused('mode selection not permitted or already attempted')
            if self.serial.pending():
                raise Refused('unsolicited data arrived before mode request')
            self.state['mode_attempted'] = True
            self.state['phase'] = 'MODE_ATTEMPTED'
            data = MODE_FRAME
        elif kind == 'SYNC':
            if (self.state['sync_attempted'] >= 4 or self.state['phase'] != 'AWAITING_VERSION' or
                    not self.state['mode_write_returned'] or self.state['connect_attempted']):
                raise Refused('sync budget exhausted')
            if self.serial.pending():
                raise Refused('input arrived before sync; no additional TX')
            self.state['sync_attempted'] += 1
            data = SYNC_FRAME
        elif kind == 'CONNECT':
            if (not self.state['autod_version_verified'] or self.state['connect_attempted'] or
                    self.state['phase'] != 'VERSION_VERIFIED' or
                    self.state['verified_session'] != self.state['sessions_opened']):
                raise Refused('CONNECT is not authorized')
            if self.serial.pending():
                raise Refused('new data before CONNECT requires a new assessment')
            self.state['connect_attempted'] = True
            self.state['phase'] = 'CONNECT_ATTEMPTED'
            data = CONNECT_FRAME
        else:
            raise Refused('TX kind outside fixed handshake')
        # Count before the write API: a failed/partial call is never retried.
        self.sink('tx', dict(kind=kind, data=data, session=self.state['sessions_opened']))
        self.serial.write(data)
        if kind == 'SYNC':
            self.state['sync_write_returned'] += 1
        else:
            self.state[kind.lower() + '_write_returned'] = True
            self.state['phase'] = 'MODE_SELECTED' if kind == 'MODE' else 'CONNECT_SENT'

    def receive(self, name, seconds, synchronize=False, seed=b'', expect='version'):
        raw = bytearray(seed)
        until = self.clock() + seconds
        next_sync = self.clock()
        try:
            while self.clock() < until:
                try:
                    chunk = self.serial.read_available()
                except OSError as exc:
                    if getattr(exc, 'winerror', None) in LOSS_ERRORS:
                        raise HandleLost('download receive handle lost') from exc
                    raise
                raw.extend(chunk)
                d = decode(raw)
                if d['over_limit'] or d['junk'] or d['invalid']:
                    break
                if clean(d) and d['frames']:
                    break
                if (synchronize and not d['frames'] and not d['half'] and
                        not d['dangling_escape'] and self.state['sync_attempted'] < 4 and
                        self.clock() >= next_sync):
                    self.send('SYNC')
                    next_sync = self.clock() + .4
                self.sleep(.02)
        finally:
            self.sink('rx', dict(name=name, data=bytes(raw), session=self.state['sessions_opened']))
        return bytes(raw)

    def version_session(self, seed=b''):
        self.state['phase'] = 'AWAITING_VERSION'
        raw = self.receive('version-' + str(self.state['sessions_opened']), 4, True, seed)
        verdict = classify_version(raw)
        if not verdict['authorized']:
            raise Refused('AutoD version refused: ' + verdict['reason'])
        self.verify_handle()
        self.state['autod_version_verified'] = True
        self.state['verified_session'] = self.state['sessions_opened']
        self.state['phase'] = 'VERSION_VERIFIED'
        self.log('AUTOD_VERSION_CONFIRMED', session=self.state['sessions_opened'])

    def run(self):
        try:
            if self.snapshot():
                raise Refused('fresh unplugged/normal-to-download connection required')
            self.state['status'] = 'ARMED_WAITING_DOWNLOAD'
            self.log('ARMED', wait_seconds=self.wait_seconds, permit_mode=self.permit_mode)
            self.wait_open(self.wait_seconds)
            self.state['phase'] = 'PASSIVE_BOOT'
            passive = self.receive('passive', .1)
            if passive:
                if not classify_version(passive)['authorized']:
                    passive = self.receive('passive-tail', .5, seed=passive)
                if not classify_version(passive)['authorized']:
                    raise Refused('unsolicited input is not an exact AutoD version')
                self.verify_handle()
                self.state['autod_version_verified'] = True
                self.state['verified_session'] = self.state['sessions_opened']
                self.state['phase'] = 'VERSION_VERIFIED'
                self.log('MODE_SKIPPED_ALREADY_AUTOD')
            else:
                self.send('MODE')
                try:
                    after = self.receive('after-mode', 1.8)
                    parsed = decode(after)
                    if (parsed['over_limit'] or parsed['junk'] or parsed['invalid'] or
                            any(not f['crc_ok'] or f['kind'] != 'AUTOD_VERSION' for f in parsed['frames'])):
                        raise Refused('unapproved response after mode request')
                    self.verify_handle()
                except HandleLost as exc:
                    # Only loss of the handle can route to a new session.
                    # Enumeration ambiguity/configuration errors fail closed.
                    self.log('OLD_HANDLE_LOST', reason=type(exc).__name__)
                    self.close()
                    self.state['autod_version_verified'] = False
                    self.state['verified_session'] = None
                    self.wait_open(30)
                    self.version_session()
                else:
                    self.version_session(after)
            self.send('CONNECT')
            ack = self.receive('connect-ack', 4, expect='ack')
            if not ack_ok(ack):
                raise Refused('CONNECT ACK not confirmed')
            self.verify_handle()
            self.state['connect_ack_verified'] = True
            self.state['status'] = 'AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS'
            self.state['phase'] = 'FINISHED'
        except Exception as exc:
            self.state['status'] = 'STOPPED_UNCONFIRMED'
            self.state['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            try:
                self.close()
            finally:
                if self.state['host_close_failed']:
                    self.state['status'] = 'HOST_CLOSE_UNCONFIRMED'
                self.sink('result', dict(self.state))
        return dict(self.state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--permit-mode-selection', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=300)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.permit_mode_selection:
        parser.error('active boot mode request requires explicit --permit-mode-selection')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sequence = [0]
    def sink(kind, value):
        if kind in ('tx', 'rx'):
            sequence[0] += 1
            name = value.get('kind', value.get('name')).lower()
            path = out / ('%03d-%s-%s.bin' % (sequence[0], kind, name))
            path.write_bytes(value['data'])
            record = dict(value, data_hex=value['data'].hex(), bytes=len(value['data']), file=path.name)
            del record['data']
        else:
            record = value
        with (out/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(record_type=kind, **record), sort_keys=True) + '\n')
        if kind == 'result':
            (out/'result.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
        print(json.dumps(dict(record_type=kind, **record), sort_keys=True), flush=True)
    from win32_download_transport import inventory, open_download
    probe = Probe(inventory, open_download, sink, args.permit_mode_selection, wait_seconds=args.wait_seconds)
    try:
        probe.run()
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
