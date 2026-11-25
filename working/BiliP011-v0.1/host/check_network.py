"""Read-only network comparison after API timeouts; no power/radio changes."""
import datetime,json
from awake_trial import ROOT,NATIVE,Adb,archive,result_from

out=ROOT/'logs'/('BiliP011-Network-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
out.mkdir();print('LOG_DIR='+str(out),flush=True);adb=Adb(out)
safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
before=result_from(adb.python('before',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
code=r'''
import os,subprocess
state={}
for path in ['/proc/net/route','/etc/resolv.conf','/sys/class/net/wlan0/operstate','/sys/class/net/wlan0/carrier','/sys/class/backlight/sprd_backlight/actual_brightness']:
 try:
  with open(path) as f:state[path]=f.read(8192)
 except OSError:state[path]='unavailable'
checks={}
for name,binary,url,private in [
 ('stock-api','/usr/bin/curl','https://api.bilibili.com/x/web-interface/nav',False),
 ('private-api','/mnt/data/p011-toolbox/bili-media/8affe27ba705ba01/bin/curl','https://api.bilibili.com/x/web-interface/nav',True),
 ('private-web','/mnt/data/p011-toolbox/bili-media/8affe27ba705ba01/bin/curl','https://www.bilibili.com/',True)]:
 env=dict(os.environ)
 for k in ['http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD']:env.pop(k,None)
 if private:env['LD_LIBRARY_PATH']='/mnt/data/p011-toolbox/bili-media/8affe27ba705ba01/lib'
 p=subprocess.Popen([binary,'--silent','--show-error','--connect-timeout','3','--max-time','6','--output','/dev/null','--write-out','HTTP=%{http_code} DNS=%{time_namelookup} TCP=%{time_connect} TLS=%{time_appconnect}\n','-A','wiliwili',url],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:o,e=p.communicate(timeout=9)
 except subprocess.TimeoutExpired:p.kill();o,e=p.communicate()
 checks[name]={'exit':p.returncode,'stdout':o,'stderr':e}
print('RESULT='+repr({'state':state,'checks':checks}))
'''
report=result_from(adb.python('network-read-only',code,timeout=35))
for name,row in report['checks'].items():
 for stream in ('stdout','stderr'):
  raw=row.pop(stream);(out/(name+'.'+stream+'.raw')).write_bytes(raw);row[stream]=raw.decode('utf-8','replace')
after=result_from(adb.python('after',safety+"\ns=stock_snapshot();require_stock(s);print('RESULT='+repr(s))"))
report.update(stock_hashes_unchanged=before['hashes']==after['hashes'],stock_processes_unchanged=before['processes']==after['processes'])
(out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));archive(out)
