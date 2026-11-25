"""Immutable source-bound cached-output real-stream diagnostic. Not production."""
import hashlib,json,re
from cache_artifact import PINS,source_hashes as cache_sources
from importlib.util import module_from_spec,spec_from_file_location
from fused_worker_artifact import source_hashes as worker_sources
from hardware_seek_trial import probe_sources

EXTRA=('host/cached_worker_artifact.py','host/cached_seek_trial.py','host/worker_wait_sampler.py','build/build_cached_worker.py',
       'probes/vsp_wait_observer.cpp','probes/vsp_gap_stats.hpp','probes/vsp_cycle_stats.hpp','host/vsp_wait_mock.cpp',
       'probes/omx_format_bridge.h','probes/omx_format_stats.hpp','build/format_omx_overlay.py',
       'build/build_format_plugin.py','host/omx_format_profile.py','build/cached_compat_overlay.py',
       'probes/cached_compat_guard.hpp','host/cached_compat_guard_test.cpp','host/cached_compat_evidence.py','host/vsp_readback.py')
BINS=('bili-hw','hardware-seek-probe','libgstomx.so')
def source_hashes(base):
    return {**cache_sources(base),**worker_sources(base),**probe_sources(base),
            **{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in EXTRA}}
def identity(binaries,sources):
    return 'cached-worker-'+hashlib.sha256(json.dumps([binaries,sources],sort_keys=True).encode('ascii')).hexdigest()[:16]

def modified_hashes(base):
    modules=[]
    for name in ('cache_omx_overlay','format_omx_overlay','cached_compat_overlay'):
        spec=spec_from_file_location('p011_'+name,base/('build/'+name+'.py'))
        module=module_from_spec(spec);spec.loader.exec_module(module);modules.append(module)
    source=base/'third_party/gst-omx-1.14.2-p011/omx'
    result={name:hashlib.sha256(modules[1].overlay(name,modules[0].overlay(name,(source/name).read_text(encoding='utf-8'))).encode('utf-8')).hexdigest()
            for name in ('gstomx.c','gstomxvideodec.c')}
    result['omx_format_bridge.h']=hashlib.sha256((base/'probes/omx_format_bridge.h').read_bytes()).hexdigest()
    result['cached_compat_guard.hpp']=hashlib.sha256((base/'probes/cached_compat_guard.hpp').read_bytes()).hexdigest()
    result['hardware_worker.cpp']=hashlib.sha256(modules[2].overlay((base/'client/hardware_worker.cpp').read_text(encoding='utf-8')).encode('utf-8')).hexdigest()
    result['hardware_client.hpp']=hashlib.sha256(modules[2].client_overlay((base/'client/hardware_client.hpp').read_text(encoding='utf-8')).encode('utf-8')).hexdigest()
    result['hardware_seek_probe.cpp']=hashlib.sha256(modules[2].probe_overlay((base/'probes/hardware_seek_probe.cpp').read_text(encoding='utf-8')).encode('utf-8')).hexdigest()
    return result
def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch('cached-worker-[a-f0-9]{16}',path.name):raise ValueError('Not a cached diagnostic worker')
    meta=json.loads((path/'build.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=1 or meta.get('format_observer_schema')!=1 or meta.get('cached_compat_schema')!=1 or meta.get('sources')!=source_hashes(base) or meta.get('pins')!=PINS or meta.get('production_default') is not False or meta.get('host_mock_passed') is not True:
        raise ValueError('Cached worker source or build boundary differs')
    if meta.get('geometry')!=[1920,1080,1920,1088,3133440]:raise ValueError('Unvalidated output geometry')
    binaries={}
    for name in BINS:
        file=path/name;raw=file.read_bytes()
        if file.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40:raise ValueError('Not an ARM ELF32 diagnostic')
        binaries[name]=hashlib.sha256(raw).hexdigest()
    if meta.get('binaries')!=binaries or path.name!=identity(binaries,meta['sources']):raise ValueError('Cached worker binary identity differs')
    modified=modified_hashes(base)
    if meta.get('modified_open_source')!=modified:raise ValueError('Corresponding source recipe differs')
    for name,digest in modified.items():
        file=path/'modified-open-source'/name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('Corresponding source differs')
    return meta
