"""HOST-only real TCP/session checks. No ADB, remote API or media library."""
import ast
import contextlib
import http.client
import io
import json
import os
import pathlib
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

BASE = pathlib.Path(__file__).resolve().parents[2]
ORIGINAL_THREAD = threading.Thread
# BASE is the Bili worktree; its sibling supplies the stripped HTTP runtime.
sys.path.insert(0, str(BASE.parent / 'ToolboxNext-v0.5.1-native/runtime'))
sys.path.insert(0, str(BASE / 'client'))
sys.path.insert(0, str(BASE / 'formal/runtime'))
import formal_service as formal
from story_cache import StoryCache


class Clock:
    def __init__(self):
        self.value = 0.0
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


class FormalServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, 'runtime')
        self.account = os.path.join(self.temp.name, 'account')
        os.mkdir(self.root)
        os.mkdir(self.account)
        self.clock = Clock()
        self.created = []
        self.helper_calls = []
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.capture_out = contextlib.redirect_stdout(self.stdout)
        self.capture_err = contextlib.redirect_stderr(self.stderr)
        self.capture_out.__enter__()
        self.capture_err.__enter__()
        self.server = formal.FormalServer(self.root, 'a' * 24,
                                         self.create_backend, clock=self.clock)
        self.listener = threading.Thread(target=self.server.serve_forever)
        self.listener.start()

    def tearDown(self):
        try:
            self.server.shutdown()
            self.listener.join(3)
            self.assertFalse(self.listener.is_alive())
            self.server.server_close()
            self.assertIsNone(self.server.backend)
            for backend in self.created:
                self.assertTrue(backend.stopping.is_set())
                self.assertFalse(any(worker.is_alive() for worker in backend.threads))
                self.assertFalse(any(child.poll() is None for child in backend.children))
        finally:
            self.capture_err.__exit__(None, None, None)
            self.capture_out.__exit__(None, None, None)
            self.temp.cleanup()

    def helper(self, op, args):
        self.helper_calls.append((op, args))
        if op == 'recommend':
            return {'items': [{'bvid': 'BV1Da411Y7U4', 'title': 'HOST fixture'}],
                    'more': False}
        raise AssertionError('unexpected fixed helper operation')

    def create_backend(self):
        backend = formal.FormalBackend(self.root, 'unused-api', 'unused-player',
            self.account, {}, helper=self.helper, lifetime=formal.SESSION_SECONDS,
            automation=False, protocol=2)
        backend.preferences = formal.legacy.Preferences(os.path.join(self.temp.name, 'preferences'))
        backend.playback_settings = backend.preferences.load()
        backend.library = formal.legacy.Library(os.path.join(self.temp.name, 'library'))
        self.created.append(backend)
        return backend

    def request(self, path, body=None, token=None, native=False, headers=None,
                method='POST'):
        values = dict(headers or {})
        if token is not None:
            values['X-P011-Token'] = token
        if native:
            values['X-P011-Native-UI'] = 'bili-qml-runtime'
        raw = b'' if body is None else json.dumps(body).encode('utf-8')
        if method == 'POST':
            values['Content-Type'] = 'application/json'
            values['Content-Length'] = str(len(raw))
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=4)
        try:
            connection.request(method, path, raw if method == 'POST' else None, values)
            response = connection.getresponse()
            result = response.read()
            try:
                result = json.loads(result.decode('utf-8'))
            except ValueError:
                pass
            return response.status, result
        finally:
            connection.close()

    def bootstrap(self):
        code, result = self.request('/bootstrap', {}, native=True)
        self.assertEqual(code, 200)
        return result['token']

    def test_idle_listener_can_wait_before_first_native_bootstrap(self):
        self.clock.advance(90000)
        self.server.check_session()
        self.assertEqual(self.created, [])
        self.assertIsNone(self.server.backend)
        token = self.bootstrap()
        self.assertTrue(token)
        self.assertEqual(len(self.created), 1)
        self.assertGreater(self.created[0].deadline - time.monotonic(), 86395)
        self.assertFalse(self.created[0].automation)

    def test_bootstrap_host_origin_and_native_header_fail_before_backend_creation(self):
        attempts = [({}, False), ({'Host': 'localhost:1'}, True),
                    ({'Origin': 'http://example.invalid'}, True),
                    ({'Sec-Fetch-Site': 'same-origin'}, True),
                    ({'X-P011-Native-UI': 'wrong'}, False)]
        for headers, native in attempts:
            code, _ = self.request('/bootstrap', {}, native=native, headers=headers)
            self.assertEqual(code, 403)
        self.assertEqual(self.created, [])
        self.assertEqual(self.helper_calls, [])

    def test_duplicate_host_and_native_headers_are_rejected(self):
        for duplicate in ('Host', 'X-P011-Native-UI'):
            headers = ['Host: ' + self.server.expected_host,
                       'X-P011-Native-UI: bili-qml-runtime']
            headers.append(duplicate + ': ' + (self.server.expected_host
                if duplicate == 'Host' else 'bili-qml-runtime'))
            raw = ('POST /bootstrap HTTP/1.0\r\n' + '\r\n'.join(headers) +
                   '\r\nContent-Length: 2\r\n\r\n{}').encode('ascii')
            client = socket.create_connection(self.server.server_address, timeout=3)
            try:
                client.sendall(raw)
                data = b''
                while True:
                    block = client.recv(4096)
                    if not block:
                        break
                    data += block
                self.assertTrue(data.startswith(b'HTTP/1.0 403 '))
            finally:
                client.close()
        self.assertEqual(self.created, [])

    def test_exit_preserves_listener_and_rotates_session_token(self):
        cookie = os.path.join(self.account, 'cookies.txt')
        with open(cookie, 'wb') as output:
            output.write(b'HOST private account sentinel')
        first = self.bootstrap()
        backend = self.server.backend
        code, result = self.request('/bootstrap', {}, native=True)
        self.assertEqual(code, 409)
        self.assertEqual(result['error'], 'CANCELED')
        self.assertIs(self.server.backend, backend)
        self.assertEqual(self.request('/exit', {}, token='wrong')[0], 403)
        self.assertEqual(self.request('/exit', {}, token=first), (200, {'ok': True}))
        self.assertIsNone(self.server.backend)
        self.assertFalse(self.server.stopping.is_set())
        self.assertFalse(os.path.exists(os.path.join(self.root, 'stop.request')))
        with open(cookie, 'rb') as source:
            self.assertEqual(source.read(), b'HOST private account sentinel')
        self.assertEqual(self.request('/state', token=first, method='GET')[0], 403)
        second = self.bootstrap()
        self.assertNotEqual(first, second)
        self.assertEqual(self.request('/formal/heartbeat', {}, token=first)[0], 403)
        self.assertEqual(self.request('/state', token=second, method='GET')[0], 200)

    def test_heartbeat_expiry_closes_real_child_and_cache_worker(self):
        token = self.bootstrap()
        backend = self.server.backend
        child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        backend.children.add(child)
        backend.player = child
        reaper = formal.legacy.threading.Thread(target=backend.reap_player, args=(child,))
        reaper.start()
        cache = StoryCache(self.root, lambda *a: None, lambda *a: None, lambda: False)
        backend.story_cache = cache
        self.clock.advance(14)
        self.server.check_session()
        self.assertIs(self.server.backend, backend)
        self.assertEqual(self.request('/formal/heartbeat', {}, token=token)[0], 200)
        self.clock.advance(14)
        self.server.check_session()
        self.assertIs(self.server.backend, backend)
        self.clock.advance(1.01)
        self.server.check_session()
        reaper.join(1)
        self.assertIsNone(self.server.backend)
        self.assertIsNotNone(child.poll())
        self.assertFalse(reaper.is_alive())
        self.assertFalse(cache.thread.is_alive())
        self.assertFalse(any(worker.is_alive() for worker in backend.threads))
        child.stdout.close()
        with open(os.path.join(self.root, 'lease.json')) as source:
            self.assertIs(json.load(source)['active'], False)
        self.assertNotEqual(token, self.bootstrap())

    def test_invalid_heartbeat_does_not_extend_lease(self):
        token = self.bootstrap()
        self.clock.advance(14)
        self.assertEqual(self.request('/formal/heartbeat', {}, token='invalid')[0], 403)
        self.assertEqual(self.request('/formal/heartbeat', [], token=token)[0], 400)
        self.assertEqual(self.server.last_heartbeat, 0)
        self.clock.advance(1.01)
        self.server.check_session()
        self.assertIsNone(self.server.backend)

    def test_fixed_session_deadline_is_not_renewed_by_heartbeat(self):
        token = self.bootstrap()
        self.server.backend.deadline = time.monotonic() - 1
        self.assertEqual(self.request('/formal/heartbeat', {}, token=token)[0], 200)
        self.server.check_session()
        self.assertIsNone(self.server.backend)

    def test_existing_fixed_job_routes_work_without_arbitrary_commands(self):
        token = self.bootstrap()
        code, result = self.request('/jobs', {'op': 'shell', 'args': {'command': 'fixture'}}, token=token)
        self.assertEqual(code, 200)
        self.assertEqual(result['error'], 'BAD_INPUT')
        self.assertEqual(self.helper_calls, [])
        code, result = self.request('/jobs', {'op': 'recommend', 'args': {'page': 1}}, token=token)
        self.assertEqual(code, 200)
        until = time.monotonic() + 2
        while time.monotonic() < until:
            code, answer = self.request('/jobs/' + result['job'], token=token, method='GET')
            if not answer.get('pending'):
                break
            time.sleep(.01)
        self.assertEqual(code, 200)
        self.assertTrue(answer['ok'])
        self.assertEqual(answer['data']['items'][0]['title'], 'HOST fixture')
        self.assertEqual(len(self.helper_calls), 1)
        self.assertEqual(self.request('/not-a-business-route', {}, token=token)[0], 404)

    def test_malformed_bootstrap_never_creates_backend(self):
        self.assertEqual(self.request('/bootstrap', [], native=True)[0], 400)
        # Send the over-limit header alone. Sending unread payload while the
        # server rejects it can become a Windows TCP reset instead of a visible
        # HTTP response; neither behavior should create a session.
        client = socket.create_connection(self.server.server_address, timeout=3)
        try:
            client.sendall(('POST /bootstrap HTTP/1.0\r\nHost: ' +
                self.server.expected_host + '\r\nX-P011-Native-UI: bili-qml-runtime'
                '\r\nContent-Length: 4097\r\n\r\n').encode('ascii'))
            self.assertTrue(client.recv(4096).startswith(b'HTTP/1.0 413 '))
        finally:
            client.close()
        self.assertEqual(self.created, [])

    def test_endpoint_is_loopback_private_and_removed_after_shutdown(self):
        endpoint = os.path.join(self.root, 'bili-endpoint.json')
        with open(endpoint) as source:
            value = json.load(source)
        self.assertEqual(value['url'], 'http://' + self.server.expected_host)
        self.assertTrue(value['formal'])
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        self.assertNotIn('token', value)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(os.stat(endpoint).st_mode), 0o600)

    def test_unexpected_endpoint_replacement_is_preserved(self):
        endpoint = os.path.join(self.root, 'bili-endpoint.json')
        replacement = endpoint + '.replacement'
        with open(replacement, 'w') as output:
            output.write('HOST replacement')
        os.replace(replacement, endpoint)
        self.server.shutdown()
        self.listener.join(2)
        with self.assertRaises(ValueError):
            self.server.server_close()
        with open(endpoint) as source:
            self.assertEqual(source.read(), 'HOST replacement')
        # Permit fixture teardown only after checking the refusal.
        info = os.stat(endpoint)
        self.server.endpoint_identity = info.st_dev, info.st_ino

    def test_legacy_threads_are_tracked_without_global_threading_patch(self):
        self.bootstrap()
        backend = self.server.backend
        self.assertIsNot(formal.legacy.threading, threading)
        self.assertIs(threading.Thread, ORIGINAL_THREAD)
        until = time.monotonic() + 1
        while time.monotonic() < until:
            with backend.formal_thread_lock:
                count = len(backend.formal_threads)
            if count == 2:
                break
            time.sleep(.01)
        self.assertEqual(count, 2)

    def test_watchdog_expires_session_without_an_http_request(self):
        self.bootstrap()
        self.clock.advance(15.01)
        until = time.monotonic() + 2
        while self.server.backend is not None and time.monotonic() < until:
            time.sleep(.01)
        self.assertIsNone(self.server.backend)
        self.assertFalse(self.server.stopping.is_set())

    def test_concurrent_bootstrap_creates_one_backend(self):
        replies = []
        workers = [threading.Thread(target=lambda: replies.append(
            self.request('/bootstrap', {}, native=True))) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(code for code, _ in replies), [200, 409])
        self.assertEqual(len(self.created), 1)

    def test_failed_cleanup_quarantines_owner_and_redacts_exception(self):
        token = self.bootstrap()
        backend = self.server.backend
        original = backend.close
        def fail():
            original()
            raise RuntimeError('HOST_SECRET_MUST_NOT_BE_LOGGED')
        backend.close = fail
        self.assertEqual(self.request('/exit', {}, token=token)[0], 503)
        self.assertTrue(self.server.session_failed)
        self.assertIs(self.server.backend, backend)
        self.assertEqual(self.request('/bootstrap', {}, native=True)[0], 503)
        self.assertEqual(len(self.created), 1)
        self.assertNotIn('HOST_SECRET_MUST_NOT_BE_LOGGED', self.stderr.getvalue())
        backend.close = original
        self.server.session_failed = False
        self.assertEqual(self.request('/exit', {}, token=token)[0], 200)

    def test_background_exception_is_redacted_and_ends_session(self):
        self.bootstrap()
        backend = self.server.backend
        def fail():
            backend.formal_thread_failed = False
            raise RuntimeError('HOST_BACKGROUND_SECRET')
        worker = formal.legacy.threading.Thread(target=fail)
        worker.start()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(backend.formal_thread_failed)
        self.server.check_session()
        self.assertIsNone(self.server.backend)
        self.assertNotIn('HOST_BACKGROUND_SECRET', self.stderr.getvalue())
        self.assertIn('P011_BILI_FORMAL REQUEST_FAILED', self.stderr.getvalue())


class FormalSourceTests(unittest.TestCase):
    def test_python35_syntax(self):
        source = pathlib.Path(formal.__file__).read_text(encoding='utf-8')
        ast.parse(source, feature_version=(3, 5))

    @unittest.skipIf(os.name == 'nt', 'POSIX lock and mode are device/Linux semantics')
    def test_singleton_lock_releases_without_deleting_stale_pid_files(self):
        with tempfile.TemporaryDirectory() as root:
            first = formal.process_lock(root)
            try:
                with self.assertRaises(RuntimeError):
                    formal.process_lock(root)
            finally:
                os.close(first)
            second = formal.process_lock(root)
            os.close(second)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(root, 'formal-service.lock')).st_mode), 0o600)

    @unittest.skipIf(os.name == 'nt', 'Windows terminate does not deliver POSIX SIGTERM')
    def test_actual_sigterm_closes_active_session_and_private_endpoint(self):
        script = '''import os,signal,sys
import formal_service as f
root=sys.argv[1]
lock=f.process_lock(root)
def create():
 return f.FormalBackend(root,'unused-api','unused-player',root,{},helper=lambda *a: {},lifetime=86400,automation=False,protocol=2)
server=f.FormalServer(root,'b'*24,create)
signal.signal(signal.SIGTERM,lambda sig,frame:server.shutdown())
print('HOST_SIGNAL_READY',flush=True)
try:server.serve_forever()
finally:
 server.server_close()
 os.close(lock)
print('HOST_SIGNAL_CLOSED',flush=True)
'''
        with tempfile.TemporaryDirectory() as root:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([
                str(BASE / 'formal/runtime'), str(BASE / 'client'),
                str(BASE.parent / 'ToolboxNext-v0.5.1-native/runtime')]))
            child = subprocess.Popen([sys.executable, '-u', '-c', script, root],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                endpoint = os.path.join(root, 'bili-endpoint.json')
                until = time.monotonic() + 3
                while not os.path.isfile(endpoint) and time.monotonic() < until and child.poll() is None:
                    time.sleep(.01)
                self.assertTrue(os.path.isfile(endpoint))
                with open(endpoint) as source:
                    url = json.load(source)['url']
                self.assertEqual(stat.S_IMODE(os.stat(endpoint).st_mode), 0o600)
                host = url[len('http://'):]
                connection = http.client.HTTPConnection(host, timeout=3)
                try:
                    connection.request('POST', '/bootstrap', '{}',
                                       {'X-P011-Native-UI': 'bili-qml-runtime'})
                    response = connection.getresponse()
                    payload = response.read()
                    self.assertEqual(response.status, 200)
                    token = json.loads(payload.decode('utf-8'))['token']
                finally:
                    connection.close()
                child.send_signal(signal.SIGTERM)
                stdout, stderr = child.communicate(timeout=6)
                self.assertEqual(child.returncode, 0, stderr.decode('utf-8', 'replace'))
                self.assertIn(b'HOST_SIGNAL_CLOSED', stdout)
                self.assertIn(b'P011_BILI_FORMAL SESSION_CLOSED', stdout)
                self.assertNotIn(token.encode('ascii'), stdout + stderr)
                self.assertFalse(os.path.exists(endpoint))
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
