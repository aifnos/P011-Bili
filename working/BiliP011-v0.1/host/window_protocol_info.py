"""Read-only compositor version and specific upstream size-error fingerprint."""
import datetime,json
from awake_trial import Adb,ROOT,result_from

PROBE=r'''
import glob,os,subprocess,hashlib
version=subprocess.check_output(['/usr/bin/weston','--version'],timeout=5).decode('ascii','replace').strip()
rows=[];seen=set()
for path in glob.glob('/usr/lib/libweston-desktop*.so*'):
 real=os.path.realpath(path)
 if real in seen or not os.path.isfile(real) or os.path.getsize(real)>8388608:continue
 seen.add(real)
 with open(real,'rb') as f:raw=f.read(8388609)
 rows.append({'file':os.path.basename(real),'sha256':hashlib.sha256(raw).hexdigest(),'has_xdg_fullscreen_size_rejection':b'xdg_surface buffer does not match the configured state' in raw})
print('RESULT='+repr({'read_only':True,'weston_version':version,'libraries':rows}))
'''
def main():
 out=ROOT/'logs'/('BiliP011-WindowProtocol-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
 result=result_from(Adb(out).python('protocol-version-readonly',PROBE))
 (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print('LOG_DIR='+str(out));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
