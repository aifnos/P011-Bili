"""One bounded child for the scoped original-byte sysdumpdb write test.

This parent never opens hardware. A pinned approval and preflight are validated
by the fixed sibling child before its one open. No general flasher is launched.
"""
import argparse
import datetime
import hashlib
import pathlib
import sys
import uuid

BASE = pathlib.Path(__file__).resolve().parent
NO_ADB = BASE.parent
sys.path.insert(0, str(NO_ADB))
from run_early_mode_probe import ExclusiveLock, _capture, _archive, _json

SOURCES = {
    'run_sysdump_rewrite.py': BASE / 'run_sysdump_rewrite.py',
    'sysdump_original_rewrite.py': BASE / 'sysdump_original_rewrite.py',
    'read_preflight.py': BASE / 'read_preflight.py',
    'win32_download_transport.py': NO_ADB / 'win32_download_transport.py',
    'storage_read_codec.py': NO_ADB / 'storage_read_codec.py',
    'gpt_readback.py': NO_ADB / 'gpt_readback.py',
    'run_early_mode_probe.py': NO_ADB / 'run_early_mode_probe.py',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fixed original-byte sysdumpdb test and evidence capture')
    parser.add_argument('--preflight', type=pathlib.Path, required=True)
    parser.add_argument('--approval', type=pathlib.Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    args = parser.parse_args(argv)
    evidence = NO_ADB.parent / 'evidence'
    prior = args.preflight.resolve(strict=True)
    approval = args.approval.resolve(strict=True)
    if prior.parent != evidence.resolve() or not prior.name.startswith('autod-read-preflight-private-'):
        parser.error('preflight must be a fresh fixed-read evidence directory')
    if (approval.is_symlink() or not approval.is_file() or
            hashlib.sha256(approval.read_bytes()).hexdigest() != args.approval_sha256):
        parser.error('approval SHA-256 differs')
    with ExclusiveLock(evidence / '.early-mode-probe.lock'):
        stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        out = evidence / ('sysdump-original-rewrite-private-' + stamp.strftime('%Y%m%d-%H%M%S-%f') + '-' + uuid.uuid4().hex[:8])
        out.mkdir(exist_ok=False)
        snapshot = out / 'sources'
        snapshot.mkdir()
        before = {}
        for name, path in SOURCES.items():
            raw = path.read_bytes()
            before[name] = hashlib.sha256(raw).hexdigest()
            (snapshot / name).write_bytes(raw)
        (out / 'approval.json').write_bytes(approval.read_bytes())
        child_out = out / 'device-probe'
        command = [sys.executable, '-u', str(BASE / 'sysdump_original_rewrite.py'),
                   '--preflight', str(prior), '--approval', str(approval),
                   '--approval-sha256', args.approval_sha256, '--output', str(child_out)]
        print('LOG_DIR=' + str(out), flush=True)
        _json(out / 'command.json', {'argv': command, 'watchdog_seconds': 600,
              'target': 'sysdumpdb', 'bytes': 0xa00000, 'mode': 'ORIGINAL_BYTES_ONLY',
              'parent_opens_hardware': False, 'adb_invoked': False})
        status = _capture(command, out, 600)
        after = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in SOURCES.items()}
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
                      scope='ORIGINAL_SYSDUMPDB_ONLY_ACK_AND_FULL_READBACK',
                      preflight=str(prior), approval_sha256=args.approval_sha256,
                      physical_restoration_verified=False)
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
