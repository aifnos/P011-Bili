"""Read-only core registry inventory, with raw vendor output suppressed."""
import datetime,json
from probe_device import ROOT,BASE,NATIVE,Adb,result_from,archive


def main():
    out=ROOT/'logs'/('BiliP011-OmxInventory-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    adb=Adb(out);safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    gate=safety+'\ns=stock_snapshot();require_stock(s);print("RESULT="+repr(s))'
    before=result_from(adb.python('before',gate))
    probe=(BASE/'probes/omx_inventory.py').read_text(encoding='utf-8')
    code='PROBE='+repr(probe)+'\n'+r'''
import ast,subprocess,sys
p=subprocess.Popen([sys.executable,'-B','-c',PROBE],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:o,e=p.communicate(timeout=8)
except subprocess.TimeoutExpired:p.kill();o,e=p.communicate()
r={'exit':p.returncode,'suppressed_stdout_bytes':len(o),'suppressed_stderr_bytes':len(e)}
for line in o.splitlines():
 if line.startswith(b'P011_OMX_RESULT='):r['core']=ast.literal_eval(line.split(b'=',1)[1].decode('ascii'))
print('RESULT='+ascii(r))
'''
    report=result_from(adb.python('core-components',code,timeout=12))
    after=result_from(adb.python('after',gate));report.update(stock_unchanged=before==after,streams_opened=False,window_opened=False)
    (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));print('LOG_DIR='+str(out));archive(out)


if __name__=='__main__':main()
