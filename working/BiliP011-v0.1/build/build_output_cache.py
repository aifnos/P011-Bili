"""Build opt-in bundle OMX; no automatic export, installation, or device use."""
import hashlib,json,pathlib,runpy,sys
from build_deps import B
from build_cache_plugin import build_plugin
sys.path.insert(0,'/src/host')
from output_cache_artifact import source_hashes,identity,PINS

base=pathlib.Path('/src');before=source_hashes(base)
runpy.run_path(str(base/'build/test_output_cache.py'))
work=B/'output-cache-plugin'
plugin,modified,_,_=build_plugin(work,fallback=True)
if source_hashes(base)!=before:raise ValueError('Cache bundle source changed during build')
sha=hashlib.sha256(plugin.read_bytes()).hexdigest()
meta=dict(schema=1,sources=before,pins=PINS,sha256=sha,copy_mode=4,host_mock_passed=True,
          unverified_geometry_uncached=True,cached_geometry=[1920,1080,1920,1088,3133440],modified_open_source=modified)
out=base/'out'/identity(sha,before)
if out.exists():
    if json.loads((out/'build.json').read_text())!=meta or (out/'libgstomx.so').read_bytes()!=plugin.read_bytes():raise ValueError('Immutable cache bundle collision')
else:
    out.mkdir();(out/'libgstomx.so').write_bytes(plugin.read_bytes());(out/'build.json').write_text(json.dumps(meta,indent=2))
    (out/'modified-open-source').mkdir()
    for name in modified:(out/'modified-open-source'/name).write_bytes((work/name).read_bytes())
print('OUTPUT_CACHE_PLUGIN='+str(out),flush=True)
