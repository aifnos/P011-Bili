"""Bounded read-only IP/DNS probes; does not modify the pen's network settings."""
import datetime,json
from awake_trial import ROOT,NATIVE,Adb,archive,result_from
out=ROOT/'logs'/('BiliP011-Reachability-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
before=result_from(adb.python('before',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
code=r'''
import os,socket,struct,threading,time
result={};lock=threading.Lock()
def check(kind,address,port):
 start=time.monotonic();answer={}
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM if kind=='dns' else socket.SOCK_STREAM);s.settimeout(3)
 try:
  if kind=='dns':
   query=struct.pack('!HHHHHH',0x5011,0x0100,1,0,0,0)+b'\x03api\x08bilibili\x03com\x00'+struct.pack('!HH',1,1)
   s.sendto(query,(address,port));raw,source=s.recvfrom(4096)
   if source!=(address,port) or len(raw)<12 or struct.unpack('!H',raw[:2])[0]!=0x5011:raise ValueError('unexpected DNS reply')
   _,flags,questions,answers,_,_=struct.unpack('!HHHHHH',raw[:12])
   answer={'ok':(flags&15)==0 and answers>0,'rcode':flags&15,'answers':answers}
  else:s.connect((address,port));answer={'ok':True}
 except Exception as exc:answer={'ok':False,'error_type':type(exc).__name__}
 finally:s.close()
 answer['milliseconds']=int((time.monotonic()-start)*1000)
 with lock:result[kind+'-'+address+':'+str(port)]=answer
threads=[]
for item in [('dns','192.168.1.1',53),('dns','223.5.5.5',53),('dns','1.1.1.1',53),('tcp','192.168.1.1',80),('tcp','223.5.5.5',443),('tcp','1.1.1.1',443)]:
 t=threading.Thread(target=check,args=item);t.start();threads.append(t)
for t in threads:t.join(4)
with open('/proc/net/arp') as f:arp=f.read(4096)
try:
 with open('/proc/net/wireless') as f:wireless=f.read(4096)
except FileNotFoundError:wireless='not exposed by this firmware'
print('RESULT='+repr({'checks':result,'arp':arp,'wireless':wireless}))
'''
report=result_from(adb.python('ip-and-dns',code,timeout=30))
after=result_from(adb.python('after',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
report.update(stock_hashes_unchanged=before['hashes']==after['hashes'],stock_processes_unchanged=before['processes']==after['processes'])
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));archive(out)
