"""PC-only, immutable dependency export of CPython's matching JSON stdlib.
Never installs into target Python and never executes downloaded code here.
"""
import hashlib,json,pathlib,urllib.request,zipfile
BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE/'client/deps';ROOT.mkdir(parents=True,exist_ok=True)
files={}
for name in ('__init__.py','decoder.py','encoder.py','scanner.py'):
    url='https://raw.githubusercontent.com/python/cpython/v3.5.10/Lib/json/'+name
    with urllib.request.urlopen(url,timeout=30) as response:files['json/'+name]=response.read(131072)
url='https://raw.githubusercontent.com/python/cpython/v3.5.10/LICENSE'
with urllib.request.urlopen(url,timeout=30) as response:files['LICENSE-PSF.txt']=response.read(131072)
lock={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
lockfile=ROOT/'json35-sources.json'
if lockfile.exists() and json.loads(lockfile.read_bytes())!=lock:raise ValueError('Dependency source changed')
target=ROOT/'stdlib-json35.zip'
if not target.exists():
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(2020,9,5,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert {name:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}==lock
lockfile.write_text(json.dumps(lock,indent=2),encoding='utf-8')
print('PRIVATE_JSON_ZIP_SHA256='+hashlib.sha256(target.read_bytes()).hexdigest())
