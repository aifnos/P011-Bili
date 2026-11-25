"""Continue the one approved MODE attempt; this wrapper has no MODE command.

The sibling child validates the prior stopped session and claims it once. The
existing, HOST-tested capture/archive helpers bound and record this fixed child.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import uuid

from run_early_mode_probe import ExclusiveLock, _capture, _archive, _json


SOURCES = ('continue_autod_handshake.py', 'run_continue_autod.py',
           'early_mode_probe.py', 'bsl_frames.py', 'win32_download_transport.py',
           'run_early_mode_probe.py')


def main(argv=None):
    parser = argparse.ArgumentParser(description='One no-MODE continuation of a recorded stopped session')
    parser.add_argument('--prior', required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    base = pathlib.Path(__file__).resolve().parent
    root = base.parent / 'evidence'
    prior = args.prior.resolve(strict=True)
    if prior.parent != root.resolve() or not prior.name.startswith('early-mode-probe-'):
        parser.error('prior must be an original early-mode-probe directory in this evidence root')
    with ExclusiveLock(root / '.early-mode-probe.lock'):
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        out = root / ('autod-continuation-' + now.strftime('%Y%m%d-%H%M%S-%f') + '-' + uuid.uuid4().hex[:8])
        out.mkdir(exist_ok=False)
        snapshot = out / 'sources'
        snapshot.mkdir()
        before = {}
        for name in SOURCES:
            data = (base / name).read_bytes()
            before[name] = hashlib.sha256(data).hexdigest()
            (snapshot / name).write_bytes(data)
        child_out = out / 'device-probe'
        command = [sys.executable, '-u', str(base / 'continue_autod_handshake.py'),
                   '--prior', str(prior), '--output', str(child_out)]
        print('LOG_DIR=' + str(out), flush=True)
        _json(out / 'command.json', {'argv': command, 'prior': str(prior),
                                    'mode_command_allowed': False, 'watchdog_seconds': 75})
        status = _capture(command, out, 75)
        after = {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in SOURCES}
        changed = before != after
        _json(out / 'source.sha256.json', {'before': before, 'after': after, 'changed_during_run': changed})
        if status['interrupted']:
            exit_code = 130
        elif status['timeout']:
            exit_code = 124
        elif (changed or not status['streams_complete'] or status['capture_errors'] or
              status['stdout_forward_errors'] or status['spawn_error'] or status['termination_error']):
            exit_code = 1
        else:
            exit_code = status['host_exit'] if status['host_exit'] is not None else 1
        status.update(wrapper_exit=exit_code, source_changed=changed,
                      scope='ONE_CONTINUATION_NO_MODE_NO_STORAGE', prior=str(prior))
        _json(out / 'host.status.json', status)
        archive, digest = _archive(out)
        _json(out / 'archive.verification.json', {'result_zip': str(archive),
              'zip_sha256': digest, 'crc_readback_verified': True, 'member_sha256_verified': True})
        print('RESULT_ZIP=' + str(archive), flush=True)
        print('RESULT_ZIP_SHA256=' + digest, flush=True)
        print('ZIP_READBACK_VERIFIED=true', flush=True)
        return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
