"""PC-only observer ABI forwarding test and immutable ARM build."""
import hashlib,json,os,pathlib,subprocess,sys
from build_deps import B,TRIPLE,run
sys.path.insert(0,'/src/host')
from memion_observer_artifact import PINS,artifact_name,source_hashes
base=pathlib.Path('/src');before=source_hashes(base);work=B/'memion-observer';work.mkdir(exist_ok=True)
source=base/'probes/memion_observer.cpp';mock=base/'host/memion_observer_mock.cpp'
run(['g++','-std=c++17','-fPIC','-shared',mock,'-DP011_MOCK_LIBRARY=1','-o',work/'libmemion.so'])
run(['g++','-std=c++17',mock,'-ldl','-o',work/'mock-caller'])
run(['g++','-std=c++17','-fPIC','-shared',source,'-ldl','-o',work/'observer-host.so'])
env=dict(os.environ,LD_LIBRARY_PATH=str(work),LD_PRELOAD=str(work/'observer-host.so'),P011_SEEK_PROBE_ROOT='/mnt/data/p011-toolbox/bili-seek-probe-'+'0'*24)
trial=subprocess.run([work/'mock-caller'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,check=True)
event=json.loads(trial.stdout)
if trial.stderr or event!={'ion_allocation_event':0,'bytes':3133440,'heapmask':0x80000001,'mapping_flags':512,'result':17}:raise ValueError('Observer changed or leaked mock arguments')
env['P011_SEEK_PROBE_ROOT']='/tmp/not-a-private-probe'
trial=subprocess.run([work/'mock-caller'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,check=True)
if trial.stdout or trial.stderr:raise ValueError('Observer emitted outside private scope')
target=work/'libmemion-observer.so'
run([TRIPLE+'-g++','-O2','-std=c++17','-fPIC','-shared',source,'-ldl','-o',target])
if source_hashes(base)!=before:raise ValueError('Observer sources changed during build')
raw=target.read_bytes();digest=hashlib.sha256(raw).hexdigest();out=base/'out'/artifact_name(digest,before)
meta={'schema':1,'sha256':digest,'sources':before,'pins':PINS,'read_only_arguments':True}
if out.exists():
    if (out/'libmemion-observer.so').read_bytes()!=raw or json.loads((out/'build.json').read_text())!=meta:raise ValueError('Immutable observer collision')
else:
    out.mkdir();(out/'libmemion-observer.so').write_bytes(raw);(out/'build.json').write_text(json.dumps(meta,indent=2))
print('MEMION_OBSERVER='+str(out))
