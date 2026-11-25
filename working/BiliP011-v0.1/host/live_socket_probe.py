"""Read-only scoped GET/TLS/WebSocket diagnostic; no message sending or media."""
import argparse,datetime,hashlib,json,pathlib
from awake_trial import ROOT,Adb,result_from,check_bundle
def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);a=p.parse_args();meta,_=check_bundle(a.bundle)
    out=ROOT/'logs'/('BiliP011-LiveSocket-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();print('LOG_DIR='+str(out),flush=True)
    code='ROOT='+repr(meta['remote'])+'\nMEDIA='+repr(meta['media_remote'])+'\nEXPECTED='+repr(hashlib.sha256((a.bundle/'live_danmaku.py').read_bytes()).hexdigest())+'\n'+r'''
import sys,os,hashlib,subprocess,signal
signal.alarm(55)
sys.path[:0]=[ROOT+'/stdlib-json35.zip',ROOT]
import json
assert hashlib.sha256(open(ROOT+'/live_danmaku.py','rb').read()).hexdigest()==EXPECTED
report={'phase':0,'account_writes':False,'player_started':False}
env=dict(os.environ,LD_LIBRARY_PATH=MEDIA+'/lib',P011_BILI_COOKIES='/mnt/data/p011-toolbox/bili-account/cookies.txt',P011_ACCOUNT_WRITES='disabled')
for k in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD'):env.pop(k,None)
def api(op,args):
 p=subprocess.Popen([MEDIA+'/bin/bili-api'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
 try:raw,_=p.communicate(json.dumps(dict(op=op,args=args)).encode(),timeout=24)
 except subprocess.TimeoutExpired:p.kill();p.communicate();raise ValueError('timeout')
 d=json.loads(raw.decode());report['api_ok']=d.get('ok') is True
 report['api_code']=d.get('code',0);report['api_error']=d.get('error','') if d.get('error','') in ('API_ERROR','API_SCHEMA','LOGIN_REQUIRED','FEATURE_UNAVAILABLE','NETWORK_ERROR','INTERNAL') else ''
 if not d.get('ok'):raise ValueError('api')
 return d['data']
sock=None
try:
 report['phase']=1
 import live_danmaku
 room=api('live_catalog',{})['items'][0]['room']
 report['phase']=2;info=api('live_danmaku_info',{'room':room})
 report['servers']=len(info['servers']);report['token_present']=bool(info['token']);report['uid_present']=info.get('uid')!='0'
 report['phase']=3;report['ca_exists']=os.path.isfile('/etc/ssl/certs/ca-certificates.crt')
 sock,rest=live_danmaku.connect(info['servers'][0],'/etc/ssl/certs/ca-certificates.crt');report['phase']=4
except Exception as e:
 report['error_type']=type(e).__name__;report['os_error']=getattr(e,'errno',None)
 message=str(e);report['error']=message if message in ('api','timeout','handshake status','handshake proof','server boundary','handshake limit') else ''
finally:
 if sock:sock.close()
print('RESULT='+repr(report))
'''
    value=result_from(Adb(out).python('live-read-only',code,timeout=60));(out/'result.json').write_text(json.dumps(value,indent=2),encoding='utf-8');print(json.dumps(value))
if __name__=='__main__':main()
