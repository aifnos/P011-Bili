"""One continuation of the pinned stopped MODE round; no MODE capability.

Import is HOST-only. Main validates immutable prior evidence, consumes an
exclusive claim, and only then imports/opens the restricted Windows transport.
No prior log is rewritten. There is no reconnect/reset/loader/storage fallback.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import time
from dataclasses import dataclass

from bsl_frames import CONNECT_FRAME
from early_mode_probe import Probe, Refused, SYNC_FRAME, ack_ok


BASE = pathlib.Path(__file__).resolve().parent
PRIOR_NAME = 'early-mode-probe-20261014-193756-572489-4d25b551'
PRIOR = BASE.parent / 'evidence' / PRIOR_NAME
PINS = {
    'host.status.json': '8e0c7c07d339ecc497df23cf80f3b38c0bb72d80e72012fce707040f1c242ec0',
    'host.stdout.raw': '6102229d0422fafb617e5de6ccddb6883071580f23a9cd5b30b3bb6c138d8e2c',
    'host.stderr.raw': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'source.sha256.json': 'f0b09ff151056969dbb3208b206250c97765f53b7d0fe81362ce3e4cac76f113',
    'command.json': 'f5109b9df88284032c28c79d9833686ba2f3c72142743e923b6190dbc9a80cce',
    'device-probe/result.json': '34ab8cea64adab3609a26a076cfb4bdc85aed0807cc5f71989a19e3ab453f697',
    'device-probe/events.jsonl': '6102229d0422fafb617e5de6ccddb6883071580f23a9cd5b30b3bb6c138d8e2c',
    'device-probe/001-rx-passive.bin': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'device-probe/002-tx-mode.bin': '61b9c35051d1cd49cf005ffa473b00166ac49f4fd8784041085ba4fa2d399beb',
    'device-probe/003-rx-after-mode.bin': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'sources/early_mode_probe.py': 'a6015f5a080b3c010940fd0a0dbd2b84c5f7de8b5bb6d3f8a2ea3b7cd7529542',
    'sources/bsl_frames.py': '3a3e6d8739672345caf2c38f2fa49ecb1ca2183642c618b1aa815f11c57cd7d6',
    'sources/win32_download_transport.py': '791cb1bfcad7e6bb7e4781a61b2e22bdab990a00f72a13ca124db7581726321b',
    'sources/run_early_mode_probe.py': '696e6298f5f177a712bb0b24fafa9a94b89b4331f6a665f139c9b790f8bcdea6',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused('duplicate evidence JSON key')
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)


def require(condition, message):
    if not condition:
        raise Refused(message)


@dataclass(frozen=True)
class Origin:
    directory: pathlib.Path
    fingerprint: str
    identity_hash: str
    port: str


def load_origin(directory, *, required_path=PRIOR, pins=PINS):
    """Pure HOST validation. Alternate pins/path exist only for injected tests."""
    directory = pathlib.Path(directory).resolve(strict=True)
    require(directory == pathlib.Path(required_path).resolve(strict=True), 'unapproved prior evidence path')
    require(set(pins) == set(PINS), 'prior evidence member set changed')
    blobs = {}
    for name, expected in pins.items():
        path = directory / name
        require(not path.is_symlink() and path.is_file(), 'missing or linked prior member: ' + name)
        require(path.resolve().is_relative_to(directory), 'prior member escaped its directory')
        raw = path.read_bytes()
        require(len(raw) <= 1048576 and sha(raw) == expected, 'prior evidence SHA mismatch: ' + name)
        blobs[name] = raw
    members = {p.name for p in (directory / 'device-probe').iterdir()}
    expected_members = {pathlib.PurePosixPath(n).name for n in pins if n.startswith('device-probe/')}
    require(members == expected_members, 'unexpected prior device-probe member')
    host = parse(blobs['host.status.json'])
    require(host.get('host_exit') == 1 and host.get('wrapper_exit') == 1 and
            host.get('streams_complete') is True and host.get('remote_exit') is None and
            host.get('remote_exit_applicable') is False, 'prior host outcome is not the recorded complete stop')
    for key in ('timeout', 'interrupted', 'child_kill_attempted', 'source_changed'):
        require(host.get(key) is False, 'prior host uncertainty: ' + key)
    for key in ('spawn_error', 'termination_error'):
        require(host.get(key) is None, 'prior host error: ' + key)
    for key in ('capture_errors', 'stdout_forward_errors'):
        require(host.get(key) == [], 'prior stream uncertainty: ' + key)
    require(blobs['host.stderr.raw'] == b'' and
            blobs['host.stdout.raw'] == blobs['device-probe/events.jsonl'], 'prior raw streams disagree')
    source = parse(blobs['source.sha256.json'])
    names = {n.removeprefix('sources/') for n in pins if n.startswith('sources/')}
    require(source.get('changed_during_run') is False and source.get('before') == source.get('after') and
            set(source.get('before', {})) == names, 'prior source freeze is incomplete')
    for name in names:
        require(source['before'][name] == sha(blobs['sources/' + name]), 'prior source bytes disagree')
        require(sha((BASE / name).read_bytes()) == source['before'][name], 'current dependency differs: ' + name)
    command = parse(blobs['command.json'])
    require(command.get('permit_mode_selection') is True and command.get('wrapper_device_commands') is False and
            command.get('child_output_directory') == 'device-probe', 'prior command permission differs')
    result = parse(blobs['device-probe/result.json'])
    require(result.get('status') == 'STOPPED_UNCONFIRMED' and result.get('phase') == 'MODE_SELECTED' and
            result.get('mode_attempted') is True and result.get('mode_write_returned') is True and
            result.get('host_handle_closed') is True and result.get('host_close_failed') is False,
            'prior MODE/close evidence is insufficient')
    for key in ('sync_attempted', 'sync_write_returned', 'open_failures'):
        require(type(result.get(key)) is int and result[key] == 0, 'prior budget is not unused: ' + key)
    require(type(result.get('sessions_opened')) is int and result['sessions_opened'] == 1,
            'unexpected prior session count')
    for key in ('connect_attempted', 'connect_write_returned', 'autod_version_verified',
                'connect_ack_verified', 'adb_invoked', 'external_loader_uploaded',
                'storage_access_attempted', 'device_persistent_write_attempted', 'physical_restoration_verified'):
        require(result.get(key) is False, 'unexpected prior action or acceptance: ' + key)
    require(result.get('verified_session') is None and
            result.get('error', '').startswith('PermissionError: [WinError 22] '), 'prior stop reason differs')
    records = [parse(line) for line in blobs['device-probe/events.jsonl'].splitlines() if line]
    results = [r for r in records if r.get('record_type') == 'result']
    require(len(results) == 1 and {k: v for k, v in results[0].items() if k != 'record_type'} == result,
            'prior result record disagrees')
    tx = [r for r in records if r.get('record_type') == 'tx']
    rx = [r for r in records if r.get('record_type') == 'rx']
    require(len(tx) == 1 and tx[0].get('kind') == 'MODE' and tx[0].get('session') == 1 and
            tx[0].get('file') == '002-tx-mode.bin' and tx[0].get('bytes') == 10 and
            tx[0].get('data_hex') == '7e000000000800fe827e' and
            blobs['device-probe/002-tx-mode.bin'].hex() == tx[0]['data_hex'], 'prior TX is not only one MODE')
    require(len(rx) == 2 and {r.get('name') for r in rx} == {'passive', 'after-mode'}, 'prior RX phases differ')
    for record in rx:
        name = '001-rx-passive.bin' if record['name'] == 'passive' else '003-rx-after-mode.bin'
        require(record.get('file') == name and record.get('bytes') == 0 and record.get('data_hex') == '' and
                record.get('session') == 1 and blobs['device-probe/' + name] == b'', 'prior RX is not empty')
    states = [r for r in records if r.get('event') == 'USB_STATE']
    require(states and len(states[-1].get('devices', [])) == 1, 'prior target is not unique')
    target = states[-1]['devices'][0]
    require(target.get('pid') == '4D00' and target.get('started') is True and target.get('problem') == 0 and
            target.get('port') == 'COM9' and len(target.get('identity_sha256', '')) == 16, 'prior target is not ready')
    opened = [r for r in records if r.get('event') == 'OPENED']
    require(len(opened) == 1 and opened[0].get('port') == target['port'] and opened[0].get('session') == 1,
            'prior open identity differs')
    fingerprint = sha(json.dumps(dict(sorted(pins.items())), separators=(',', ':')).encode())
    return Origin(directory, fingerprint, target['identity_sha256'], target['port'])


def claim_once(origin, output, *, claim_path=None):
    claim = (origin.directory.parent / ('.' + origin.directory.name + '.autod-continuation.claim.json')
             if claim_path is None else pathlib.Path(claim_path))
    value = dict(prior=origin.directory.name, fingerprint=origin.fingerprint,
                 output=str(pathlib.Path(output).resolve()), pid=os.getpid(),
                 time=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
                 consumed=True, mode_allowed=False, remaining_sync=4, remaining_connect=1)
    try:
        with claim.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(value, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise Refused('this MODE round already has a continuation claim; no retry') from exc
    return claim


class NoModeTransport:
    """No MODE/other packet can reach the underlying transport through this adapter."""
    def __init__(self, serial, inventory, expected, budget):
        self.serial, self.inventory, self.expected, self.budget = serial, inventory, expected, budget

    @property
    def is_open(self):
        return self.serial.is_open

    def pending(self):
        return self.serial.pending()

    def read_available(self):
        return self.serial.read_available()

    def write(self, data):
        require(type(data) is bytes and data in (SYNC_FRAME, CONNECT_FRAME), 'continuation has no MODE capability')
        current = self.inventory()
        require(len(current) == 1 and all(current[0][k] == self.expected[k] for k in ('id', 'devinst', 'port')),
                'continuation handle identity changed')
        require(self.serial.pending() == 0, 'input arrived before continuation TX')
        key, limit = ('sync', 4) if data == SYNC_FRAME else ('connect', 1)
        require(self.budget[key] < limit and not (key == 'sync' and self.budget['connect']),
                'continuation cumulative TX budget exhausted')
        self.budget[key] += 1  # A failed/partial write consumes the attempt.
        self.serial.write(data)

    def close(self):
        return self.serial.close()


def continue_round(origin, inventory, opener, sink, *, clock=time.monotonic, sleep=time.sleep):
    """Caller has already consumed claim_once; no reconnect after any new error."""
    budget = dict(sync=0, connect=0)
    open_attempted = False
    def current():
        rows = inventory()
        require(len(rows) == 1, 'continuation requires one USB target and no runtime coexistence')
        row = rows[0]
        require(row.get('pid') == '4D00' and row.get('started') is True and row.get('problem') == 0 and
                row.get('port') == origin.port and sha(row.get('id', '').encode())[:16] == origin.identity_hash,
                'current target does not match the pinned prior target')
        return rows
    def open_once(row):
        nonlocal open_attempted
        require(not open_attempted, 'continuation open was already attempted; no retry')
        fresh = current()[0]
        require(all(fresh[k] == row[k] for k in ('id', 'devinst', 'port')), 'target changed before continuation open')
        open_attempted = True
        try:
            serial = opener(fresh)
        except OSError as exc:
            raise Refused('continuation open/configuration failed; no retry; winerror=' +
                          str(getattr(exc, 'winerror', None))) from exc
        return NoModeTransport(serial, current, dict(fresh), budget)
    probe = Probe(current, open_once, sink, permit_mode=False, clock=clock, sleep=sleep, wait_seconds=1)
    probe.state.update(mode_attempted=True, mode_write_returned=True,
                       prior_directory=origin.directory.name, prior_fingerprint=origin.fingerprint,
                       prior_host_exit=1, prior_status='STOPPED_UNCONFIRMED',
                       continuation_no_mode_capability=True, phase='CONTINUATION_SOURCE_VERIFIED')
    try:
        probe.log('NO_MODE_CONTINUATION_ARMED', prior=origin.directory.name, sync_budget=4, connect_budget=1)
        probe.wait_open(5)
        probe.version_session()
        probe.send('CONNECT')
        ack = probe.receive('connect-ack', 4, expect='ack')
        require(ack_ok(ack), 'continuation CONNECT ACK not confirmed')
        probe.verify_handle()
        probe.state.update(connect_ack_verified=True, status='AUTOD_HANDSHAKE_CONFIRMED_NO_STORAGE_ACCESS', phase='FINISHED')
    except Exception as exc:
        probe.state.update(status='STOPPED_UNCONFIRMED', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        try:
            probe.close()
        finally:
            if probe.state['host_close_failed']:
                probe.state['status'] = 'HOST_CLOSE_UNCONFIRMED'
            probe.state.update(cumulative_mode_attempted=1, cumulative_sync_attempted=probe.state['sync_attempted'],
                               cumulative_connect_attempted=int(probe.state['connect_attempted']),
                               adapter_sync_attempted=budget['sync'], adapter_connect_attempted=budget['connect'])
            sink('result', dict(probe.state))
    return dict(probe.state)


def make_sink(out):
    sequence = 0
    def sink(kind, value):
        nonlocal sequence
        if kind in ('tx', 'rx'):
            sequence += 1
            name = value.get('kind', value.get('name')).lower()
            path = out / ('%03d-%s-%s.bin' % (sequence, kind, name))
            path.write_bytes(value['data'])
            record = dict(value, data_hex=value['data'].hex(), bytes=len(value['data']), file=path.name)
            del record['data']
        else:
            record = dict(value)
        record['record_type'] = kind
        line = json.dumps(record, sort_keys=True)
        with (out / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(line + '\n')
        if kind == 'result':
            (out / 'result.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(line, flush=True)
    return sink


def main(argv=None):
    parser = argparse.ArgumentParser(description='Only the pinned round: zero MODE, at most four SYNC and one CONNECT')
    parser.add_argument('--prior', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sink = make_sink(out)
    try:
        origin = load_origin(args.prior)
        claim = claim_once(origin, out)
        sink('event', dict(event='ORIGIN_AND_EXCLUSIVE_CLAIM_VERIFIED', prior=origin.directory.name,
                           prior_fingerprint=origin.fingerprint, claim_file=claim.name, mode_allowed=False))
        from win32_download_transport import inventory, open_download
        continue_round(origin, inventory, open_download, sink)
    except Exception as exc:
        sink('event', dict(event='CONTINUATION_STOP', error=type(exc).__name__ + ': ' + str(exc), mode_allowed=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
