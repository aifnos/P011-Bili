"""Read-only collection of four AVC/ION libraries for LOCAL offline analysis.

No loading, executing, patching or redistribution of vendor libraries. This
private out/ directory is deliberately excluded from source review packages.
"""
import datetime,hashlib,json,pathlib,stat
from awake_trial import Adb,BASE,NATIVE,ROOT,result_from

LIBRARIES=('libsprd_omx_core.so','libstagefright_sprd_h264dec.so',
           'libomx_avcdec_hw_sprd.so','libmemion.so')
MAX_BYTES=16*1024*1024

PROBE=r'''
import hashlib,stat
before=stock_snapshot();require_stock(before)
records={}
for name in NAMES:
 path='/usr/lib/'+name;real=os.path.realpath(path);info=os.lstat(real)
 if not real.startswith('/usr/lib/') or not stat.S_ISREG(info.st_mode) or info.st_size>16777216:raise ValueError('Unexpected vendor library')
 with open(real,'rb') as stream:body=stream.read(16777217)
 if len(body)!=info.st_size or body[:5]!=b'\x7fELF\x01':raise ValueError('Unexpected vendor ELF')
 records[name]={'sha256':hashlib.sha256(body).hexdigest(),'size':len(body),'real_path':real}
after=stock_snapshot();require_stock(after)
print('RESULT='+repr(dict(libraries=records,stock_unchanged=before==after)))
'''

def verify_copy(path,record):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES:raise ValueError('Not a bounded regular copy')
    body=path.read_bytes()
    if len(body)!=record['size'] or hashlib.sha256(body).hexdigest()!=record['sha256']:
        raise ValueError('Vendor copy identity differs')
    if body[:5]!=b'\x7fELF\x01' or int.from_bytes(body[18:20],'little')!=40:
        raise ValueError('Not ARM ELF32')

def main():
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out=BASE/'out'/('vendor-avc-inspect-'+stamp);out.mkdir()
    log=ROOT/'logs'/('BiliP011-VendorAVC-ReadOnly-'+stamp);log.mkdir()
    adb=Adb(log)
    code=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    code+='\nNAMES='+repr(LIBRARIES)+'\n'+PROBE
    before=result_from(adb.python('before-library-hashes',code))
    if before['stock_unchanged'] is not True:raise ValueError('Stock changed during inspection')
    for name in LIBRARIES:
        adb.run('pull-'+name,['pull','/usr/lib/'+name,str(out/name)],timeout=30)
        verify_copy(out/name,before['libraries'][name])
    after=result_from(adb.python('after-library-hashes',code))
    if before!=after:raise ValueError('Vendor or stock changed during collection')
    result=dict(before,local_copies_verified=True,device_files_written=False,
                vendor_libraries_executed=False,redistributable=False,private_directory=str(out))
    (log/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('PRIVATE_VENDOR_DIRECTORY='+str(out));print('LOG_DIR='+str(log))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
