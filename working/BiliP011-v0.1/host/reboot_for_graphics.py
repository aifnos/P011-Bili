"""One explicitly user-authorized normal reboot; no reset/flash/looped reboot."""
import argparse,datetime,json,time
from awake_trial import Adb,result_from,ROOT,NATIVE,archive

def main():
    p=argparse.ArgumentParser();p.add_argument('--authorized',action='store_true');a=p.parse_args()
    if not a.authorized:raise SystemExit('Explicit authorization for this reboot is required')
    out=ROOT/'logs'/('BiliP011-AuthorizedReboot-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();adb=Adb(out)
    code=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')+r'''
s=stock_snapshot();require_stock(s)
for pid in os.listdir('/proc'):
 if not pid.isdigit():continue
 try:entry=identity(pid)
 except (OSError,ValueError):continue
 if entry.get('exe','').startswith('/mnt/data/p011-toolbox/bili-'):raise RuntimeError('Candidate still active; refuse reboot')
def numeric(path):
 try:return int(open(path).read())
 except (OSError,ValueError):return None
print('RESULT='+repr({'stock':s,'boot':open('/proc/sys/kernel/random/boot_id').read().strip(),'ion_heaps_kb':numeric('/sys/kernel/ion/total_heaps_kb'),'ion_pools_kb':numeric('/sys/kernel/ion/total_pools_kb')}))
'''
    before=result_from(adb.python('before-reboot',code));report={'authorized':True,'reboot_commands':0,'before':before}
    try:
        # A transport disconnect can occur after the reboot is accepted. Never
        # resend this command; reconcile with boot identity instead.
        report['reboot_commands']=1
        try:adb.run('single-normal-reboot',['reboot'],timeout=15)
        except Exception as ex:report['command_observation']=type(ex).__name__
        until=time.monotonic()+120;after=None;attempt=0
        while time.monotonic()<until:
            time.sleep(3);attempt+=1
            try:
                candidate=result_from(adb.python('readiness-'+str(attempt),code,timeout=8))
                if candidate['boot']!=before['boot']:after=candidate;break
            except Exception:pass
        report['after']=after;report['boot_changed']=after is not None
        report['passed']=after is not None and before['stock']['hashes']==after['stock']['hashes']
    finally:
        (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');archive(out)
    print(json.dumps({k:report[k] for k in ('authorized','reboot_commands','boot_changed','passed')},indent=2));print('LOG_DIR='+str(out))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
