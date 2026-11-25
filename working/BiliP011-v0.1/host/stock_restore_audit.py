"""Fresh read-only stock identity and private-process check; never starts/stops."""
import datetime,json,pathlib
from awake_trial import Adb,NATIVE,ROOT,result_from

PROBE=r'''
s=stock_snapshot();require_stock(s)
active=0;webengine=0
for pid in os.listdir('/proc'):
 if not pid.isdigit() or int(pid)==os.getpid():continue
 try:
  exe=os.readlink('/proc/'+pid+'/exe')
  if exe.endswith('/QtWebEngineProcess'):webengine+=1
  args=open('/proc/'+pid+'/cmdline','rb').read(4096)
  if exe.startswith('/mnt/data/p011-toolbox/') or b'/mnt/data/p011-toolbox/bili-awake/' in args or b'/mnt/data/p011-toolbox/bili-media/' in args:active+=1
 except OSError:pass
print('RESULT='+repr(dict(stock=s,active_private_processes=active,webengine_processes=webengine,passed=active==0)))
'''

def main():
    out=ROOT/'logs'/('BiliP011-StockRestoreAudit-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    # Adb.python compresses the read-only script and enforces the old server's
    # command-length limit; never pass a long multiline adb -c directly.
    result=result_from(Adb(out).python('stock-and-private',(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+'\n'+PROBE))
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if result['passed'] is not True:raise ValueError('Private work remains active')

if __name__=='__main__':main()
