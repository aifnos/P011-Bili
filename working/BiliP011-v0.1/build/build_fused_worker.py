"""Build only an immutable diagnostic worker; leave default media/exports intact."""
import hashlib,json,pathlib,sys
from build_deps import B
from build_hardware import main as build_worker
sys.path.insert(0,'/src/host')
from fused_worker_artifact import source_hashes

base=pathlib.Path('/src');before=source_hashes(base)
target=B/'bili-hw-fused-probe';build_worker(target)
if before!=source_hashes(base):raise ValueError('Worker sources changed during build')
raw=target.read_bytes();digest=hashlib.sha256(raw).hexdigest()
out=base/'out'/('fused-worker-'+digest[:16])
meta={'schema':1,'sha256':digest,'sources':before,'device_tested':False,'production_default':False}
if out.exists():
    if (out/'bili-hw').read_bytes()!=raw or json.loads((out/'build.json').read_text())!=meta:raise ValueError('Immutable worker identity collision')
else:
    out.mkdir();(out/'bili-hw').write_bytes(raw);(out/'build.json').write_text(json.dumps(meta,indent=2))
print('FUSED_WORKER='+str(out),flush=True)
