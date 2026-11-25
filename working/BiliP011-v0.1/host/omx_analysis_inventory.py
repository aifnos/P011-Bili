"""Read-only profiler capability inventory and private stock plugin copy."""
import datetime,hashlib,json
from awake_trial import Adb,BASE,ROOT,NATIVE,result_from

def main():
    out=ROOT/'logs'/('BiliP011-OmxAnalysis-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    gate=safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before=result_from(adb.python('before',gate))
    inventory=result_from(adb.python('read-only-inventory',r'''
import os,hashlib
path='/usr/lib/gstreamer-1.0/libgstomx.so'
tools={name:any(os.path.isfile(folder+'/'+name) and os.access(folder+'/'+name,os.X_OK) for folder in ('/usr/bin','/bin','/usr/sbin','/sbin')) for name in ('perf','gdb','strace','readelf')}
paranoid='/proc/sys/kernel/perf_event_paranoid'
print('RESULT='+repr({'tools':tools,'perf_paranoid':int(open(paranoid).read()) if os.path.isfile(paranoid) else None,'plugin_sha256':hashlib.sha256(open(path,'rb').read()).hexdigest(),'plugin_bytes':os.path.getsize(path)}))
'''))
    dest=BASE/'private-omx-analysis'/inventory['plugin_sha256'];dest.mkdir(parents=True,exist_ok=False)
    target=dest/'libgstomx.so';adb.run('read-plugin',['pull','/usr/lib/gstreamer-1.0/libgstomx.so',str(target)])
    if hashlib.sha256(target.read_bytes()).hexdigest()!=inventory['plugin_sha256']:raise ValueError('Plugin copy mismatch')
    after=result_from(adb.python('after',gate));inventory.update(stock_unchanged=before==after,device_writes=False,vendor_copy_private=True)
    (out/'result.json').write_text(json.dumps(inventory,indent=2));(dest/'identity.json').write_text(json.dumps(inventory,indent=2))
    print(json.dumps(inventory,indent=2));print('LOG_DIR='+str(out));print('PRIVATE_PLUGIN='+str(target))
    return 0 if inventory['stock_unchanged'] else 1
if __name__=='__main__':raise SystemExit(main())
