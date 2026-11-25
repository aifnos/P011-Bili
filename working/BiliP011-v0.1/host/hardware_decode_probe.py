"""Bounded, no-display/no-audio stock OMX test; credentials stay on P011."""
import argparse,datetime,hashlib,json,pathlib,re,secrets
from awake_trial import Adb,check_bundle,result_from,ROOT,BASE,archive


def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=pathlib.Path,required=True);p.add_argument('--quality',type=int,choices=(80,116),default=116);p.add_argument('--software',action='store_true');p.add_argument('--threads',type=int,choices=(4,6,8),default=4);p.add_argument('--bvid',default='BV1Da411Y7U4');p.add_argument('--start',type=int,choices=(0,10,20),default=0);p.add_argument('--codec',type=int,choices=(7,12),default=7);a=p.parse_args()
    if not re.fullmatch('BV[0-9A-Za-z]{10}',a.bvid):raise ValueError('Invalid public benchmark ID')
    meta,_=check_bundle(a.bundle);out=ROOT/'logs'/('BiliP011-HardwareDecode-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();adb=Adb(out)
    source=BASE/'probes'/('mpv_decode_probe.py' if a.software else 'gst_decode_probe.py')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    directory='/mnt/data/p011-toolbox/bili-decode-probe-'+secrets.token_hex(12)
    path=directory+'/probe.py'
    # Legacy ADB has a 4096-byte shell limit. Stage only our own source in a
    # fresh private directory, never edit the frozen trial or a system path.
    prepare='import os,sys\nsys.path.insert(0,'+repr(meta['remote'])+')\nimport awake_trial as t\nfrom native_safety import stock_snapshot,require_stock\nt.verify();require_stock(stock_snapshot())\nos.mkdir('+repr(directory)+',0o700)\nprint("RESULT="+repr({"created":True}))'
    result_from(adb.python('prepare-probe-source',prepare))
    adb.run('push-probe-source',['push',str(source),path])
    code='ROOT='+repr(meta['remote'])+'\nQUALITY='+repr(a.quality)+'\nCODEC='+repr(a.codec)+'\nSOFTWARE='+repr(a.software)+'\nTHREADS='+repr(a.threads)+'\nSEEK='+repr(a.start)+'\nBV='+repr(a.bvid)+'\nPROBE_PATH='+repr(path)+'\nPROBE_HASH='+repr(digest)+'\n'+r'''
import ast,hashlib,os,stat,sys,subprocess
sys.path.insert(0,ROOT)
import service,config,awake_trial as trial
from native_safety import stock_snapshot,require_stock
trial.verify();before=stock_snapshot();require_stock(before)
info=os.lstat(PROBE_PATH)
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('unsafe owned probe')
os.chmod(PROBE_PATH,0o600)
with open(PROBE_PATH,'rb') as f:probe_bytes=f.read(32769)
if hashlib.sha256(probe_bytes).hexdigest()!=PROBE_HASH:raise ValueError('probe identity mismatch')
PROBE=probe_bytes.decode('utf-8')
b=service.Backend(ROOT,config.MEDIA+'/bin/bili-api','','/mnt/data/p011-toolbox/bili-account',dict(os.environ,LD_LIBRARY_PATH=config.MEDIA+'/lib'),lifetime=45)
report={'window_opened':False,'audio_played':False,'account_content_exported':False,'quality':QUALITY,'codec':CODEC,'software_probe':SOFTWARE}
try:
 d=b.helper('detail',{'kind':'video','bvid':BV})
 row=dict(d['parts'][0],quality=QUALITY,codec=CODEC)
 stream=b.helper('play',service.safe_args('play',row))
 report['width']=stream.get('width');report['height']=stream.get('height')
 # No custom media LD_LIBRARY_PATH in this process: it uses stock GStreamer.
 env=dict(os.environ,GST_DEBUG='0');env.pop('LD_LIBRARY_PATH',None)
 if SOFTWARE:env['LD_LIBRARY_PATH']=config.MEDIA+'/lib'
 parent=os.getpid()
 readfd,writefd=os.pipe()
 child=subprocess.Popen([sys.executable,'-c',PROBE,str(writefd),str(THREADS),config.MEDIA,str(SEEK),str(CODEC)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,pass_fds=(writefd,),preexec_fn=lambda:trial.child_limits(parent))
 os.close(writefd)
 try:o,e=child.communicate(stream['video'].encode('utf-8')+b'\n',timeout=21)
 except subprocess.TimeoutExpired:child.kill();o,e=child.communicate();report['timeout']=True
 report['child_exit']=child.returncode
 safe=os.read(readfd,4096);os.close(readfd)
 for line in safe.splitlines():
  raw=ast.literal_eval(line.decode('ascii'))
  report['decode']={k:raw[k] for k in ('frames','hw_library_loaded','vsp_open','bus_error','parse_error','elapsed_ms','cpu_ms','state_result','cleanup_finished','warm_frames','warm_elapsed_ms','frames_requested','threads','loaded','ended','after_loaded_ms','time_pos','container_fps','start_seconds','source_fps') if k in raw and type(raw[k]) in (bool,int,float)}
 # Raw vendor output intentionally stays private and is not exported.
 report['suppressed_stdout_bytes']=len(o);report['suppressed_stderr_bytes']=len(e)
except Exception as ex:report['error_type']=type(ex).__name__
finally:b.close()
after=stock_snapshot();require_stock(after);report['stock_unchanged']=before==after
os.unlink(PROBE_PATH);os.rmdir(os.path.dirname(PROBE_PATH));report['probe_source_removed']=True
print('RESULT='+ascii(report))
'''
    result=result_from(adb.python('bounded-stock-decoder',code,timeout=65))
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2));print('LOG_DIR='+str(out));archive(out)
    return 0 if result.get('stock_unchanged') else 1


if __name__=='__main__':raise SystemExit(main())
