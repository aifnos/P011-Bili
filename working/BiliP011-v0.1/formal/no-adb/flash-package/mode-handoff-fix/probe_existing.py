"""One fixed continuation of the user's stopped v5 round. No MODE/EXEC/storage.

Only the pinned original ZIP and its unused SYNC budget authorize this probe.
The persistent claim prevents reruns. No archived START script is executed.
"""
import gzip
import hashlib
import json
import pathlib
import sys
import traceback
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent / 'out/P011-Bili-NoADB-v5-open-20261014/app'
sys.path.insert(0, str(APP))
import engine
from run_early_mode_probe import ExclusiveLock


def main():
    prior = HERE / 'user-failed-install-v5-original.zip'
    digest = hashlib.sha256(prior.read_bytes()).hexdigest()
    engine.require(digest == '171de9c88a3d3c792c127ec97ce1490375bf30920bc6284215990e9fca664fc5', 'prior ZIP SHA changed')
    with zipfile.ZipFile(prior) as archive:
        engine.require(archive.testzip() is None, 'prior ZIP CRC')
        get = archive.read
        result = json.loads(get('result.json'))
        state = result['transport']
        engine.require(state['mode_attempts'] == 1 and state['sync_attempts'] == 0 and
                       not state['write_started'] and state['host_handle_closed'] and
                       not state['cleanup_uncertain'] and state['phase'] == 'WAIT_MODE_REENUMERATION', 'prior budget/phase differs')
        engine.require(gzip.decompress(get('wire.tx.raw.gz')) == engine.MODE and
                       gzip.decompress(get('wire.rx.raw.gz')) == b'', 'prior wire differs')
    with ExclusiveLock(pathlib.Path('D:/文档/近代史/视频/P011-Bili-NoADB-v5-open-20261014/.flash.lock')):
        rows = engine.win.inventory()
        engine.require(len(rows) == 1, 'unique download required')
        node = rows[0]
        engine.win._identity(node)
        engine.require(hashlib.sha256(node['id'].encode()).hexdigest() == state['target_id_hash'] and
                       node['port'] == state['port'], 'current target differs')
        out = HERE / 'existing-device-handshake'
        with (HERE / 'existing-device-continuation.claim.json').open('x', encoding='utf-8') as stream:
            json.dump(dict(prior_zip_sha256=digest, mode_allowed=False, max_sync=1, max_connect=1,
                           exec_allowed=False, storage_allowed=False), stream)
        out.mkdir()
        session = engine.Session(out)
        observed = dict(status='NOT_COMPLETE', prior_zip_sha256=digest, mode_sent=False,
                        exec_sent=False, storage_read_or_write=False, physical_acceptance=False)
        try:
            session.node = node
            session.state['phase'] = 'CONTINUE_EXISTING_NO_MODE'
            session.state['open_attempts'] = 1
            session.serial = engine.win.open_download(node)
            session.state['host_handle_closed'] = False
            version = session.exchange(b'\x7e', 'SYNC_CRC', engine.codec.CRC16, True, 0x81, 12)
            engine.require(version == engine.codec.AUTOD_PAYLOAD, 'AutoD version differs')
            session.exchange(engine.codec.build_fixed('CONNECT_CRC16'), 'CONNECT_CRC16', engine.codec.CRC16, True)
            observed.update(status='AUTOD_VERSION_AND_CONNECT_ACK_VERIFIED_NO_STORAGE',
                            version_payload_hex=version.hex(), port=node['port'])
        except BaseException as exc:
            observed['error'] = type(exc).__name__ + ': ' + str(exc)
            (out / 'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
        finally:
            try:
                session.close()
            except BaseException as exc:
                observed.update(status='NOT_COMPLETE', close_error=str(exc))
            observed['transport'] = session.state
            (out / 'result.json').write_text(json.dumps(observed, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(observed, indent=2, ensure_ascii=False))
        return 0 if observed['status'].startswith('AUTOD_VERSION') else 1


if __name__ == '__main__':
    raise SystemExit(main())
