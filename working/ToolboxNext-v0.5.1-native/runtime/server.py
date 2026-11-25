#!/usr/bin/env python3
"""P011 fixed-purpose loopback bridge + opt-in bounded LAN file transfer.

Python 3.5, no json stdlib dependency. No shell, D-Bus or firmware modification.
"""
import argparse
import hmac
import io
import os
import re
import signal
import subprocess
import threading
import time
import urllib.parse
from minhttp import BaseHTTPRequestHandler, HTTPServer
import p011_json as J
from storage import FileStore, components, kind, MAX_FILE
from metrics import Sampler


def local_addresses(preview=False):
    if preview:
        return [{'name':'host-preview', 'address':'127.0.0.1'}]
    rows = []
    # The firmware has no fcntl module. Fixed read-only argv; no shell, ConnMan
    # or arbitrary commands. Never return cellular / wildcard addresses.
    for executable in ('/sbin/ip','/usr/sbin/ip','/bin/ip','/usr/bin/ip'):
        if not os.path.isfile(executable): continue
        try:
            result = subprocess.run([executable,'-o','-4','addr','show'],stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,timeout=2)
            if result.returncode: continue
            for line in result.stdout.decode('ascii','replace').splitlines():
                match = re.match(r'^\d+:\s+(\S+)\s+inet\s+([0-9.]+)/',line)
                if not match: continue
                name,addr = match.groups(); name = name.split('@',1)[0]
                if not re.match(r'^(wlan\d+|wl[a-z0-9]+|eth\d+|en[a-z0-9]+)$',name): continue
                octets = [int(x) for x in addr.split('.')]
                if len(octets)!=4 or any(x>255 for x in octets): continue
                a,b,c,d = octets
                if a==10 or (a==172 and 16<=b<=31) or (a==192 and b==168):
                    rows.append({'name':name,'address':addr})
            break
        except (OSError, ValueError, subprocess.TimeoutExpired): continue
    return rows


class BoundedServer(HTTPServer):
    def __init__(self, address, state, lan=False):
        self.state, self.lan = state, lan
        HTTPServer.__init__(self, address, Handler)
        self.expected_host = self.server_address[0]+':'+str(self.server_address[1])

    def handle_error(self, request, address):
        self.state.event('connection_error')


class State:
    def __init__(self, root, preview=False, audio_launcher=None, flat_web_root=None):
        self.store = FileStore(root)
        self.flat_web_root = flat_web_root
        self.preview = preview
        self.token = os.urandom(32).hex()
        self.native_bootstrap_until = 0
        self.lock = threading.RLock()
        self.transfer_lock = threading.RLock()
        self.audio_control_lock = threading.RLock()
        self.last_audio_command = -1
        self.stop_event = threading.Event()
        self.sampler = Sampler(self.store.root)
        self.latest = self.sampler.sample()
        self.events = []
        self.lan = None
        self.lan_thread = None
        self.lan_deadline = 0
        self.lan_code = ''
        self.attempts = {}
        self.scores = {}
        self.state_dir = os.path.join(self.store.root, '.toolbox-state')
        if os.path.lexists(self.state_dir) and (os.path.islink(self.state_dir) or not os.path.isdir(self.state_dir)):
            raise ValueError('状态目录不可用')
        os.makedirs(self.state_dir, mode=0o700, exist_ok=True)
        self.score_path = os.path.join(self.state_dir, 'scores.txt')
        if os.path.islink(self.score_path): raise ValueError('状态文件不能是链接')
        if os.path.isfile(self.score_path):
            with open(self.score_path) as handle:
                for line in handle.read(1024).splitlines():
                    fields = line.split('=')
                    if len(fields)==2 and fields[0] in ('snake','2048','bricks') and fields[1].isdigit():
                        self.scores[fields[0]] = min(int(fields[1]),100000000)
        from audio import AudioEngine
        self.audio = AudioEngine(self.state_dir, self.event, audio_launcher)
        self.worker = threading.Thread(target=self.sample_loop)
        self.worker.daemon = True
        self.worker.start()

    def event(self, name):
        # No passwords, paths, request bodies, query strings, tokens or identifiers.
        with self.lock:
            self.events.append({'epoch':time.time(),'event':str(name).split(':')[0][:80]})
            self.events = self.events[-500:]

    def arm_native_bootstrap(self, seconds=30):
        # Only the local launcher can arm this; there is no public API to rearm.
        with self.lock: self.native_bootstrap_until=time.monotonic()+min(60,max(1,seconds))

    def native_bootstrap(self):
        with self.lock:
            if time.monotonic()>=self.native_bootstrap_until: raise ValueError('界面初始化已过期')
            self.native_bootstrap_until=0
            return {'token':self.token}

    def sample_loop(self):
        while not self.stop_event.wait(2):
            with self.lock:
                self.latest = self.sampler.sample()
            if self.lan and (time.monotonic() >= self.lan_deadline or
                    self.lan.server_address[0] not in [a['address'] for a in local_addresses(self.preview)]):
                self.stop_lan()

    def start_lan(self, address):
        with self.transfer_lock:
            return self._start_lan(address)

    def _start_lan(self, address):
        allowed = [x['address'] for x in local_addresses(self.preview)]
        if address not in allowed: raise ValueError('请选择当前 Wi-Fi/以太网私网地址')
        self.stop_lan()
        server = BoundedServer((address,0),self,True)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        with self.lock:
            self.lan_code = '%08d' % (int.from_bytes(os.urandom(4),'big')%100000000)
            self.lan_deadline = time.monotonic()+600
            self.attempts = {}
            self.lan, self.lan_thread = server, thread
        thread.start()
        self.event('transfer_started')
        return self.transfer_state()

    def stop_lan(self):
        with self.transfer_lock:
            self._stop_lan()

    def _stop_lan(self):
        with self.lock:
            server, thread = self.lan, self.lan_thread
            self.lan = self.lan_thread = None
            self.lan_code = ''
            self.lan_deadline = 0
        if server:
            server.shutdown()
            server.server_close()
            if thread is not threading.current_thread(): thread.join(2)
            self.event('transfer_stopped')

    def transfer_state(self):
        with self.lock:
            return {'enabled':self.lan is not None, 'url':'http://'+self.lan.expected_host if self.lan else '',
                    'code':self.lan_code, 'seconds':max(0,int(self.lan_deadline-time.monotonic()))}

    def check_lan(self, server, address, code):
        with self.lock:
            if self.lan is not server or time.monotonic() >= self.lan_deadline: return False
            now = time.monotonic()
            self.attempts = {k:v for k,v in self.attempts.items() if now-v[0]<60}
            stamp,count = self.attempts.get(address,(now,0))
            if count>=8 or len(self.attempts)>128: return False
            if not hmac.compare_digest(code.encode('utf-8'),self.lan_code.encode('ascii')):
                self.attempts[address] = (stamp,count+1)
                return False
            return True

    def save_score(self, game, score):
        if game not in ('snake','2048','bricks') or not 0<=score<=100000000: raise ValueError('分数无效')
        with self.lock:
            if score<=self.scores.get(game,-1): return dict(self.scores)
            updated=dict(self.scores)
            updated[game]=max(updated.get(game,0),score)
            temporary = self.score_path+'.tmp-'+os.urandom(4).hex()
            try:
                with open(temporary,'x') as handle:
                    handle.write('\n'.join(k+'='+str(v) for k,v in sorted(updated.items())))
                    handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary,self.score_path)
                self.scores=updated
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            return dict(self.scores)

    def export(self, what):
        if what not in ('samples','logs'): raise ValueError('导出种类无效')
        with self.lock:
            rows = list(self.sampler.history if what=='samples' else self.events)
        payload = ('\n'.join(J.dumps(x,ensure_ascii=False) for x in rows)+'\n').encode('utf-8')
        path = 'Exports/'+what+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(3).hex()+'.log'
        return self.store.write_new(path,io.BytesIO(payload),len(payload))

    def close(self):
        self.stop_event.set()
        self.stop_lan()
        with self.audio_control_lock: self.audio.stop_audio()
        self.worker.join(3)
        self.store.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'P011-Transfer/0.5'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def setup(self):
        self.request.settimeout(12)
        BaseHTTPRequestHandler.setup(self)

    def log_message(self, fmt, *args): pass

    def send_data(self, code, data, content='application/json; charset=utf-8', download=None):
        self.send_response(code)
        self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if download: self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(download,safe=''))
        self.end_headers()
        self.wfile.write(data)

    def reply(self, data, code=200):
        self.send_data(code,J.dumps({'ok':code==200,'data':data} if code==200 else {'ok':False,'error':str(data)}).encode('utf-8'))

    def query(self):
        url = urllib.parse.urlsplit(self.path)
        if len(self.path)>4096 or url.scheme or url.netloc: raise ValueError('请求路径无效')
        values = urllib.parse.parse_qs(url.query,keep_blank_values=True)
        if any(len(v)!=1 for v in values.values()): raise ValueError('重复参数')
        return url.path, {k:v[0] for k,v in values.items()}

    def authorized(self, path):
        headers = self.headers
        if any(len(headers.get_all(k,[]))>1 for k in ('Host','Origin','Content-Length','X-P011-Token','X-P011-Code','X-P011-Native-UI')): return False
        if headers.get('Host','')!=self.server.expected_host or headers.get('Transfer-Encoding'): return False
        origin = headers.get('Origin','')
        allowed = ('','http://'+self.server.expected_host) if self.server.lan else ('','null','file://')
        if origin not in allowed: return False
        if self.server.lan:
            if self.command=='GET' and path in ('/','/transfer.js','/transfer.css','/favicon.svg'): return True
            return self.server.state.check_lan(self.server,self.client_address[0],headers.get('X-P011-Code',''))
        if path=='/api/native/bootstrap':
            # QML is a trusted local client. A browser cross-origin custom-header
            # request requires preflight, which this server rejects. Never allow
            # a simple navigation/form or any LAN request to obtain the token.
            return (self.command=='GET' and self.client_address[0]=='127.0.0.1' and
                    headers.get('X-P011-Native-UI')=='qml-runtime' and
                    time.monotonic()<self.server.state.native_bootstrap_until)
        return hmac.compare_digest(headers.get('X-P011-Token','').encode('utf-8'),self.server.state.token.encode('ascii'))

    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()

    def dispatch(self):
        try:
            path, q = self.query()
            if not self.authorized(path):
                self.reply('访问被拒绝或访问码已过期',403); return
            state = self.server.state
            if self.server.lan and path in ('/','/transfer.js','/transfer.css','/favicon.svg') and self.command=='GET':
                name = 'index.html' if path=='/' else path[1:]
                content = 'text/html; charset=utf-8' if path=='/' else 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                if name=='favicon.svg': content='image/svg+xml'
                web_file = os.path.join(state.flat_web_root,'toolbox-web-'+name) if state.flat_web_root else os.path.join(os.path.dirname(__file__),'..','web',name)
                with open(web_file,'rb') as handle:
                    self.send_data(200,handle.read(),content)
                return
            if self.command=='GET' and path=='/api/files':
                self.reply(state.store.listing(q.get('path',''),int(q.get('offset','0')))); return
            if self.command=='GET' and path=='/api/download':
                handle,st = state.store.open_file(q.get('path',''))
                with handle:
                    if st.st_size>MAX_FILE: raise ValueError('下载上限 64 MiB')
                    self.send_response(200)
                    self.send_header('Content-Type','application/octet-stream')
                    self.send_header('Content-Length',str(st.st_size))
                    self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(os.path.basename(q['path']),safe=''))
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Cache-Control','no-store')
                    self.end_headers()
                    while True:
                        if self.server.lan and (state.lan is not self.server or time.monotonic()>=state.lan_deadline): break
                        block = handle.read(65536)
                        if not block: break
                        self.wfile.write(block)
                return
            if self.command=='POST' and path=='/api/upload':
                if not self.server.lan: raise ValueError('请使用传输页面上传')
                length = int(self.headers.get('Content-Length','0'))
                outer = self
                class LimitedStream:
                    def read(self, n):
                        if state.lan is not outer.server or time.monotonic()>=state.lan_deadline: raise ValueError('传输已关闭')
                        return outer.rfile.read(n)
                result = state.store.write_new(q.get('path',''),LimitedStream(),length)
                state.event('upload_completed'); self.reply(result); return
            # LAN never reaches local controls, telemetry, scores, pairing or playback.
            if self.server.lan:
                self.reply('接口未开放',404); return
            if self.command=='GET':
                if path=='/api/native/bootstrap': result=state.native_bootstrap()
                elif path=='/api/state':
                    with state.lock:
                        result = {'metrics':state.latest,'history':list(state.sampler.history[-120:]),'scores':dict(state.scores)}
                    result.update({'transfer':state.transfer_state(),'addresses':local_addresses(state.preview)})
                elif path=='/api/processes': result = {'processes':state.sampler.processes()}
                elif path=='/api/audio': result = state.audio.audio_snapshot()
                elif path=='/api/open':
                    name=q.get('path',''); handle,st=state.store.open_file(name); handle.close()
                    category=kind(name)
                    if category=='resource': raise ValueError('资源仅保存，尚未提供模拟器')
                    result={'kind':category,'path':name,'bytes':st.st_size,
                            'url':('file:///' if os.name=='nt' else 'file://')+urllib.parse.quote(os.path.join(state.store.root,*components(name)).replace('\\','/'),safe='/:')}
                    if category=='text': result.update(state.store.text(name))
                else: self.reply('接口不存在',404); return
                self.reply(result); return
            length = int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096: raise ValueError('操作参数过长')
            body=self.rfile.read(length)
            if len(body)!=length: raise ValueError('请求中断')
            form=urllib.parse.parse_qs(body.decode('utf-8'),keep_blank_values=True)
            if any(len(v)!=1 for v in form.values()): raise ValueError('重复参数')
            form={k:v[0] for k,v in form.items()}
            if path=='/api/transfer/start': result=state.start_lan(form.get('address',''))
            elif path=='/api/transfer/stop': state.stop_lan(); result={'stopped':True}
            elif path=='/api/scores': result=state.save_score(form.get('game',''),int(form.get('score','-1')))
            elif path=='/api/export': result=state.export(form.get('what',''))
            elif path=='/api/ui/event':
                event=form.get('event','')
                if event not in ('page_Home','page_Files','page_Games','page_Dashboard'):raise ValueError('页面事件无效')
                state.event(event);result={'recorded':True}
            elif path in ('/api/audio/play','/api/audio/stop'):
                command=int(form.get('command','-1'))
                if not 0<=command<=9007199254740991: raise ValueError('音频请求标识无效')
                with state.audio_control_lock:
                    if command<=state.last_audio_command: raise ValueError('过期音频操作已忽略')
                    state.last_audio_command=command
                    if path.endswith('/play'):
                        name=form.get('path','')
                        if kind(name)!='audio': raise ValueError('请选择音频')
                        handle,st=state.store.open_file(name); handle.close()
                        result=state.audio.play(os.path.join(state.store.root,*components(name)),int(form.get('volume','25')))
                    else:
                        state.audio.stop_audio(); result={'stopped':True}
            else: self.reply('操作不在白名单',404); return
            self.reply(result)
        except (ValueError, OSError, RuntimeError) as exc:
            try: self.reply('操作失败：'+str(exc)[:180],409 if isinstance(exc,FileExistsError) else 400)
            except OSError: pass
        except Exception:
            self.server.state.event('request_error')
            try: self.reply('服务暂时不可用',500)
            except OSError: pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='/mnt/data/p011-user')
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    state=State(args.root,args.preview)
    server=BoundedServer(('127.0.0.1',0),state)
    quit_event=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:quit_event.set())
    thread=threading.Thread(target=server.serve_forever); thread.daemon=True; thread.start()
    print('Backend ready on loopback. Use host preview launcher for authenticated UI.',flush=True)
    try: quit_event.wait()
    finally: server.shutdown(); server.server_close(); state.close()


if __name__=='__main__': main()
