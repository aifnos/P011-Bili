"""Stage one bounded, immutable strip-window experiment; no vendor signals."""
import datetime
import hashlib
import json
import zipfile
import argparse

from probe_device import BASE, ROOT, NATIVE, Adb, result_from
from wayland_evidence import analyze, probe_passed
from private_sdl_artifact import validate_private_artifact


def validate_artifact(base):
    binary = base / 'out/window-buffer-probe'
    manifest = json.loads((base/'out/window-buffer-probe.build.json').read_text(encoding='utf-8'))
    names = {'probes/window_buffer_probe.cpp', 'client/drm_trace.hpp', 'build/build_window_probe.py'}
    if manifest.get('schema')!=1 or set(manifest.get('sources',{}))!=names:
        raise ValueError('Unknown probe build manifest')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Probe source differs from build: '+name)
    raw = binary.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum!=manifest.get('binary_sha256') or raw[:6]!=b'\x7fELF\x01\x01' or raw[18:20]!=b'\x28\x00':
        raise ValueError('Probe binary is stale, changed or not ARM32')
    return binary, checksum


def main(private_sdl=False):
    # Gate before any ADB call: a failed build cannot re-run an older binary.
    runtime=None;runtime_sha=''
    if private_sdl:
        binary,checksum,runtime,runtime_sha,identity=validate_private_artifact(BASE)
    else:
        binary, checksum = validate_artifact(BASE);identity=checksum
    remote = '/mnt/data/p011-toolbox/bili-probes/' + identity[:16]
    out = ROOT / 'logs' / ('BiliP011-StripWindow-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    adb = Adb(out)
    safety = (NATIVE / 'runtime/native_safety.py').read_text(encoding='utf-8')
    gate = safety + '\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before = result_from(adb.python('before', gate))
    header = 'DEST=' + repr(remote) + '\nEXPECTED=' + repr(checksum) + '\nRUNTIME_SHA=' + repr(runtime_sha) + '\n'
    stage = header + safety + r'''
require_stock(stock_snapshot());owned_directory(DEST,True)
p=DEST+'/window-buffer-probe'
if os.path.lexists(p):assert not os.path.islink(p) and digest(p)==EXPECTED
lib=DEST+'/libSDL2-2.0.so.0'
if os.path.lexists(lib):assert RUNTIME_SHA and not os.path.islink(lib) and digest(lib)==RUNTIME_SHA
print('RESULT='+repr({'exists':os.path.isfile(p),'runtime_exists':os.path.isfile(lib)}))
'''
    ready = result_from(adb.python('stage-gate', stage))
    if not ready['exists']:
        adb.run('stage-owned-binary', ['push', str(binary), remote + '/window-buffer-probe'])
    if runtime is not None and not ready.get('runtime_exists'):
        adb.run('stage-owned-runtime',['push',str(runtime),remote+'/libSDL2-2.0.so.0'])
    report = {'binary_sha256': checksum, 'runtime_sha256':runtime_sha or None,
              'private_sdl':private_sdl,'physical_acceptance': False}
    try:
        answer = result_from(adb.python('finite-window', header + safety + r'''
import subprocess,ctypes
require_stock(stock_snapshot());owned_directory(DEST)
binary=DEST+'/window-buffer-probe';assert not os.path.islink(binary) and digest(binary)==EXPECTED
os.chmod(binary,0o700)
for sub in ('cache','config'):owned_directory(DEST+'/'+sub,True)
env=dict(os.environ,XDG_RUNTIME_DIR='/run/user/0',WAYLAND_DISPLAY='wayland-0',SDL_VIDEODRIVER='wayland',XDG_CACHE_HOME=DEST+'/cache',XDG_CONFIG_HOME=DEST+'/config',WAYLAND_DEBUG='client')
for k in ('LD_PRELOAD','LD_LIBRARY_PATH'):env.pop(k,None)
if RUNTIME_SHA:
 lib=DEST+'/libSDL2-2.0.so.0'
 assert not os.path.islink(lib) and digest(lib)==RUNTIME_SHA
 os.chmod(lib,0o500);env['LD_LIBRARY_PATH']=DEST
def limits():
 class Limit(ctypes.Structure):_fields_=[('cur',ctypes.c_ulong),('max',ctypes.c_ulong)]
 libc=ctypes.CDLL('libc.so.6');v=Limit(0,0);libc.setrlimit(4,ctypes.byref(v))
child=subprocess.Popen([binary],env=env,cwd=DEST,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=limits)
expired=False
try:o,e=child.communicate(timeout=15)
except subprocess.TimeoutExpired:
 expired=True;child.kill();o,e=child.communicate()
print('RESULT='+repr({'exit':child.returncode,'timeout':expired,'stdout':o,'stderr':e}))
''', timeout=25))
        (out / 'probe.stdout.raw').write_bytes(answer.pop('stdout'))
        (out / 'probe.stderr.raw').write_bytes(answer.pop('stderr'))
        report['process'] = answer
        raw = (out / 'probe.stdout.raw').read_text(encoding='utf-8')
        lines = [line[6:] for line in raw.splitlines() if line.startswith('PROBE=')]
        report['probe'] = json.loads(lines[-1]) if lines else None
        protocol = (out / 'probe.stderr.raw').read_text(encoding='utf-8', errors='replace')
        report['protocol_audit'] = analyze(protocol)
    finally:
        # Preserve evidence even if the independent restoration query fails.
        # Unknown is not restored; never promote a failed query to a pass.
        report['stock_unchanged'] = False
        try:
            after = result_from(adb.python('after', gate))
            report['stock_unchanged'] = before == after
        except Exception as error:
            report['restoration_query_error_type'] = type(error).__name__
        report['passed'] = probe_passed(report)
        if private_sdl:
            p=report.get('probe') or {}
            report['passed']=bool(report['passed'] and p.get('private_sdl_configure_timeout_ms')==500
                                  and p.get('diagnostic_settle_ms')==0)
        (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        compact=dict(report)
        compact['protocol_audit']={k:v for k,v in report.get('protocol_audit',{}).items() if k!='events'}
        print(json.dumps(compact, indent=2));print('LOG_DIR=' + str(out))
        # Protocol raw logs remain local: never archive keyboard/touch events.
        target = out.with_name(out.name + '-safe.zip')
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(out / 'result.json', 'result.json')
            if (out / 'probe.stdout.raw').is_file():
                bundle.write(out / 'probe.stdout.raw', 'probe.stdout.raw')
        with zipfile.ZipFile(target) as bundle:
            if bundle.testzip() is not None:raise ValueError('ZIP CRC failed')
        print('RESULT_ZIP=' + str(target));print('ZIP_SHA256=' + hashlib.sha256(target.read_bytes()).hexdigest())
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--private-sdl',action='store_true')
    raise SystemExit(main(parser.parse_args().private_sdl))
