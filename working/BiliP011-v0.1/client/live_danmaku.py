"""Read-only official live WebSocket, protocol 2/zlib. Python 3.5, no chat posting.

Token/room/user identifiers stay in private memory. Bounded frames, decompression,
TLS certificate/host checks, heartbeat, finite retry; history polling is not used.
"""
import base64,hashlib,json,os,re,socket,ssl,struct,time,zlib

LIMIT=1024*1024
def packet(op,body=b''):
    if len(body)>LIMIT-16:raise ValueError('packet limit')
    return struct.pack('>IHHII',16+len(body),16,1,op,1)+body

def unpack(data,depth=0):
    if len(data)>LIMIT or depth>2:raise ValueError('packet limit')
    out=[];at=0
    while at<len(data):
        if len(data)-at<16:raise ValueError('packet header')
        size,header,version,op,seq=struct.unpack('>IHHII',data[at:at+16])
        if not 16<=header<=size<=len(data)-at:raise ValueError('packet size')
        body=data[at+header:at+size];at+=size
        if version==2:
            z=zlib.decompressobj();decoded=z.decompress(body,LIMIT+1)
            if len(decoded)>LIMIT or z.unconsumed_tail or not z.eof:raise ValueError('zlib limit')
            out+=unpack(decoded,depth+1)
        elif version in (0,1):
            if op in (5,8):out.append((op,json.loads(body.decode('utf-8'))))
            elif op==3:out.append((3,None))
        else:raise ValueError('unsupported compression')
        if len(out)>200:raise ValueError('message limit')
    return out

def masked(op,payload):
    if len(payload)>LIMIT:raise ValueError('frame limit')
    key=os.urandom(4);size=len(payload);head=bytes([0x80|op])
    head+=bytes([0x80|size]) if size<126 else bytes([0x80|126])+struct.pack('>H',size) if size<65536 else bytes([0x80|127])+struct.pack('>Q',size)
    return head+key+bytes(c^key[i%4] for i,c in enumerate(payload))

class Frames:
    def __init__(self):self.buffer=b'';self.fragments=b'';self.fragment_op=0
    def feed(self,data):
        self.buffer+=data;result=[]
        if len(self.buffer)>LIMIT+65536:raise ValueError('buffer limit')
        while len(self.buffer)>=2:
            first,second=self.buffer[0],self.buffer[1];op=first&15;size=second&127;start=2
            if first&0x70 or second&0x80:raise ValueError('server frame flags')
            if size==126:
                if len(self.buffer)<4:break
                size=struct.unpack('>H',self.buffer[2:4])[0];start=4
            elif size==127:
                if len(self.buffer)<10:break
                size=struct.unpack('>Q',self.buffer[2:10])[0];start=10
            if size>LIMIT:raise ValueError('frame limit')
            if op>=8 and (size>125 or not first&128):raise ValueError('control frame')
            if len(self.buffer)<start+size:break
            payload=self.buffer[start:start+size];self.buffer=self.buffer[start+size:]
            if op>=8:result.append((op,payload));continue
            if op==0:
                if not self.fragment_op:raise ValueError('unexpected continuation')
                self.fragments+=payload
            elif op in (1,2):
                if self.fragment_op:raise ValueError('interleaved message')
                self.fragments=payload;self.fragment_op=op
            else:raise ValueError('opcode')
            if len(self.fragments)>LIMIT:raise ValueError('fragment limit')
            if first&128:result.append((self.fragment_op,self.fragments));self.fragment_op=0;self.fragments=b''
        return result

def chat(value):
    if not isinstance(value,dict) or not str(value.get('cmd','')).startswith('DANMU_MSG'):return None
    info=value.get('info',[])
    if not isinstance(info,list) or len(info)<2 or not isinstance(info[0],list) or len(info[0])<4 or not isinstance(info[1],str):return None
    text=''.join(c for c in info[1] if ord(c)>=32)[:120];color=info[0][3]
    if not text:return None
    return dict(text=text,color=color if type(color) is int and 0<=color<=0xffffff else 0xffffff)

def connect(server,ca):
    host=server.get('host','');port=server.get('port')
    if not re.match(r'^[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.chat\.bilibili\.com$',host) or type(port) is not int or port not in (443,2245):raise ValueError('server boundary')
    raw=socket.create_connection((host,port),timeout=5)
    try:sock=ssl.create_default_context(cafile=ca).wrap_socket(raw,server_hostname=host)
    except Exception:raw.close();raise
    try:
        key=base64.b64encode(os.urandom(16)).decode('ascii')
        headers='GET /sub HTTP/1.1\r\nHost: '+host+(':'+str(port) if port!=443 else '')+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+'\r\nSec-WebSocket-Version: 13\r\nOrigin: https://live.bilibili.com\r\n\r\n'
        sock.sendall(headers.encode('ascii'));reply=b''
        while b'\r\n\r\n' not in reply:
            part=sock.recv(2048)
            if not part or len(reply)+len(part)>16384:raise ValueError('handshake limit')
            reply+=part
        head,rest=reply.split(b'\r\n\r\n',1);lines=head.decode('ascii').split('\r\n')
        if lines[0].split(' ')[1]!='101':raise ValueError('handshake status')
        fields={k.strip().lower():v.strip() for k,v in (line.split(':',1) for line in lines[1:] if ':' in line)}
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
        if fields.get('sec-websocket-accept')!=expected or fields.get('upgrade','').lower()!='websocket' or 'upgrade' not in fields.get('connection','').lower():raise ValueError('handshake proof')
        sock.settimeout(1);return sock,rest
    except Exception:sock.close();raise

def run(info_provider,deliver,stopping,alive,ca,stats,tick=lambda:None):
    stats.update(connected=False,authenticated=False,ever_authenticated=False,messages=0,heartbeats=0,reconnects=0,failed=False)
    for attempt in range(3):
        if stopping.is_set() or not alive():return
        sock=None
        try:
            stats['last_phase']=1;info=info_provider();servers=info.get('servers',[])
            if not servers:raise ValueError('no servers')
            stats['last_phase']=2;sock,rest=connect(servers[attempt%len(servers)],ca);stats['connected']=True
            auth={'uid':int(info.get('uid','0')),'roomid':int(info['room']),'protover':2,'platform':'web','type':2,'key':info['token']}
            sock.sendall(masked(2,packet(7,json.dumps(auth,separators=(',',':')).encode('utf-8'))));auth.clear();info.clear()
            stats['last_phase']=3;reader=Frames();auth_deadline=time.monotonic()+12;next_heartbeat=0;data=rest
            while not stopping.is_set() and alive():
                tick()
                now=time.monotonic()
                if not stats['authenticated'] and now>auth_deadline:raise ValueError('authentication timeout')
                if stats['authenticated'] and now>=next_heartbeat:sock.sendall(masked(2,packet(2)));next_heartbeat=now+25
                if not data:
                    try:data=sock.recv(65536)
                    except socket.timeout:continue
                    if not data:raise ValueError('closed')
                for op,payload in reader.feed(data):
                    if op==8:raise ValueError('closed')
                    if op==9:sock.sendall(masked(10,payload));continue
                    if op!=2:continue
                    for kind,value in unpack(payload):
                        if kind==8:
                            if not isinstance(value,dict) or value.get('code')!=0:raise ValueError('authentication refused')
                            stats['authenticated']=True;stats['ever_authenticated']=True;stats['failed']=False;stats['last_phase']=4
                        elif kind==3:stats['heartbeats']+=1
                        elif kind==5 and stats['authenticated']:
                            row=chat(value)
                            if row:stats['messages']+=1;deliver(row)
                data=b''
            return
        except (OSError,ValueError,KeyError,TypeError):stats['failed']=True
        finally:
            if sock:sock.close()
            stats['connected']=False;stats['authenticated']=False
        if attempt<2:stats['reconnects']+=1;stopping.wait(2+attempt*2)
