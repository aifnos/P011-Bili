"""PC-only build of a finite, synthetic ION copy comparison."""
import hashlib,json,pathlib,sys
from build_deps import TRIPLE,run
sys.path.insert(0,'/src/host')
from ion_copy_trial import artifact_name,source_hashes
base=pathlib.Path('/src');before=source_hashes(base)
target=pathlib.Path('/work/p011/build/ion-copy-probe')
run([TRIPLE+'-g++','-O2','-std=c++17','-mfpu=neon','-pthread','-DP011_OMX_PARALLEL_COPY=1',
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern',base/'probes/ion_copy_probe.cpp','-o',target])
if before!=source_hashes(base):raise ValueError('Sources changed during build')
raw=target.read_bytes();digest=hashlib.sha256(raw).hexdigest()
out=base/'out'/artifact_name(digest,before)
metadata={'schema':2,'sha256':digest,'sources':before,'production':False}
if out.exists():
    if out.is_symlink() or set(p.name for p in out.iterdir())!={'ion-copy-probe','build.json'} or (out/'ion-copy-probe').is_symlink() or (out/'build.json').is_symlink() or (out/'ion-copy-probe').read_bytes()!=raw or json.loads((out/'build.json').read_text())!=metadata:raise ValueError('Immutable artifact collision')
else:
    out.mkdir()
    (out/'ion-copy-probe').write_bytes(raw)
    (out/'build.json').write_text(json.dumps(metadata,indent=2))
print('ION_COPY_PROBE='+str(out))
