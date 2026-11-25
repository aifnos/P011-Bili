"""Persistent loopback listener; a native QML page owns each Bili session.

The listener may start under PID 1. No backend, login request or media process
exists until an authenticated native bootstrap. Business routes remain the
fixed routes in service.Handler. Python 3.5 compatible.
"""
from __future__ import print_function
import ctypes
import os
import re
import signal
import stat
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import service as legacy
from story_cache import purge

HEARTBEAT_SECONDS = 15
SESSION_SECONDS = 86400
CLOSE_SECONDS = 20


def marker(name, failed=False):
    if name not in ('READY', 'STOPPED', 'SESSION_OPENED', 'SESSION_CLOSED',
                    'SESSION_EXPIRED', 'SESSION_CLOSE_FAILED', 'REQUEST_FAILED'):
        raise ValueError('unknown lifecycle marker')
    stream = sys.stderr if failed else sys.stdout
    stream.write('P011_BILI_FORMAL ' + name + '\n')
    stream.flush()


class _TrackedThreading:
    """Track only threads created by this process's imported service module.

    A facade leaves the actual threading module and other libraries intact.
    Bound targets and nested closures identify the owning FormalBackend; this
    covers the inherited workers, player bridge/reaper and delayed helpers.
    """
    def __getattr__(self, name):
        return getattr(threading, name)

    def Thread(self, *args, **kwargs):
        target = kwargs.get('target', args[1] if len(args) > 1 else None)
        owner = getattr(target, '__self__', None)
        if not isinstance(owner, FormalBackend):
            owner = None
            for cell in getattr(target, '__closure__', ()) or ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, FormalBackend):
                    owner = value
                    break
        if owner is None:
            return threading.Thread(*args, **kwargs)
        call_args = kwargs.get('args', args[3] if len(args) > 3 else ())
        call_kwargs = kwargs.get('kwargs', args[4] if len(args) > 4 else None) or {}

        def run():
            current = threading.current_thread()
            with owner.formal_thread_lock:
                if owner.formal_closing:
                    return
                owner.formal_threads.add(current)
            try:
                target(*call_args, **call_kwargs)
            except Exception:
                # The default Thread traceback can include helper arguments or
                # signed media data. Quarantine this session using fixed text.
                owner.formal_thread_failed = True
                owner.stopping.set()
                marker('REQUEST_FAILED', True)
            finally:
                with owner.formal_thread_lock:
                    owner.formal_threads.discard(current)

        options = dict(kwargs, target=run, args=(), kwargs={})
        if args:
            positional = list(args)
            while len(positional) < 2:
                positional.append(None)
            positional[1] = run
            if len(positional) > 3:
                positional[3] = ()
            if len(positional) > 4:
                positional[4] = {}
            options.pop('target', None)
            if len(positional) > 3:
                options.pop('args', None)
            if len(positional) > 4:
                options.pop('kwargs', None)
            return threading.Thread(*positional, **options)
        return threading.Thread(**options)


class FormalBackend(legacy.Backend):
    def __init__(self, *args, **kwargs):
        self.formal_thread_lock = threading.Lock()
        self.formal_threads = set()
        self.formal_closing = False
        self.formal_thread_failed = False
        super(FormalBackend, self).__init__(*args, **kwargs)

    def close(self):
        until = time.monotonic() + CLOSE_SECONDS
        with self.formal_thread_lock:
            self.formal_closing = True
        self.stopping.set()
        super(FormalBackend, self).close()
        cache = self.story_cache
        if cache is not None:
            stats = cache.close()
            if not stats.get('worker_stopped'):
                raise RuntimeError('session cache still active')
        with self.formal_thread_lock:
            threads = list(self.formal_threads)
        for worker in threads:
            if worker is not threading.current_thread():
                worker.join(max(0, until - time.monotonic()))
        with self.formal_thread_lock:
            if any(worker.is_alive() for worker in self.formal_threads):
                raise RuntimeError('session thread still active')
        with self.lock:
            if any(child.poll() is None for child in self.children):
                raise RuntimeError('session child still active')
        purge(self.root)


# service is private to this listener process; never alter threading.Thread.
legacy.threading = _TrackedThreading()


def atomic_json(root, name, value):
    path = os.path.join(root, name)
    if os.path.lexists(path):
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or os.path.islink(path) or
                hasattr(os, 'getuid') and info.st_uid != os.getuid()):
            raise ValueError('unsafe runtime file')
    temp = path + '.new-' + os.urandom(8).hex()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w') as output:
            legacy.json.dump(value, output)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    info = os.lstat(path)
    return info.st_dev, info.st_ino


class FormalServer(legacy.HTTPServer):
    def __init__(self, root, session, backend_factory, clock=time.monotonic,
                 heartbeat_seconds=HEARTBEAT_SECONDS):
        self.root, self.session = root, session
        self.backend_factory, self.clock = backend_factory, clock
        self.heartbeat_seconds = heartbeat_seconds
        self.session_lock = threading.RLock()
        self.backend = None
        self.last_heartbeat = None
        self.session_failed = False
        self.monitor = None
        super(FormalServer, self).__init__(('127.0.0.1', 0), FormalHandler)
        self.expected_host = '127.0.0.1:' + str(self.server_address[1])
        try:
            self.endpoint_identity = atomic_json(root, 'bili-endpoint.json',
                {'url': 'http://' + self.expected_host, 'formal': True})
            self.release_lease()
        except Exception:
            super(FormalServer, self).server_close()
            raise

    def release_lease(self):
        atomic_json(self.root, 'lease.json',
                    {'session': self.session, 'seq': -1, 'active': False})

    def bootstrap(self):
        if self.session_failed:
            raise RuntimeError('session cleanup failed')
        if self.backend is not None:
            raise legacy.Failure('CANCELED')
        backend = self.backend_factory()
        self.backend = backend
        try:
            token = backend.bootstrap()
        except Exception:
            self.close_session()
            raise
        self.last_heartbeat = self.clock()
        marker('SESSION_OPENED')
        return token

    def close_session(self, expired=False):
        backend = self.backend
        if backend is None:
            return
        error = None
        try:
            backend.stop_player()
        except Exception:
            error = True
        try:
            backend.close()
        except Exception:
            error = True
        try:
            self.release_lease()
        except Exception:
            error = True
        if error:
            # Keep the old owner quarantined. A new session must never run
            # beside an owner whose bounded cleanup could not be confirmed.
            self.session_failed = True
            marker('SESSION_CLOSE_FAILED', True)
            raise RuntimeError('session cleanup failed')
        self.backend = None
        self.last_heartbeat = None
        marker('SESSION_EXPIRED' if expired else 'SESSION_CLOSED')

    def check_session(self):
        with self.session_lock:
            if self.backend is None or self.session_failed:
                return
            now = self.clock()
            if (getattr(self.backend, 'formal_thread_failed', False) or
                    now - self.last_heartbeat >= self.heartbeat_seconds or
                    time.monotonic() >= self.backend.deadline):
                self.close_session(expired=True)

    def watch(self):
        while not self.stopping.wait(.25):
            try:
                self.check_session()
            except Exception:
                self.shutdown()
                return

    def serve_forever(self):
        self.monitor = threading.Thread(target=self.watch)
        self.monitor.daemon = True
        self.monitor.start()
        super(FormalServer, self).serve_forever()

    def handle_error(self, request, address):
        marker('REQUEST_FAILED', True)

    def server_close(self):
        super(FormalServer, self).server_close()
        if self.monitor is not None and self.monitor is not threading.current_thread():
            self.monitor.join(1)
        with self.session_lock:
            self.close_session()
        endpoint = os.path.join(self.root, 'bili-endpoint.json')
        if os.path.lexists(endpoint):
            info = os.lstat(endpoint)
            if ((info.st_dev, info.st_ino) != self.endpoint_identity or
                    not stat.S_ISREG(info.st_mode) or os.path.islink(endpoint)):
                raise ValueError('endpoint identity changed')
            os.unlink(endpoint)


class FormalHandler(legacy.Handler):
    def authorized(self, bootstrap=False):
        if bootstrap:
            return (super(FormalHandler, self).authorized(True) and
                    self.headers.get_all('X-P011-Native-UI', []) == ['bili-qml-runtime'])
        return (self.server.backend is not None and not self.server.session_failed and
                self.server.backend.bootstrapped and
                super(FormalHandler, self).authorized(False))

    def do_POST(self):
        with self.server.session_lock:
            bootstrap = self.path == '/bootstrap'
            if not self.authorized(bootstrap):
                self.error(403)
                return
            if self.path not in ('/bootstrap', '/formal/heartbeat', '/exit'):
                return super(FormalHandler, self).do_POST()
            length = int(self.headers.get('Content-Length', '0'))
            if length > 4096:
                self.error(413)
                return
            try:
                raw = self.rfile.read(length)
                if len(raw) != length or not isinstance(legacy.json.loads(raw.decode('utf-8')), dict):
                    raise ValueError('invalid body')
                if bootstrap:
                    self.reply({'token': self.server.bootstrap()})
                elif self.path == '/formal/heartbeat':
                    self.server.last_heartbeat = self.server.clock()
                    self.reply({'ok': True})
                else:
                    self.server.close_session()
                    self.reply({'ok': True})
            except (ValueError, UnicodeError):
                self.reply(legacy.error_result(legacy.Failure('BAD_INPUT')), 400)
            except legacy.Failure as error:
                self.reply(legacy.error_result(error), 409 if bootstrap else 200)
            except Exception:
                marker('REQUEST_FAILED', True)
                self.reply(legacy.error_result(legacy.Failure('INTERNAL')), 503)

    def do_GET(self):
        with self.server.session_lock:
            return super(FormalHandler, self).do_GET()


def backend_factory(config):
    from native_safety import owned_directory
    root = owned_directory(config.REMOTE, create=False)
    account = owned_directory('/mnt/data/p011-toolbox/bili-account', create=True)
    os.chmod(account, 0o700)
    cookie = os.path.join(account, 'cookies.txt')
    if os.path.lexists(cookie):
        info = os.lstat(cookie)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1):
            raise ValueError('unsafe private account file')
        os.chmod(cookie, 0o600)
    env = dict(os.environ, LD_LIBRARY_PATH=config.MEDIA + '/lib',
               XDG_RUNTIME_DIR='/run/user/0', WAYLAND_DISPLAY='wayland-0',
               SDL_VIDEODRIVER='wayland', P011_AWAKE_LEASE=root + '/lease.json',
               P011_AWAKE_SESSION=config.SESSION)
    for key in ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY',
                'HTTPS_PROXY', 'ALL_PROXY', 'LD_PRELOAD', 'SDL_DYNAMIC_API'):
        env.pop(key, None)

    def create():
        backend = FormalBackend(root, config.MEDIA + '/bin/bili-api',
            config.MEDIA + '/bin/bili-player', account, env,
            lifetime=SESSION_SECONDS, automation=False, protocol=2,
            hardware_required='bin/bili-hw' in config.MEDIA_FILES)
        try:
            backend.preferences = legacy.Preferences('/mnt/data/p011-toolbox/bili-preferences')
            backend.playback_settings = backend.preferences.load()
            backend.library = legacy.Library('/mnt/data/p011-toolbox/bili-library')
            return backend
        except Exception:
            backend.close()
            raise
    return create


def process_lock(root):
    path = os.path.join(root, 'formal-service.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('unsafe service lock')
        os.fchmod(fd, 0o600)
        if ctypes.CDLL(None, use_errno=True).flock(fd, 2 | 4):
            raise RuntimeError('formal listener already running')
        return fd
    except Exception:
        os.close(fd)
        raise


def main():
    import config as config
    from native_safety import owned_directory
    if (not re.match(r'^/mnt/data/p011-toolbox/bili-awake/[a-f0-9]{24}$', config.REMOTE) or
            config.SESSION != config.REMOTE.rsplit('/', 1)[1]):
        raise ValueError('unexpected formal runtime identity')
    root = owned_directory(config.REMOTE, create=False)
    libc = ctypes.CDLL(None, use_errno=True)
    class Limit(ctypes.Structure):
        _fields_ = [('cur', ctypes.c_ulong), ('max', ctypes.c_ulong)]
    if libc.setrlimit(4, ctypes.byref(Limit(0, 0))):
        raise RuntimeError('cannot disable core dumps')
    lock_fd = process_lock(root)
    server = None
    try:
        server = FormalServer(root, config.SESSION, backend_factory(config))
        def stop(signum, frame):
            server.shutdown()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        marker('READY')
        server.serve_forever()
    finally:
        try:
            if server is not None:
                server.server_close()
        finally:
            os.close(lock_fd)
            marker('STOPPED')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Exception text can contain paths or private media/helper data.
        marker('REQUEST_FAILED', True)
        raise SystemExit(1)
