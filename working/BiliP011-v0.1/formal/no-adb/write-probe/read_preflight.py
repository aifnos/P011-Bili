"""Fixed legacy AutoD initialization and read-only backup preflight.

No old START script is run. The pinned x86 EXE performs active MODE/built-in
EXEC setup; this wrapper supplies only partition_list and five fixed reads.
The EXE is stopped after the reads. Host process termination is not device
restoration. Output contains private device data and must remain local.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import uuid

BASE = pathlib.Path(__file__).resolve().parent
NO_ADB = BASE.parent
PROJECT = NO_ADB.parents[3]
if str(NO_ADB) not in sys.path:
    sys.path.insert(0, str(NO_ADB))
from gpt_readback import parse_primary
from run_early_mode_probe import ExclusiveLock, _archive

TOOL_ROOT = pathlib.Path('C:/Users/P011_USER/Downloads/P011-AutoD-Tools/verified-backup-20260914-160719197/spd_dump_SPRD_Release')
TOOL_PINS = {
    'spd_dump.exe': (82432, '0c8ee50cf6b5dead2499c48b4693f7a4e55f8215dd21c9372145d887436c369b'),
    'Channel9.dll': (229376, '79edbd9e4ae5d1d8b572d8663eb921069736ef0b7ee661920d3cde9855bc3d4f'),
    'Channel.ini': (387, 'f6a4d42665246d87b5704db77b0691ba68ab3b8a9f4456bd41c4131e5ec18645'),
}
REFERENCE = PROJECT / '06_Firmware/backups/v2.4.0-20260923-162730/gpt-primary-64sectors.bin'
REFERENCE_SHA = '9dde510dd5fd7b1a46237dd193ec36f17eada679bd7cfa19dc39664506bcee1e'
SOURCE_COMMIT = '2a202404a7512026d146b62624f089aceb408520'
PLAN = (
    ('uboot', 0x100000, 'uboot.before.img', 'uboot'),
    ('miscdata', 0x100000, 'miscdata.before.img', 'miscdata'),
    ('uboot_log', 0x400000, 'uboot_log.before.img', 'uboot_log'),
    ('sysdumpdb', 0xa00000, 'sysdumpdb.before1.img', 'sysdump_before1'),
    ('sysdumpdb', 0xa00000, 'sysdumpdb.before2.img', 'sysdump_before2'),
)
PROMPT = re.compile(rb'(?:^|[\r\n])(FDL2|FDL1|BROM)[ \t]*>[ \t]*')
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
FATAL = re.compile(rb'timeout reached|bad checksum|unexpected response|Connection failed|find port failed|part not exist|fopen[^\r\n]*failed', re.I)


class PreflightError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise PreflightError(message)


def sha_file(path):
    value = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    pathlib.Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def tool_manifest():
    rows = {}
    for name, (size, expected) in TOOL_PINS.items():
        path = TOOL_ROOT / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == size and
                sha_file(path) == expected, 'pinned tool mismatch: ' + name)
        rows[name] = dict(bytes=size, sha256=expected)
    raw = (TOOL_ROOT / 'spd_dump.exe').read_bytes()
    pe = struct.unpack_from('<I', raw, 0x3c)[0]
    require(raw[:2] == b'MZ' and raw[pe:pe + 4] == b'PE\0\0' and
            struct.unpack_from('<H', raw, pe + 4)[0] == 0x14c, 'tool is not the pinned x86 PE')
    return dict(source_commit=SOURCE_COMMIT, release='stable_20250726_0012',
                directory=str(TOOL_ROOT), files=rows)


def layout(value):
    return dict(sector_bytes=value['sector_bytes'], reported_disk_bytes=value['reported_disk_bytes'],
                first_usable_lba=value['first_usable_lba'], last_usable_lba=value['last_usable_lba'],
                partitions=[{key: part[key] for key in ('index', 'name', 'first_lba', 'last_lba', 'attributes', 'size_bytes')}
                            for part in value['partitions']])


def validate_gpt(run_dir, reference_raw):
    path = pathlib.Path(run_dir) / 'pgpt.bin'
    require(path.is_file() and not path.is_symlink(), 'missing primary GPT capture')
    raw = path.read_bytes()
    current, reference = parse_primary(raw), parse_primary(reference_raw)
    require(layout(current) == layout(reference), 'current GPT differs from reference layout')
    by_name = {part['name']: part for part in current['partitions']}
    for name, size, _, _ in PLAN:
        require(name in by_name and by_name[name]['size_bytes'] == size, 'fixed read target length differs: ' + name)
    require('sysdumpdb_bak' not in by_name and not any(n.endswith(('_a', '_b')) for n in by_name),
            'unexpected sysdump backup or A/B layout')
    return dict(file='pgpt.bin', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), layout_verified=True,
                primary_header_crc_verified=current['primary_header_crc_verified'],
                primary_array_crc_verified=current['primary_array_crc_verified'],
                reference_sha256=hashlib.sha256(reference_raw).hexdigest(),
                backup_gpt_verified=False, partitions=current['partitions'])


def ready_target(observer, expected=None):
    rows = observer()
    require(len(rows) == 1, 'one download interface and no other Unisoc target is required')
    row = rows[0]
    require(row.get('pid') == '4D00' and row.get('started') is True and row.get('problem') == 0 and
            re.fullmatch(r'COM[1-9][0-9]*', row.get('port', '')), 'download target is not ready')
    if expected is not None:
        require(all(row[key] == expected[key] for key in ('id', 'devinst', 'port')), 'download target changed during read')
    identity = hashlib.sha256(row['id'].encode()).hexdigest()
    safe = dict(pid='4D00', port=row['port'], identity_hash=identity, identity_hash_prefix=identity[:16],
                started=True, problem=0)
    return dict(row), safe


def confirm_read(run_dir, item):
    name, size, filename, _ = item
    path = pathlib.Path(run_dir) / filename
    require(path.is_file() and not path.is_symlink(), 'missing fixed read: ' + filename)
    require(path.stat().st_size == size, 'short/oversized fixed read: ' + filename)
    return dict(partition=name, file=filename, bytes=size, sha256=sha_file(path))


def capture_session(command, run_dir, reference_raw, observer, *, watchdog_seconds, popen=subprocess.Popen):
    """Interactive raw capture; fake command injection is only for HOST tests."""
    run_dir = pathlib.Path(run_dir)
    require(type(watchdog_seconds) is int and 1 <= watchdog_seconds <= 540, 'invalid parent watchdog')
    messages = queue.Queue()
    child = None
    threads = []
    capture_errors = []
    state = dict(schema='p011.autod.read-preflight.v1', status='READ_PREFLIGHT_NOT_COMPLETE',
                 scope='ACTIVE_BUILTIN_AUTOD_SETUP_THEN_FIXED_STORAGE_READS_ONLY',
                 selection_scope='CURRENT_PC_PINNED_SPRD_DRIVER_MAPPING_NOT_CROSS_PC_SELECTOR',
                 device_write_commands_supplied=False, erase_commands_supplied=False,
                 external_loader_supplied=False, adb_invoked=False, device_restoration_verified=False,
                 sysdump_same=False, reads=[], commands=[], stage='HOST_PREPARING',
                 child=dict(host_exit=None, host_process_stopped=False, host_handle_closed=False,
                            handle_close_evidence='owned child exit and pipe EOF, not device restoration',
                            streams_complete=False, timeout=False, interrupted=False, kill_reason=None,
                            capture_errors=capture_errors, termination_error=None))
    def event(name, **fields):
        value = dict(event=name, monotonic=time.monotonic(), **fields)
        with (run_dir / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, sort_keys=True) + '\n')
        print('STAGE=' + name, flush=True)
    def pump(kind, stream):
        try:
            with (run_dir / ('host.' + kind + '.raw')).open('wb') as raw:
                while True:
                    chunk = stream.read1(4096)
                    if not chunk:
                        break
                    raw.write(chunk)
                    raw.flush()
                    messages.put((kind, chunk))
        except Exception as exc:
            capture_errors.append(kind + ': ' + type(exc).__name__ + ': ' + str(exc))
            messages.put(('capture-error', b''))
        finally:
            stream.close()
            messages.put((kind + '-eof', b''))
    active = None
    next_read = 0
    initialized = False
    expected_target = None
    first_download = None
    transient_node_deadline = None
    tails = dict(stdout=b'', stderr=b'')
    done = False
    started = time.monotonic()
    try:
        for kind in tails:
            (run_dir / ('host.' + kind + '.raw')).write_bytes(b'')
        event('BUILTIN_AUTOD_INITIALIZATION_REQUESTED')
        state['stage'] = 'WAITING_GPT_AND_FDL2'
        child = popen(command, cwd=str(run_dir), stdin=subprocess.PIPE,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        state['child']['pid'] = child.pid
        for kind, stream in (('stdout', child.stdout), ('stderr', child.stderr)):
            thread = threading.Thread(target=pump, args=(kind, stream), daemon=True)
            thread.start()
            threads.append(thread)
        while not done:
            if time.monotonic() - started >= watchdog_seconds:
                state['child']['timeout'] = True
                raise PreflightError('parent watchdog expired')
            if capture_errors:
                raise PreflightError('raw stream capture failed')
            try:
                observed = observer()
                transient_node_deadline = None
            except Exception as exc:
                # CR_NO_SUCH_DEVNODE during boot re-enumeration is not a valid
                # inventory. Keep waiting at most two seconds before FDL2;
                # never treat it as an empty/approved target or send a read.
                if (expected_target is None and type(exc).__name__ == 'TransportRefusal' and
                        str(exc) == 'PnP status unavailable (CONFIGRET 13)'):
                    if transient_node_deadline is None:
                        transient_node_deadline = time.monotonic() + 2
                        event('TRANSIENT_BOOT_DEVNODE_DISAPPEARED')
                    require(time.monotonic() < transient_node_deadline,
                            'boot device node unavailable for two seconds')
                    time.sleep(.05)
                    continue
                raise
            downloads = [row for row in observed if row.get('pid') == '4D00']
            require(not any(row.get('pid') == '4064' for row in observed) and len(downloads) <= 1,
                    'runtime interface or multiple download targets appeared')
            if downloads:
                identity = (downloads[0].get('id'), downloads[0].get('port'))
                if first_download is None:
                    first_download = identity
                else:
                    require(identity == first_download, 'early download identity changed during initialization')
            if expected_target is not None:
                ready_target(lambda: observed, expected_target)
            try:
                kind, chunk = messages.get(timeout=.05)
            except queue.Empty:
                require(child.poll() is None, 'child exited before fixed read completion')
                continue
            if kind not in tails:
                continue
            # Normalization is ONLY for this derived parser. Raw files are exact.
            tails[kind] = (tails[kind] + ANSI.sub(b'', chunk.replace(b'\r\r\n', b'\r\n')))[-65536:]
            require(not FATAL.search(tails[kind]), 'native tool reported an error; see raw streams')
            while True:
                match = PROMPT.search(tails[kind])
                if match is None:
                    break
                tails[kind] = tails[kind][match.end():]
                require(match[1] == b'FDL2', 'unexpected native stage prompt')
                expected_target, safe = ready_target(observer, expected_target)
                state['target'] = safe
                if not initialized:
                    state['gpt'] = validate_gpt(run_dir, reference_raw)
                    initialized = True
                    event('GPT_LAYOUT_VERIFIED', sha256=state['gpt']['sha256'])
                else:
                    require(active is not None, 'unsolicited duplicate idle prompt')
                    record = confirm_read(run_dir, active)
                    state['reads'].append(record)
                    state[active[3]] = record
                    event('FIXED_READ_VERIFIED', partition=record['partition'], file=record['file'],
                          bytes=record['bytes'], sha256=record['sha256'])
                    active = None
                if next_read < len(PLAN):
                    active = PLAN[next_read]
                    next_read += 1
                    name, size, filename, _ = active
                    line = 'read_part %s 0 0x%x %s' % (name, size, filename)
                    require(line == 'read_part %s 0 0x%x %s' % (PLAN[next_read - 1][:3]), 'fixed command gate failed')
                    state['commands'].append(line)
                    event('FIXED_READ_COMMAND', command=line)
                    child.stdin.write((line + '\n').encode('ascii'))
                    child.stdin.flush()
                    state['stage'] = 'READING_' + name.upper()
                else:
                    require(len(state['reads']) == len(PLAN), 'fixed read manifest incomplete')
                    require(state['sysdump_before1']['sha256'] == state['sysdump_before2']['sha256'],
                            'sysdumpdb changed between complete reads')
                    state['sysdump_same'] = True
                    state['status'] = 'READ_PREFLIGHT_COMPLETE_VERIFIED'
                    state['stage'] = 'FDL2_IDLE_READS_COMPLETE'
                    state['child']['kill_reason'] = 'FIXED_READS_COMPLETE'
                    event('FIXED_READS_COMPLETE_HOST_STOP_ONLY', device_restoration_verified=False)
                    done = True
                    break
    except KeyboardInterrupt:
        state['child']['interrupted'] = True
        state['error'] = 'KeyboardInterrupt'
    except Exception as exc:
        state['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if child is not None:
            if child.poll() is None:
                if state['child']['kill_reason'] is None:
                    state['child']['kill_reason'] = 'PREFLIGHT_STOP_UNCONFIRMED'
                try:
                    child.kill()  # Own Popen process only, no process-name scans.
                    child.wait(timeout=10)
                except Exception as exc:
                    state['child']['termination_error'] = type(exc).__name__ + ': ' + str(exc)
            if child.stdin is not None:
                try:
                    child.stdin.close()
                except OSError:
                    pass
            for thread in threads:
                thread.join(timeout=5)
            state['child']['host_exit'] = child.poll()
            state['child']['host_process_stopped'] = child.poll() is not None
            state['child']['streams_complete'] = not any(thread.is_alive() for thread in threads)
            state['child']['host_handle_closed'] = (state['child']['host_process_stopped'] and
                                                    state['child']['streams_complete'])
        if (state.get('error') or capture_errors or not state['child']['host_handle_closed'] or
                state['child']['termination_error']):
            state['status'] = 'READ_PREFLIGHT_NOT_COMPLETE'
        state['elapsed_seconds'] = time.monotonic() - started
    return state


def source_paths():
    return {'read_preflight.py': pathlib.Path(__file__),
            'gpt_readback.py': NO_ADB / 'gpt_readback.py',
            'run_early_mode_probe.py': NO_ADB / 'run_early_mode_probe.py',
            'win32_download_transport.py': NO_ADB / 'win32_download_transport.py'}


def run_preflight(wait_seconds=300):
    require(type(wait_seconds) is int and 1 <= wait_seconds <= 300, 'wait seconds must be 1..300')
    root = NO_ADB.parent / 'evidence'
    root.mkdir(parents=True, exist_ok=True)
    with ExclusiveLock(root / '.early-mode-probe.lock'):
        from win32_download_transport import inventory
        require(inventory() == [], 'unplug all Unisoc USB interfaces before arming this fresh run')
        tool = tool_manifest()
        require(REFERENCE.is_file() and sha_file(REFERENCE) == REFERENCE_SHA, 'reference GPT pin mismatch')
        reference_raw = REFERENCE.read_bytes()
        parse_primary(reference_raw)
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        out = root / ('autod-read-preflight-private-' + now.strftime('%Y%m%d-%H%M%S-%f') + '-' + uuid.uuid4().hex[:8])
        out.mkdir(exist_ok=False)
        snapshot = out / 'sources'
        snapshot.mkdir()
        before = {}
        for name, path in source_paths().items():
            raw = path.read_bytes()
            before[name] = hashlib.sha256(raw).hexdigest()
            (snapshot / name).write_bytes(raw)
        command = [str(TOOL_ROOT / 'spd_dump.exe'), '--wait', str(wait_seconds), '--verbose', '0',
                   '--kickto', '2', 'partition_list', 'p011-partitions.xml']
        write_json(out / 'command.json', dict(argv=command, watchdog_seconds=wait_seconds + 240,
                                              active_builtin_initialization=True, write_commands_supplied=False))
        print('LOG_DIR=' + str(out), flush=True)
        print('ARMED_INSERT_POWERED_OFF_P011_NOW=true', flush=True)
        result = capture_session(command, out, reference_raw, inventory, watchdog_seconds=wait_seconds + 240)
        after = {name: sha_file(path) for name, path in source_paths().items()}
        result['tool'] = tool
        result['tool_after'] = tool_manifest()
        result['sources'] = dict(before=before, after=after, changed=before != after)
        if before != after or result['tool_after'] != tool:
            result['status'] = 'READ_PREFLIGHT_NOT_COMPLETE'
            result['error'] = 'tool or source changed during run'
        result['wrapper_exit'] = 0 if result['status'] == 'READ_PREFLIGHT_COMPLETE_VERIFIED' else 1
        write_json(out / 'source.sha256.json', result['sources'])
        write_json(out / 'host.status.json', dict(result['child'], wrapper_exit=result['wrapper_exit'],
                                                 status=result['status'], source_changed=before != after))
        write_json(out / 'read-result.json', result)
        archive, digest = _archive(out)
        verification = dict(result_zip=str(archive), zip_sha256=digest, crc_readback_verified=True,
                            member_sha256_verified=True, wrapper_exit=result['wrapper_exit'])
        write_json(out / 'archive.verification.json', verification)
        print('RESULT_ZIP=' + str(archive), flush=True)
        print('RESULT_ZIP_SHA256=' + digest, flush=True)
        print('HOST_STOP_IS_NOT_DEVICE_RESTORATION=true', flush=True)
        return dict(run_directory=str(out), result=result, **verification)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Pinned x86 AutoD setup and five fixed reads; no write/erase commands')
    parser.add_argument('--wait-seconds', type=int, default=300)
    args = parser.parse_args(argv)
    try:
        return run_preflight(args.wait_seconds)['wrapper_exit']
    except Exception as exc:
        print('PREFLIGHT_REFUSED=' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
