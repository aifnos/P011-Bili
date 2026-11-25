"""Explicit read-only v2.4.0 dependency probe. No installation or service start."""
import ast
import base64
import datetime
import hashlib
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import zlib

ROOT=pathlib.Path(__file__).resolve().parents[3]
CODE='''import os,sys,hashlib,signal
signal.alarm(15)
pins={'/usr/bin/Z03':'cb8d6a78617d50f64c6adc8056427dd963bc83979cbb04e349275dd8e8ffb62a','/usr/bin/control_engine':'364b0bf820799070e89d9362000de4a3796a0e6a2d5f4d657464c6385b8dbd6d','/usr/bin/zyb_z03_launch.sh':'7bce5379e3cc78e5bd8c04ceb603c88814f24c3a7efd28105ecc3c5849d6a42b'}
def hashes():
 return {p:hashlib.sha256(open(p,'rb').read()).hexdigest() for p in pins}
before=hashes()
assert before==pins
assert not os.path.lexists('/mnt/data/p011-menu')
mods={}
for name in ('http.server','socketserver','urllib.parse','hmac','argparse','threading','select','fcntl','ssl','ipaddress'):
 try:__import__(name);mods[name]='available'
 except Exception as e:mods[name]=type(e).__name__+':'+str(e)
after=hashes()
assert after==before
print('RESULT='+repr({'python':sys.version.split()[0],'modules':mods,'dir_fd':os.open in os.supports_dir_fd,'O_NOFOLLOW':hasattr(os,'O_NOFOLLOW'),'hashes_unchanged':True,'hashes':after}))
'''


def main():
    adb=shutil.which('adb');assert adb
    result=subprocess.run([adb,'devices'],capture_output=True,timeout=10,check=True)
    serials=re.findall(rb'^(\S+)\s+device\s*$',result.stdout,re.M)
    assert len(serials)==1,'Expected exactly one ready device'
    packed=base64.b64encode(zlib.compress(CODE.encode(),9)).decode()
    loader='import zlib,base64;exec(zlib.decompress(base64.b64decode('+repr(packed)+')))'
    command='(python3 -B -c '+shlex.quote(loader)+'); rc=$?; printf "\\n__REMOTE_EXIT__=%s\\n" "$rc"'
    assert len(command.encode())<4096
    out=ROOT/'logs'/('ToolboxNext-Dependencies-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    p=subprocess.run([adb,'-s',serials[0].decode(),'shell',command],capture_output=True,timeout=25)
    (out/'stdout.raw').write_bytes(p.stdout);(out/'stderr.raw').write_bytes(p.stderr)
    clean=p.stdout.decode('utf-8','replace').replace('\r\r\n','\n').replace('\r\n','\n')
    exits=re.findall(r'^__REMOTE_EXIT__=(\d+)\s*$',clean,re.M)
    status={'host_exit':p.returncode,'remote_exit':int(exits[-1]) if exits else None,'device_writes':False}
    (out/'status.json').write_text(json.dumps(status,indent=2))
    assert p.returncode==0 and exits==['0']
    result=ast.literal_eval(re.search(r'^RESULT=(.+)$',clean,re.M).group(1))
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));print('LOG_DIR='+str(out))


if __name__=='__main__':main()
