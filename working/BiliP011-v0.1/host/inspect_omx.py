"""Read-only factory decoder inventory. No pipeline or vendor binary export."""
import datetime,json
from awake_trial import Adb,BASE,ROOT,NATIVE,result_from,archive

def main():
    out=ROOT/'logs'/('BiliP011-OmxProperties-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    gate=safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before=result_from(adb.python('before',gate))
    result=result_from(adb.python('decoder-properties',r'''
import os,subprocess,hashlib
env=dict(os.environ,GST_REGISTRY_UPDATE='no',GST_DEBUG='0');env.pop('LD_LIBRARY_PATH',None);env.pop('LD_PRELOAD',None)
p=subprocess.Popen(['/usr/bin/gst-inspect-1.0','omxh264dec'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:o,e=p.communicate(timeout=8)
except subprocess.TimeoutExpired:p.kill();o,e=p.communicate()
path='/usr/lib/gstreamer-1.0/libgstomx.so'
print('RESULT='+repr({'exit':p.returncode,'stdout':o,'stderr_bytes':len(e),'plugin_sha256':hashlib.sha256(open(path,'rb').read()).hexdigest()}))
''',timeout=15))
    (out/'omxh264dec.txt').write_bytes(result.pop('stdout'))
    after=result_from(adb.python('after',gate));result.update(stock_unchanged=before==after,window_opened=False,pipeline_started=False)
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));print('LOG_DIR='+str(out));archive(out)
    return 0 if result['exit']==0 and result['stock_unchanged'] else 1
if __name__=='__main__':raise SystemExit(main())
