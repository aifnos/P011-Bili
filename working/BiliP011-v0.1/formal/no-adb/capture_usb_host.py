"""Capture the new host-only USB observer with independent raw streams/exits."""
import datetime,hashlib,json,pathlib,subprocess,sys,zipfile
base=pathlib.Path(__file__).resolve().parent
out=base.parent/'evidence'/('usb-no-adb-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
args=['pwsh','-NoLogo','-NoProfile','-File',str(base/'Capture-P011Usb.ps1'),'60','-OutputDirectory',str(out)]
print('LOG_DIR='+str(out),flush=True)
proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:
 stdout,stderr=proc.communicate(timeout=75)
 status={'host_exit':proc.returncode,'timeout':False,'remote_exit':None,'remote_exit_applicable':False}
except subprocess.TimeoutExpired as exc:
 proc.kill();stdout,stderr=proc.communicate()
 status={'host_exit':proc.returncode,'timeout':True,'remote_exit':None,'remote_exit_applicable':False}
out.mkdir(parents=True,exist_ok=True)
(out/'host.stdout.raw').write_bytes(stdout)
(out/'host.stderr.raw').write_bytes(stderr)
(out/'host.status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
(out/'source.sha256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [base/'Capture-P011Usb.ps1',pathlib.Path(__file__)]},indent=2),encoding='utf-8')
archive=out.with_suffix('.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
 for path in sorted(out.iterdir()):
  if path.is_file():bundle.write(path,path.name)
with zipfile.ZipFile(archive) as bundle:
 assert bundle.testzip() is None
print(stdout.decode('utf-8','replace'),flush=True)
print(stderr.decode('utf-8','replace'),file=sys.stderr,flush=True)
print('RESULT_ZIP='+str(archive),flush=True)
sys.exit(0 if status['host_exit']==0 and not status['timeout'] else 1)
