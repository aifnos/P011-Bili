"""Private loopback range relay: a cached opening segment plus HTTPS tail.

No public URL proxy, credentials, directory listing or persistent URL map.
Only opaque per-session handles reach the decoder. Python 3.5 compatible.
"""
import os
import re
import stat
import threading
import subprocess
import json
import select
from minhttp import BaseHTTPRequestHandler, HTTPServer


class CountedSlots:
    """Bounded relay admission with numeric overload evidence."""
    def __init__(self,relay,count):self.relay=relay;self.slots=threading.BoundedSemaphore(count);self.active=0
    def acquire(self,blocking=True):
        # A decoder range-seek can overlap the just-closed request briefly.
        # Allow bounded cleanup grace, never add unbounded transfer threads.
        ok=self.slots.acquire() if blocking else self.slots.acquire(timeout=.5)
        with self.relay.lock:
            if ok:
                self.active+=1
                self.relay.stats['workers_peak']=max(self.active,self.relay.stats['workers_peak'])
            else:self.relay.stats['busy_rejected']+=1
        return ok
    def release(self):
        with self.relay.lock:self.active-=1
        self.slots.release()


class ClientDisconnected(OSError):pass


def byte_range(value, total):
    if value is None:return 0,total-1,200
    m=re.match(r'^bytes=([0-9]{1,12})-([0-9]{1,12})?$',value)
    if not m:raise ValueError('range')
    start=int(m.group(1));end=min(int(m.group(2)) if m.group(2) else total-1,total-1)
    if start>end:raise ValueError('range')
    return start,end,206


class MediaRelay:
    def __init__(self, backend):
        self.backend=backend;self.lock=threading.RLock();self.rows={};self.closed=False
        self.stats=dict(prefix_bytes=0,tail_bytes=0,requests=0,failures=0,workers_peak=0,busy_rejected=0,client_closed=0,upstream_errors=0,prefix_errors=0)
        self.server=HTTPServer(('127.0.0.1',0),RelayHandler);self.server.relay=self
        self.server.slots=CountedSlots(self,4)
        self.host='127.0.0.1:'+str(self.server.server_address[1]);self.path='/'+os.urandom(24).hex()+'/'
        self.endpoint='http://'+self.host+self.path
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.daemon=True;self.thread.start()

    def register(self,key,data,meta):
        if not re.match(r'^[a-f0-9]{16}$',key):raise ValueError('key')
        result={};pending={}
        for field,suffix in (('video','v'),('audio','a')):
            if not data.get(field):continue
            spec=meta.get(field,{})
            size,total=spec.get('bytes'),spec.get('total')
            if type(size) is not int or type(total) is not int or not 0<size<=min(total,4*1024*1024) or total>8*1024**3:raise ValueError('size')
            name=key+'-'+suffix;path=os.path.join(self.backend.root,'preload',name+'.head')
            info=os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size!=size:raise ValueError('prefix')
            pending[name]=dict(path=path,size=size,total=total,url=data[field])
            result[field]=self.endpoint+name
        with self.lock:
            if self.closed:raise ValueError('closed')
            if len(self.rows)+len(pending)>12:raise ValueError('bound')
            self.rows.update(pending)
        return result

    def remove(self,key):
        with self.lock:
            for suffix in ('-v','-a'):self.rows.pop(key+suffix,None)

    def read_pipe(self,p,size,request):
        while True:
            if self.closed or self.backend.stopping.is_set():raise ClientDisconnected('stopped')
            # POSIX pipes and sockets are selectable on the actual pen. The
            # Windows host byte-fixture has no device socket and uses FileIO.
            if os.name!='nt':
                ready,_,_=select.select([p.stdout]+([request] if request else []),[],[],.25)
                if request in ready:raise ClientDisconnected('decoder closed')
                if p.stdout not in ready:continue
            return os.read(p.stdout.fileno(),size)

    def stream(self,row,start,end,request=None):
        # Fixed operation through a pipe: never put CDN URLs in argv/logs.
        b=self.backend
        while start<=end:
            last=min(end,start+4*1024*1024-1)
            with b.lock:
                if b.stopping.is_set() or self.closed:raise OSError('stopped')
                p=subprocess.Popen([b.api],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=b.env,bufsize=0)
                b.children.add(p)
            try:
                payload=dict(op='media_stream',args=dict(url=row['url'],start=start,end=last,total=row['total']))
                p.stdin.write(json.dumps(payload,ensure_ascii=True).encode('ascii'));p.stdin.close()
                header=b''
                while len(header)<6:
                    block=self.read_pipe(p,6-len(header),request)
                    if not block:break
                    header+=block
                if header!=b'READY\n':raise OSError('range upstream')
                remaining=last-start+1
                while remaining:
                    # Header and media share one unbuffered reader. Never mix
                    # buffered readline() with os.read() and lose MP4 bytes.
                    # Disconnect detection also reaps stalled obsolete tails.
                    block=self.read_pipe(p,min(65536,remaining),request)
                    if not block:raise OSError('short upstream')
                    remaining-=len(block);yield block
                if p.wait(timeout=2)!=0:raise OSError('upstream exit')
            finally:
                if p.poll() is None:p.kill()
                p.wait();p.stdout.close()
                with b.lock:b.children.discard(p)
            start=last+1

    def close(self):
        with self.lock:self.closed=True;self.rows.clear()
        self.server.server_close();self.thread.join(1)


class RelayHandler(BaseHTTPRequestHandler):
    def send_response(self,code):
        super().send_response(code)
        if code in (206,416):self.out_headers[0]='HTTP/1.0 '+str(code)+' '+{206:'Partial Content',416:'Range Not Satisfiable'}[code]
    def do_POST(self):self.error(403)
    def do_GET(self):
        r=self.server.relay
        if (self.headers.get_all('Host',[])!=[r.host] or self.headers.get('Origin') is not None or
                self.headers.get('Sec-Fetch-Site') is not None or not self.path.startswith(r.path)):
            self.error(403);return
        with r.lock:row=r.rows.get(self.path[len(r.path):])
        if not row:self.error(404);return
        values=self.headers.get_all('Range',[])
        try:
            if len(values)>1:raise ValueError('range')
            start,end,code=byte_range(values[0] if values else None,row['total'])
        except ValueError:
            self.send_response(416);self.send_header('Content-Range','bytes */'+str(row['total']));self.send_header('Content-Length','0');self.end_headers();return
        source=None;phase='prefix'
        try:
            # Open before headers; eviction may unlink later, but an accepted
            # range owns its fd until this connection completes.
            fd=os.open(row['path'],os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'rb') as prefix:
                info=os.fstat(prefix.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size!=row['size']:raise OSError('prefix changed')
                self.send_response(code);self.send_header('Content-Type','video/mp4')
                self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
                self.send_header('Cache-Control','no-store')
                if code==206:self.send_header('Content-Range','bytes {}-{}/{}'.format(start,end,row['total']))
                self.end_headers()
                with r.lock:r.stats['requests']+=1
                prefix.seek(start)
                while start<=end and start<row['size']:
                    block=prefix.read(min(65536,end-start+1,row['size']-start))
                    if not block:raise OSError('short prefix')
                    phase='client';self.wfile.write(block);phase='prefix';start+=len(block)
                    with r.lock:r.stats['prefix_bytes']+=len(block)
            if start<=end:
                source=r.stream(row,start,end,self.request)
                phase='upstream'
                for block in source:
                    phase='client';self.wfile.write(block);phase='upstream'
                    with r.lock:r.stats['tail_bytes']+=len(block)
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            with r.lock:
                r.stats['failures']+=1
                kind='client_closed' if isinstance(exc,ClientDisconnected) else {'client':'client_closed','upstream':'upstream_errors','prefix':'prefix_errors'}[phase]
                r.stats[kind]+=1
            if not self.response_started:self.error(503)
        finally:
            if source:source.close()
