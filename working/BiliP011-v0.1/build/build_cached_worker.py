"""Build a separate three-binary diagnostic, leaving all media exports intact."""
import hashlib,json,pathlib,runpy,sys
import build_hardware
from build_format_plugin import build_plugin as build_format_plugin
from cached_compat_overlay import overlay as compat_overlay,client_overlay,probe_overlay
from build_deps import B,TRIPLE,run
from build_hardware import main as build_worker
sys.path.insert(0,'/src/host')
from cached_worker_artifact import source_hashes,identity,BINS,PINS
from cache_artifact import validate as validate_cache

base=pathlib.Path('/src');before=source_hashes(base)
plugin_build=runpy.run_path(str(base/'build/build_cached_omx_probe.py'))
plugin_dir=plugin_build['out'];plugin_meta=validate_cache(base,plugin_dir)
work=B/'cached-real-worker';work.mkdir(exist_ok=True)
format_work=B/'cached-format-plugin'
format_plugin,format_modified,_,_=build_format_plugin(format_work)
for name,body in (
    ('hardware_worker.cpp',compat_overlay((base/'client/hardware_worker.cpp').read_text(encoding='utf-8')).encode('utf-8')),
    ('hardware_client.hpp',client_overlay((base/'client/hardware_client.hpp').read_text(encoding='utf-8')).encode('utf-8')),
    ('hardware_seek_probe.cpp',probe_overlay((base/'probes/hardware_seek_probe.cpp').read_text(encoding='utf-8')).encode('utf-8')),
    ('cached_compat_guard.hpp',(base/'probes/cached_compat_guard.hpp').read_bytes())):
    (format_work/name).write_bytes(body);format_modified[name]=hashlib.sha256(body).hexdigest()
run(['g++','-O2','-std=c++17','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
     base/'host/cached_compat_guard_test.cpp','-o',work/'cached-compat-guard-test'])
run([work/'cached-compat-guard-test'])
run(['g++','-O2','-std=c++17','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
     '-DP011_VSP_PROFILE_MOCK=1','-I/src/third_party/gst-omx-1.14.2-p011/omx/openmax',
     base/'host/vsp_wait_mock.cpp',base/'probes/vsp_wait_observer.cpp','-pthread','-ldl','-o',work/'vsp-wait-mock'])
run([work/'vsp-wait-mock'])
# Diagnostic-only link extension. Reuse the exact ordinary header/link recipe;
# never alter that recipe or the production build/default media source gates.
original_run=build_hardware.run
def diagnostic_link(command,*args,**kwargs):
    command=list(command)
    if '/src/client/hardware_worker.cpp' in command:
        if command.count('/src/client/hardware_worker.cpp')!=1 or '-DP011_OUTPUT_CACHE_PROBE=1' not in command or '-DP011_BUNDLED_OMX=1' in command:
            raise ValueError('Unexpected diagnostic compile recipe')
        command.insert(command.index('/src/client/hardware_worker.cpp')+1,'/src/probes/vsp_wait_observer.cpp')
        command[command.index('/src/client/hardware_worker.cpp')]=str(format_work/'hardware_worker.cpp')
        command[1:1]=['-I/src/client','-I/src/probes']
    return original_run(command,*args,**kwargs)
build_hardware.run=diagnostic_link
try:build_worker(work/'bili-hw',cache_probe=True)
finally:build_hardware.run=original_run
run([TRIPLE+'-g++','-O2','-std=c++17','-pthread','-DP011_PRIVATE_OMX_PROBE=1','-DP011_OUTPUT_CACHE_PROBE=1',
     '-I/src/client','-MMD','-MF',work/'hardware-seek-probe.d',
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
     format_work/'hardware_seek_probe.cpp','-o',work/'hardware-seek-probe'])
dependencies=(work/'hardware-seek-probe.d').read_text().replace('\\\n',' ').split()
if (str(format_work/'hardware_client.hpp') not in dependencies or
    str(format_work/'cached_compat_guard.hpp') not in dependencies or
    '/src/client/hardware_client.hpp' in dependencies):
    raise ValueError('Diagnostic driver did not use its generated launch guard')
files={name:(format_plugin if name=='libgstomx.so' else work/name) for name in BINS}
if source_hashes(base)!=before:raise ValueError('Sources changed during cached-worker build')
binaries={name:hashlib.sha256(file.read_bytes()).hexdigest() for name,file in files.items()}
meta=dict(schema=1,sources=before,binaries=binaries,pins=PINS,production_default=False,
          geometry=[1920,1080,1920,1088,3133440],host_mock_passed=True,
          format_observer_schema=1,cached_compat_schema=1,modified_open_source=format_modified,synthetic_artifact=plugin_dir.name)
out=base/'out'/identity(binaries,before)
if out.exists():
    if json.loads((out/'build.json').read_text())!=meta or any((out/name).read_bytes()!=file.read_bytes() for name,file in files.items()):raise ValueError('Immutable cached-worker collision')
else:
    out.mkdir()
    for name,file in files.items():(out/name).write_bytes(file.read_bytes())
    (out/'build.json').write_text(json.dumps(meta,indent=2))
    modified=out/'modified-open-source';modified.mkdir()
    for name in meta['modified_open_source']:(modified/name).write_bytes((format_work/name).read_bytes())
print('CACHED_WORKER='+str(out),flush=True)
