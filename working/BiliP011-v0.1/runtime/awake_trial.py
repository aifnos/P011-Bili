"""Private v2.4.0 trial. Device-side guardian, exact identities, no system writes.

The copied UI alone calls the existing vendor keep-awake API. This supervisor
only reads its two scalar fields; it never writes process memory or TCP packets.
Python 3.5 compatible; json is an output-only bundled encoder.
"""
import os
import re
import signal
import stat
import struct
import subprocess
import sys
import time
import ctypes
import p011_json as json
from native_safety import PINS, digest, owned_directory, stock_snapshot, require_stock
import config as C

ROOT = os.path.dirname(os.path.realpath(__file__))
SELF = os.path.join(ROOT, 'awake_trial.py')
CANDIDATE = os.path.join(ROOT, 'Z03.awake-candidate')
LOCK = '/mnt/data/p011-toolbox/bili-awake.lock'
STOP = False


def read(path, limit=131072):
    with open(path, 'rb') as f:
        value = f.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Read limit: ' + path)
    return value


def atomic(name, value):
    path = os.path.join(ROOT, name)
    temp = path + '.new-' + str(os.getpid())
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(value)
    os.replace(temp, path)


def log(event, **fields):
    row = dict(fields, event=event, monotonic=round(time.monotonic(), 3))
    with open(ROOT + '/events.jsonl', 'a') as f:
        f.write(json.dumps(row) + '\n')
    print(event, flush=True)


def proc(pid):
    try:
        raw = read('/proc/%d/stat' % pid, 8192).decode()
        fields = raw[raw.rindex(')') + 2:].split()
        row = dict(pid=int(pid), start=fields[19], state=fields[0], parent=int(fields[1]),
                   sid=int(fields[3]), threads=int(fields[17]), exe='', args=[])
        if row['state'] in ('Z', 'X') and row['threads'] == 1:
            return row
        row['exe'] = os.readlink('/proc/%d/exe' % pid)
        row['args'] = [os.fsdecode(x) for x in read('/proc/%d/cmdline' % pid).split(b'\0') if x]
        again = read('/proc/%d/stat' % pid, 8192).decode()
        if again[again.rindex(')') + 2:].split()[19] != row['start']:
            raise RuntimeError('PID changed while sampling')
        return row
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(row):
    return row and (row['state'] not in ('Z', 'X') or row['threads'] > 1)


def procs():
    result = []
    for name in os.listdir('/proc'):
        if name.isdigit():
            row = proc(int(name))
            if alive(row): result.append(row)
    return result


def ident(name, row):
    atomic(name + '.ident', '%d %s %s\n' % (row['pid'], row['start'], row['exe']))


def saved(name):
    try:
        pid, start, exe = read(ROOT + '/' + name + '.ident', 1024).decode().strip().split(' ', 2)
        return dict(pid=int(pid), start=start, exe=exe)
    except FileNotFoundError:
        return None


def refresh(row):
    if not row: return None
    now = proc(row['pid'])
    if not now or now['start'] != row['start']: return None
    if alive(now) and now['exe'] != row['exe']:
        raise RuntimeError('Same PID/start exec changed; signals refused')
    return now


def send(row, sig):
    current = refresh(row)
    if not alive(current): return False
    if current['pid'] <= 1 or current['pid'] == os.getpid():
        raise RuntimeError('Unsafe signal target')
    os.kill(current['pid'], sig)
    return True


def terminate(row, kill=False, grace=5):
    if grace not in (5,15):raise ValueError('Unbounded process grace refused')
    if send(row, signal.SIGTERM):
        until = time.monotonic() + grace
        while alive(refresh(row)) and time.monotonic() < until: time.sleep(.1)
    if alive(refresh(row)) and kill:
        send(row, signal.SIGKILL)
        until = time.monotonic() + 3
        while alive(refresh(row)) and time.monotonic() < until: time.sleep(.1)
    if alive(refresh(row)): raise RuntimeError('Exact process did not exit')


def boot(): return read('/proc/sys/kernel/random/boot_id', 128).decode().strip()


def environment(row):
    return dict(os.fsdecode(x).split('=', 1) for x in read('/proc/%d/environ' % row['pid']).split(b'\0') if b'=' in x)


def idle_fields():
    row = refresh(saved('control'))
    if not alive(row) or row['exe'] != '/usr/bin/control_engine': raise RuntimeError('Control engine identity changed')
    result = {}
    with open('/proc/%d/mem' % row['pid'], 'rb', buffering=0) as f:
        for name, address in [('seconds', 0x47728), ('enabled', 0x47748), ('system_state', 0x47960)]:
            f.seek(address); result[name] = struct.unpack('<I', f.read(4))[0]
    for name in ('brightness', 'actual_brightness'):
        result[name] = int(read('/sys/class/backlight/sprd_backlight/' + name, 64).strip())
    return result


def verify():
    if ROOT != C.REMOTE or not re.match(r'^/mnt/data/p011-toolbox/bili-awake/[0-9a-f]{24}$', ROOT):
        raise ValueError('Wrong trial location')
    owned_directory(ROOT)
    for line in read(ROOT + '/SOURCE.sha256', 32768).decode().splitlines():
        sha, length, name = line.split(' ')
        if not re.match(r'^[A-Za-z0-9_.-]+$', name): raise ValueError('Manifest path')
        path = ROOT + '/' + name
        if os.path.islink(path) or os.path.getsize(path) != int(length) or digest(path) != sha:
            raise ValueError('Candidate manifest mismatch')
    for path, expected in PINS.items():
        if digest(path) != expected: raise ValueError('Original file changed')
    for name, expected in C.MEDIA_FILES.items():
        path = C.MEDIA + '/' + name
        if os.path.islink(path) or digest(path) != expected: raise ValueError('Media runtime differs')


def release():
    atomic('lease.json', json.dumps(dict(session=C.SESSION, seq=-1, active=False)))


def handler(sig, frame):
    global STOP
    STOP = True


def stop_requested(): return STOP or os.path.exists(ROOT + '/stop.request')


def child_limits(parent=None):
    class Limit(ctypes.Structure): _fields_ = [('cur', ctypes.c_ulong), ('max', ctypes.c_ulong)]
    libc = ctypes.CDLL(None, use_errno=True)
    limit = Limit(0, 0)
    if libc.setrlimit(4, ctypes.byref(limit)): raise RuntimeError('Cannot disable private core dumps')
    if parent is not None:
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) or os.getppid() != parent: os._exit(99)


def launch_ui(env, cwd):
    env = dict(env, QML_DISABLE_DISK_CACHE='1', QT_LOGGING_TO_CONSOLE='1')
    env.pop('QML_FORCE_DISK_CACHE', None)
    with open(os.devnull, 'rb') as inp, open(ROOT + '/candidate.stdout.raw', 'ab', buffering=0) as out, open(ROOT + '/candidate.stderr.raw', 'ab', buffering=0) as err:
        child = subprocess.Popen([CANDIDATE, '-platform', 'wayland'], env=env, cwd=cwd,
                                 stdin=inp, stdout=out, stderr=err, close_fds=True,
                                 start_new_session=True, preexec_fn=child_limits)
    until = time.monotonic() + 2
    while time.monotonic() < until:
        row = proc(child.pid)
        if alive(row) and row['exe'] == CANDIDATE:
            ident('candidate', row); return child
        if child.poll() is not None: break
        time.sleep(.02)
    raise RuntimeError('Candidate did not reach expected executable')


def gate():
    verify(); snapshot = stock_snapshot(); require_stock(snapshot)
    if any(os.path.lexists(p) for p in [LOCK, '/mnt/data/p011-toolbox/native.lock', '/tmp/p011-menutest.lock', '/mnt/data/p011-menu']):
        raise RuntimeError('Existing trial lock/alias requires inspection')
    allp = procs()
    stock = [p for p in allp if p['exe'] == '/usr/bin/Z03']
    loops = [p for p in allp if '/usr/bin/zyb_z03_launch.sh' in p['args'][:3]]
    if len(stock) != 1 or len(loops) != 1 or stock[0]['parent'] != loops[0]['pid']:
        raise RuntimeError('Original parent topology differs')
    if stock[0]['state'] in ('T', 't', 'D') or loops[0]['state'] in ('T', 't', 'D'):
        raise RuntimeError('Original processes not healthy')
    if stock[0]['args'][1:] != ['-platform', 'wayland']: raise RuntimeError('Unexpected original arguments')
    if any(p['exe'].startswith('/mnt/data/p011-toolbox/') for p in allp): raise RuntimeError('Another private native player is running')
    env = environment(stock[0])
    if env.get('XDG_RUNTIME_DIR') != '/run/user/0' or env.get('WAYLAND_DISPLAY', 'wayland-0') != 'wayland-0':
        raise RuntimeError('Display environment differs')
    if not stat.S_ISSOCK(os.stat('/run/user/0/wayland-0').st_mode): raise RuntimeError('Wayland unavailable')
    if os.statvfs(ROOT).f_flag & getattr(os, 'ST_NOEXEC', 8): raise RuntimeError('Private path is noexec')
    ident('original', stock[0]); ident('launcher', loops[0])
    ce = [p for p in allp if p['exe'] == '/usr/bin/control_engine']
    if len(ce) != 1: raise RuntimeError('Control engine ambiguous')
    ident('control', ce[0]); fields = idle_fields()
    if fields['enabled'] != 1 or fields['seconds'] != 60: raise RuntimeError('Expected idle baseline not present')
    atomic('boot.txt', boot()); atomic('before.json', json.dumps(dict(stock=snapshot, idle=fields), indent=2))
    return env, os.readlink('/proc/%d/cwd' % stock[0]['pid'])


def start():
    gate()
    # Exclusive, owned lock. Never remove a pre-existing lock automatically.
    os.symlink(ROOT, LOCK)
    release()
    with open(os.devnull, 'rb') as inp, open(ROOT + '/guardian.stdout.raw', 'ab', buffering=0) as out, open(ROOT + '/guardian.stderr.raw', 'ab', buffering=0) as err:
        child = subprocess.Popen([sys.executable, '-B', SELF, 'guard'], stdin=inp, stdout=out, stderr=err, start_new_session=True, close_fds=True)
    until = time.monotonic() + 10
    while time.monotonic() < until:
        if os.path.exists(ROOT + '/guardian.ready'):
            print('RESULT=' + repr(dict(started=True, guardian_pid=child.pid))); return
        if child.poll() is not None: break
        time.sleep(.1)
    atomic('stop.request', 'START_TIMEOUT\n')
    raise RuntimeError('Guardian not armed; stop requested')


def launch_media(number, pause_test=False):
    env = dict(os.environ, LD_LIBRARY_PATH=C.MEDIA + '/lib', XDG_RUNTIME_DIR='/run/user/0', WAYLAND_DISPLAY='wayland-0',
               SDL_VIDEODRIVER='wayland', XDG_CONFIG_HOME=C.MEDIA + '/config', XDG_CACHE_HOME=C.MEDIA + '/cache',
               P011_AWAKE_LEASE=ROOT + '/lease.json', P011_AWAKE_SESSION=C.SESSION)
    for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'LD_PRELOAD', 'P011_PAUSE_TEST'): env.pop(key, None)
    if pause_test: env['P011_PAUSE_TEST'] = '1'
    parent = os.getpid()
    with open(os.devnull, 'rb') as inp, open(ROOT + '/play-%d.stdout.raw' % number, 'wb', buffering=0) as out, open(ROOT + '/play-%d.stderr.raw' % number, 'wb', buffering=0) as err:
        child = subprocess.Popen([C.MEDIA + '/bin/api-probe', '--play'], env=env, cwd=C.MEDIA,
                                 stdin=inp, stdout=out, stderr=err, close_fds=True, start_new_session=True,
                                 preexec_fn=lambda: child_limits(parent))
    until = time.monotonic() + 2
    while time.monotonic() < until:
        row = proc(child.pid)
        if alive(row) and row['exe'] == C.MEDIA + '/bin/api-probe': ident('media', row); break
        if child.poll() is not None: break
        time.sleep(.02)
    log('PLAY_STARTED', number=number, pause_test=pause_test, pid=child.pid)
    return child


def launch_client(env):
    # Stdout is fixed lifecycle markers only; API helper IPC is never logged.
    parent=os.getpid()
    with open(os.devnull, 'rb') as inp, open(ROOT+'/service.stdout.raw','ab',buffering=0) as out, open(ROOT+'/service.stderr.raw','ab',buffering=0) as err:
        child = subprocess.Popen([sys.executable,'-B',ROOT+'/service.py'], env=env, cwd=ROOT,
                                 stdin=inp,stdout=out,stderr=err,close_fds=True,
                                 start_new_session=True,preexec_fn=lambda:child_limits(parent))
    ident('bili-service',proc(child.pid))
    until=time.monotonic()+10
    while time.monotonic()<until:
        if child.poll() is not None: raise RuntimeError('Private Bili service exited')
        if os.path.isfile(ROOT+'/bili-endpoint.json') and b'P011_BILI_SERVICE_READY' in read(ROOT+'/service.stdout.raw'):
            log('BILI_SERVICE_READY',pid=child.pid);return child
        time.sleep(.1)
    raise RuntimeError('Private Bili service not ready')


def worker():
    if not alive(refresh(saved('guardian'))) or not os.path.exists(ROOT + '/guardian.ready'): raise RuntimeError('Guardian missing')
    app, parent = refresh(saved('original')), refresh(saved('launcher'))
    if not alive(app) or not alive(parent) or app['parent'] != parent['pid']: raise RuntimeError('Stock identity changed')
    env, cwd = environment(app), os.readlink('/proc/%d/cwd' % app['pid'])
    send(parent, signal.SIGSTOP)
    until = time.monotonic() + 2
    while refresh(parent)['state'] not in ('T', 't') and time.monotonic() < until: time.sleep(.05)
    if refresh(parent)['state'] not in ('T', 't'): raise RuntimeError('Launcher not stopped')
    log('LOOP_PAUSED')
    if stop_requested(): return
    terminate(app, kill=False)  # Never force-kill the original UI.
    if any(p['exe'] == '/usr/bin/Z03' for p in procs()): raise RuntimeError('Another original UI appeared')
    if stop_requested(): return
    client = launch_client(env) if getattr(C,'CLIENT',False) else None
    ui = launch_ui(env, cwd); log('CANDIDATE_STARTED', pid=ui.pid)
    started = time.monotonic(); media = None; number = 0; ready = False; next_sample = 0
    while not stop_requested() and time.monotonic() - started < 560:
        if not alive(refresh(saved('guardian'))):
            log('GUARDIAN_LOST'); recover(env, cwd); return
        if ui.poll() is not None: raise RuntimeError('Candidate exited')
        if client is not None and client.poll() is not None: raise RuntimeError('Private Bili service ended')
        if refresh(parent)['state'] not in ('T', 't'): raise RuntimeError('Original launcher resumed unexpectedly')
        elapsed = time.monotonic() - started
        if not ready and elapsed >= 9:
            stdout = read(ROOT + '/candidate.stdout.raw', 8 * 1024 * 1024)
            stderr = read(ROOT + '/candidate.stderr.raw', 8 * 1024 * 1024)
            loaded=b'P011_AWAKE READY' in stdout+stderr and (client is None or b'P011_BILI UI_READY' in stdout+stderr)
            if not loaded:
                if elapsed >= (28 if client is not None else 9): raise RuntimeError('Bridge or client UI not ready within limit')
            else:
                if idle_fields()['enabled'] != 1:
                    players=[p for p in procs() if p['exe']==C.MEDIA+'/bin/bili-player' and environment(p).get('P011_CLIENT_ROOT')==ROOT]
                    if client is None or not players: raise RuntimeError('Initial release not confirmed')
                ready = True; atomic('ready', 'READY\n'); log('READY_FOR_PLAY')
        if client is None and ready and media is None and number < 3 and os.path.exists(ROOT + '/play-%d.request' % (number + 1)):
            number += 1
            pause = read(ROOT + '/play-%d.request' % number, 64).strip() == b'pause'
            media = launch_media(number, pause)
        if media is not None and media.poll() is not None:
            log('PLAY_EXIT', number=number, exit=media.returncode)
            release(); atomic('play-%d.done' % number, str(media.returncode)); media = None
        if time.monotonic() >= next_sample:
            if client is not None:
                ui_log=read(ROOT+'/candidate.stdout.raw',8*1024*1024)+read(ROOT+'/candidate.stderr.raw',8*1024*1024)
                if b'P011_BILI UI_DESTROYED' in ui_log:
                    log('USER_LEFT_BILI');return
            fields = idle_fields(); log('SAMPLE', **fields); next_sample = time.monotonic() + 1
            if fields['seconds'] != 60: raise RuntimeError('Idle timeout unexpectedly changed')
        time.sleep(.1)


def cleanup_private():
    # Worker was stopped first, so it can no longer spawn new processes.
    if getattr(C,'CLIENT',False):
        def own_client(row):
            if ROOT+'/service.py' in row['args'][1:3]: return True
            if getattr(C,'TOOLBOX',False):
                if ROOT+'/audio_guard.py' in row['args'][1:3]:return True
                if row['exe'] in ('/usr/bin/gst-play-1.0','/bin/gst-play-1.0'):
                    try:return environment(row).get('P011_TOOLBOX_ROOT')==ROOT
                    except (FileNotFoundError,ProcessLookupError):return False
            if row['exe'] not in (C.MEDIA+'/bin/bili-api',C.MEDIA+'/bin/bili-player',C.MEDIA+'/bin/bili-hw'): return False
            try: return environment(row).get('P011_CLIENT_ROOT')==ROOT
            except (FileNotFoundError,ProcessLookupError): return False
        owned=[p for p in procs() if own_client(p)]
        terminate(saved('bili-service'),kill=True,grace=15)
        for child in owned: terminate(child,kill=True)
        if any(own_client(p) for p in procs()): raise RuntimeError('Private Bili client remains active')
        # Cache contains authorized ephemeral media, never diagnostic output.
        # All exact-session readers/writers have exited before narrow cleanup.
        from story_cache import purge
        purge(ROOT)
    media = saved('media')
    children = [p for p in procs() if media and p['parent'] == media['pid'] and p['exe'] == C.MEDIA + '/bin/mpv-probe']
    terminate(media, kill=True)
    for child in children: terminate(child, kill=True)
    if any(p['exe'] in (C.MEDIA + '/bin/api-probe', C.MEDIA + '/bin/mpv-probe') for p in procs()):
        raise RuntimeError('Private media still active')
    release()


def recover(env, cwd):
    result = dict(restored=False, idle_restored=False, errors=[])
    if boot() != read(ROOT + '/boot.txt', 128).decode().strip(): raise RuntimeError('Boot changed, no stale signals')
    log('RESTORING')
    try:
        cleanup_private()
        until = time.monotonic() + 5
        while idle_fields()['enabled'] != 1 and time.monotonic() < until: time.sleep(.2)
        if idle_fields()['enabled'] != 1:
            # One bounded release-only UI retry if the bridge itself stopped.
            terminate(saved('candidate'), kill=True)
            release(); launch_ui(env, cwd)
            until = time.monotonic() + 12
            while idle_fields()['enabled'] != 1 and time.monotonic() < until: time.sleep(.2)
        result['idle_restored'] = idle_fields()['enabled'] == 1 and idle_fields()['seconds'] == 60
    except Exception as exc:
        result['errors'].append('release: ' + str(exc))
    try:
        terminate(saved('candidate'), kill=True)
        # Catch the narrow launch-to-identity-record failure window by exact path.
        for row in procs():
            if row['exe'] == CANDIDATE: terminate(row, kill=True)
        if any(p['exe'] == CANDIDATE for p in procs()): raise RuntimeError('Candidate remains active')
        parent = refresh(saved('launcher'))
        if not alive(parent) or '/usr/bin/zyb_z03_launch.sh' not in parent['args'][:3]: raise RuntimeError('Original loop absent')
        send(parent, signal.SIGCONT); log('ORIGINAL_LOOP_RESUMED', pid=parent['pid'])
        until = time.monotonic() + 60; stable = None; since = 0
        while time.monotonic() < until:
            stock = [p for p in procs() if p['exe'] == '/usr/bin/Z03' and p['parent'] == parent['pid'] and p['state'] not in ('T', 't', 'D')]
            if len(stock) == 1:
                key = (stock[0]['pid'], stock[0]['start'])
                if key != stable: stable = key; since = time.monotonic()
                if time.monotonic() - since >= 3:
                    snapshot = stock_snapshot(); require_stock(snapshot)
                    result['after'] = snapshot; result['idle_after'] = idle_fields(); result['restored'] = True; break
            else: stable = None
            time.sleep(.3)
        if not result['restored']: raise RuntimeError('Original UI not stable within 60 seconds')
    except Exception as exc:
        result['errors'].append('stock: ' + str(exc))
    result['passed'] = result['restored'] and result['idle_restored'] and not result['errors']
    # A restored process is deliberately not labelled physical UI acceptance.
    result['physical_ui_verified'] = False
    atomic('result.json', json.dumps(result, indent=2))
    if result['passed'] and os.path.islink(LOCK) and os.readlink(LOCK) == ROOT: os.unlink(LOCK)
    log('FINISHED', passed=result['passed'])
    return result


def guard():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    app = refresh(saved('original'))
    if not alive(app): raise RuntimeError('Original app gone before guardian')
    env, cwd = environment(app), os.readlink('/proc/%d/cwd' % app['pid'])
    ident('guardian', proc(os.getpid())); atomic('guardian.ready', 'ARMED\n')
    child = None
    try:
        with open(os.devnull, 'rb') as inp, open(ROOT + '/worker.stdout.raw', 'ab', buffering=0) as out, open(ROOT + '/worker.stderr.raw', 'ab', buffering=0) as err:
            child = subprocess.Popen([sys.executable, '-B', SELF, 'worker'], stdin=inp, stdout=out, stderr=err, start_new_session=True, close_fds=True)
        row = proc(child.pid); ident('worker', row)
        until = time.monotonic() + 600
        while child.poll() is None and not stop_requested() and time.monotonic() < until: time.sleep(.2)
        log('GUARDIAN_RECOVERY', worker_exit=child.poll(), requested=stop_requested())
    finally:
        stopped = True
        if child and child.poll() is None:
            try:
                child.terminate()
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=3)
            except Exception as exc:
                stopped = child.poll() is not None; log('WORKER_STOP_ERROR', error=str(exc))
        if stopped: recover(env, cwd)
        else: log('RECOVERY_NEEDS_ATTENTION', error='Worker not stopped, refuse parallel original')


def main():
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, handler)
    command = sys.argv[1]
    if command == 'start': start()
    elif command == 'guard': guard()
    elif command == 'worker': worker()
    elif command == 'stop': atomic('stop.request', 'USER_STOP\n'); print('RESULT=' + repr(dict(stop_requested=True)))
    elif command == 'play':
        if not os.path.exists(ROOT + '/ready') or os.path.exists(ROOT + '/result.json') or stop_requested(): raise RuntimeError('Trial not ready')
        for number in (1, 2, 3):
            if not os.path.exists(ROOT + '/play-%d.request' % number):
                atomic('play-%d.request' % number, 'pause\n' if len(sys.argv) > 2 and sys.argv[2] == 'pause' else 'normal\n')
                print('RESULT=' + repr(dict(play_requested=number))); break
        else: raise RuntimeError('Three playback limit reached')
    elif command == 'status':
        files = {name: read(ROOT + '/' + name, 131072).decode('utf-8', 'replace') for name in ('result.json', 'events.jsonl') if os.path.isfile(ROOT + '/' + name)}
        print('RESULT=' + repr(dict(ready=os.path.exists(ROOT + '/ready'), complete=os.path.exists(ROOT + '/result.json'), idle=idle_fields(), files=files)))
    else: raise RuntimeError('Unknown trial command')


if __name__ == '__main__': main()
