"""Small HTTP/1.x subset for the pen's stripped Python 3.5 runtime.

No http.server, email, html, socketserver, fcntl or third-party dependencies.
One request per connection, four workers, bounded headers/body/time, no chunked
requests, no keep-alive, no generic file serving and no CGI. Application code
must still authorize Host/Origin/token and confine every filesystem operation.
"""
import re
import socket
import threading
import time

MAX_BODY = 64 * 1024 * 1024
MAX_HEADERS = 16384
REASONS = {200:'OK', 400:'Bad Request', 403:'Forbidden', 404:'Not Found',
           405:'Method Not Allowed', 408:'Request Timeout', 409:'Conflict',
           411:'Length Required', 413:'Payload Too Large', 431:'Headers Too Large',
           500:'Internal Server Error', 503:'Service Unavailable'}


class Headers:
    def __init__(self): self.values = {}
    def add(self, key, value): self.values.setdefault(key.lower(), []).append(value)
    def get(self, key, default=None): return self.values.get(key.lower(), [default])[0]
    def get_all(self, key, default=None): return self.values.get(key.lower(), default)


class BodyStream:
    def __init__(self, request, initial, remaining, deadline, stopping):
        self.request, self.buffer = request, initial
        self.remaining, self.deadline = remaining, deadline
        self.stopping = stopping

    def read(self, size):
        size = min(size, self.remaining)
        if size <= 0: return b''
        chunks = [self.buffer[:size]]
        self.buffer = self.buffer[size:]
        count = len(chunks[0])
        idle_deadline = time.monotonic()+12
        while count < size:
            if self.stopping.is_set(): raise OSError('server stopped')
            remaining = self.deadline-time.monotonic()
            if remaining <= 0 or time.monotonic()>=idle_deadline: raise OSError('request deadline exceeded')
            self.request.settimeout(min(.25, remaining))
            try: block = self.request.recv(min(65536, size-count))
            except socket.timeout: continue
            if not block: break
            chunks.append(block); count += len(block)
            idle_deadline = time.monotonic()+12
        self.remaining -= count
        return b''.join(chunks)


class SocketOutput:
    def __init__(self, request, deadline): self.request, self.deadline = request, deadline
    def write(self, data):
        remaining = self.deadline-time.monotonic()
        if remaining <= 0: raise OSError('request deadline exceeded')
        self.request.settimeout(min(12, remaining))
        self.request.sendall(data)


class BaseHTTPRequestHandler:
    def __init__(self, request, address, server):
        self.request, self.client_address, self.server = request, address, server
        self.response_started = False
        self.deadline = time.monotonic()+180
        self.setup()
        self.handle()

    def setup(self): self.wfile = SocketOutput(self.request, self.deadline)

    def error(self, code):
        data = (REASONS[code]+'\n').encode('ascii')
        self.send_response(code)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers(); self.wfile.write(data)

    def handle(self):
        header_deadline = time.monotonic()+4
        data = b''
        while b'\r\n\r\n' not in data:
            remaining = header_deadline-time.monotonic()
            if remaining <= 0: self.error(408); return
            self.request.settimeout(remaining)
            try: block = self.request.recv(4096)
            except socket.timeout: self.error(408); return
            if not block: return
            data += block
            # The final read can contain initial body bytes, which are not headers.
            boundary = data.find(b'\r\n\r\n')
            if (boundary < 0 and len(data)>MAX_HEADERS) or boundary>MAX_HEADERS:
                self.error(431); return
        head, initial = data.split(b'\r\n\r\n', 1)
        lines = head.split(b'\r\n')
        match = re.match(br'^(GET|POST) ([^\x00-\x20\x7f]{1,4096}) HTTP/1\.[01]$', lines[0])
        if not match:
            self.error(400 if lines[0].startswith((b'GET ',b'POST ')) else 405); return
        try: self.command, self.path = match.group(1).decode('ascii'), match.group(2).decode('ascii')
        except UnicodeError: self.error(400); return
        self.headers = Headers()
        if len(lines)>65: self.error(431); return
        for line in lines[1:]:
            parts = line.split(b':',1)
            if (len(parts)!=2 or len(line)>8192 or
                    not re.match(br"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$", parts[0]) or
                    re.search(br'[\x00-\x08\x0a-\x1f\x7f]', parts[1])):
                self.error(400); return
            self.headers.add(parts[0].decode('ascii'), parts[1].decode('latin1').strip(' \t'))
        if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Expect'):
            self.error(400); return
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths)>1 or (lengths and not re.match(r'^[0-9]{1,10}$', lengths[0])):
            self.error(400); return
        length = int(lengths[0]) if lengths else 0
        if length>MAX_BODY: self.error(413); return
        if self.command=='POST' and not lengths: self.error(411); return
        if self.command=='GET' and length: self.error(400); return
        self.rfile = BodyStream(self.request, initial[:length], length, self.deadline, self.server.stopping)
        # Small forms can arrive in a separate TCP packet. Rejecting a route
        # before reading that packet closes with unread bytes and may reset the
        # connection (notably on Windows), hiding the HTTP status from the UI.
        # Buffer at most 4 KiB with a four-second deadline, then replay the bytes
        # to the authorized handler. Larger uploads remain streaming/bounded.
        if 0 < length <= 4096:
            self.rfile.deadline = min(self.deadline, time.monotonic()+4)
            try: body = self.rfile.read(length)
            except OSError:
                if not self.server.stopping.is_set(): self.error(408)
                return
            if len(body) != length: self.error(400); return
            self.rfile = BodyStream(self.request, body, length, self.deadline, self.server.stopping)
        getattr(self, 'do_'+self.command)()

    def send_response(self, code):
        if self.response_started: raise OSError('response already started')
        self.out_headers = ['HTTP/1.0 '+str(code)+' '+REASONS.get(code,'Error'), 'Connection: close']

    def send_header(self, name, value):
        if '\r' in name+value or '\n' in name+value: raise ValueError('invalid response header')
        self.out_headers.append(name+': '+value)

    def end_headers(self):
        self.response_started = True
        self.wfile.write(('\r\n'.join(self.out_headers)+'\r\n\r\n').encode('latin1'))


class HTTPServer:
    """Four bounded workers; shutdown also interrupts our active transfers."""
    def __init__(self, address, handler):
        self.handler = handler
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.socket.bind(address); self.socket.listen(4); self.socket.settimeout(0.2)
        except Exception:
            self.socket.close(); raise
        self.server_address = self.socket.getsockname()
        self.stopping = threading.Event()
        self.worker_lock = threading.Lock()
        self.workers = {}
        self.slots = threading.BoundedSemaphore(4)

    def serve_forever(self):
        while not self.stopping.is_set():
            try: request, address = self.socket.accept()
            except socket.timeout: continue
            except OSError:
                if self.stopping.is_set(): break
                raise
            if not self.slots.acquire(False): request.close(); continue
            worker = threading.Thread(target=self.process, args=(request,address))
            worker.daemon = True
            with self.worker_lock: self.workers[request] = worker
            try: worker.start()
            except Exception:
                with self.worker_lock: self.workers.pop(request,None)
                self.slots.release(); request.close(); raise

    def process(self, request, address):
        try:
            if not self.stopping.is_set(): self.handler(request,address,self)
        except (OSError, ValueError): pass
        except Exception: self.handle_error(request,address)
        finally:
            request.close()
            with self.worker_lock: self.workers.pop(request,None)
            self.slots.release()

    def shutdown(self):
        self.stopping.set()
        self.socket.close()
        with self.worker_lock: requests = list(self.workers)
        for request in requests:
            try: request.shutdown(socket.SHUT_RDWR)
            except OSError: pass

    def server_close(self):
        self.shutdown()
        with self.worker_lock: workers = list(self.workers.values())
        deadline = time.monotonic()+2
        for worker in workers:
            if worker is not threading.current_thread(): worker.join(max(0,deadline-time.monotonic()))

    def handle_error(self, request, address): pass
