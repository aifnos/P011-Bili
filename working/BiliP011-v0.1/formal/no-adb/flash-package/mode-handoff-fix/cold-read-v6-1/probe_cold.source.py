"""One cold-start v6 candidate test: built-in AutoD, GPT and uboot reads only."""
import hashlib
import json
import pathlib
import sys
import traceback

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent / 'out/P011-Bili-NoADB-v5-open-20261014/app'
sys.path[:0] = [str(HERE), str(APP)]
import engine
import flash
from run_early_mode_probe import ExclusiveLock


class ReadOnlySession(engine.Session):
    def write_system(self, *args, **kwargs):
        raise RuntimeError('This hardware verification cannot write system')

    def read_partition(self, name, path):
        engine.require(name in ('user_partition', 'uboot'), 'Only GPT and uboot reads are permitted')
        return super().read_partition(name, path)


def main():
    tests = json.loads((HERE / 'host-tests-result.json').read_bytes())
    engine.require(tests['passed'] and tests['engine_sha256'] == engine.sha_file(HERE / 'engine.py'), 'HOST-tested engine identity changed')
    flash.verify_package(APP.parent)
    out = HERE / 'cold-read-v6-1'
    out.mkdir()
    result = dict(status='NOT_COMPLETE', scope='BUILTIN_AUTOD_THEN_GPT_UBOOT_READ_ONLY',
                  system_write_tested=False, physical_acceptance=False, source_sha256=tests['engine_sha256'])
    session = ReadOnlySession(out)
    try:
        with ExclusiveLock(pathlib.Path('D:/文档/近代史/视频/P011-Bili-NoADB-v5-open-20261014/.flash.lock')):
            session.connect(wait_seconds=180)
            gpt = session.read_partition('user_partition', out / 'gpt.bin')
            engine.require(gpt == engine.sha_file(APP.parent / 'data/reference-gpt.bin'), 'GPT bytes differ')
            uboot = session.read_partition('uboot', out / 'uboot.bin')
            engine.require(uboot == flash.UBOOT_SHA, 'uboot bytes differ')
            result.update(status='COLD_AUTOD_GPT_UBOOT_READ_VERIFIED', gpt_sha256=gpt, uboot_sha256=uboot)
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        (out / 'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        try:
            session.close()
        except BaseException as exc:
            result.update(status='NOT_COMPLETE', close_error=str(exc))
        result['transport'] = session.state
        (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0 if result['status'] == 'COLD_AUTOD_GPT_UBOOT_READ_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
