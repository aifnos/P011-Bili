"""Read-only installation-path discovery; no commands or user account files."""
import datetime,json,pathlib
from awake_trial import ROOT,NATIVE,Adb,result_from,archive

def main():
    out=ROOT/'logs'/('P011-Install-Inspect-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir()
    adb=Adb(out)
    safety=(NATIVE/'runtime/native_safety.py').read_text(encoding='utf-8')
    code=safety+r'''
import re
s=stock_snapshot();require_stock(s)
report={'stock':s,'uid':os.getuid(),'init':os.readlink('/proc/1/exe'),'directories':{},'mounts':[],'paths':{}}
for directory in ('/etc/init.d','/etc/rcS.d','/etc/rc3.d','/etc/rc5.d','/etc/systemd/system','/lib/systemd/system','/etc/xdg/autostart','/home/.config/autostart'):
 if not os.path.isdir(directory):continue
 names=os.listdir(directory)
 if 'systemd' in directory:names=[x for x in names if re.search('zyb|Z03|weston|control|rc-local|multi-user|default.target',x)]
 report['directories'][directory]=sorted(names)
for path in ('/etc','/mnt/data','/etc/rc.local','/etc/inittab','/etc/xdg/weston/weston.ini','/home/.config/weston.ini'):
 if not os.path.exists(path):continue
 info=os.lstat(path);report['paths'][path]={'mode':oct(stat.S_IMODE(info.st_mode)),'symlink':stat.S_ISLNK(info.st_mode),'readonly_fs':bool(os.statvfs(path).f_flag&1)}
with open('/proc/mounts') as f:
 for line in f:
  fields=line.split()
  if len(fields)>=4 and fields[1] in ('/','/etc','/mnt/data','/home','/run'):
   report['mounts'].append({'at':fields[1],'type':fields[2],'readonly':'ro' in fields[3].split(',')})
report['trial_locks']={p:os.path.lexists(p) for p in ('/mnt/data/p011-toolbox/bili-awake.lock','/mnt/data/p011-toolbox/native.lock','/tmp/p011-menutest.lock','/mnt/data/p011-menu')}
print('RESULT='+repr(report))
'''
    result=result_from(adb.python('readonly-install-paths',code))
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));print('LOG_DIR='+str(out));archive(out)

if __name__=='__main__':main()
