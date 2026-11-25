"""Explicit synthetic-fixture-only cache candidate identity. No default export."""
import hashlib,json,re
from importlib.util import module_from_spec,spec_from_file_location
from private_omx_artifact import source_hashes as baseline_sources
from memion_observer_artifact import PINS as OBSERVER_PINS
PINS=dict(OBSERVER_PINS,**{
 '/usr/lib/libomx_avcdec_hw_sprd.so':'10f78010d85ec6d93fce94e7ddf05fc9a783237aa59dff8bda2df7077badbe14',
 '/usr/lib/libsprd_omx_core.so':'bcf76bb48a53aa270ea0d901f0c1db10e2c3d9bc0289bfbe93c4ed302059428b'})
NAMES=('probes/memion_cache.cpp','probes/cache_decode_probe.cpp','probes/omx_cache_bridge.h',
       'build/build_cached_omx_probe.py','build/cache_omx_overlay.py','host/cache_artifact.py',
       'host/cache_bridge_mock.cpp','host/cache_trial.py','host/cache_fixture.py',
       'host/memion_observer_artifact.py','host/ion_copy_trial.py','build/build_cache_plugin.py')
def source_hashes(base):
    return dict(baseline_sources(base),**{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in NAMES})
def identity(binaries,sources):return hashlib.sha256(json.dumps([binaries,sources],sort_keys=True).encode('ascii')).hexdigest()[:16]
def modified_hashes(base,fallback=False):
    spec=spec_from_file_location('p011_cache_overlay',base/'build/cache_omx_overlay.py')
    module=module_from_spec(spec);spec.loader.exec_module(module)
    source=base/'third_party/gst-omx-1.14.2-p011/omx'
    return {name:hashlib.sha256(module.overlay(name,(source/name).read_text(encoding='utf-8'),fallback=fallback).encode('utf-8')).hexdigest()
            for name in ('gstomx.c','gstomxvideodec.c')}
def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch('cache-omx-probe-[a-f0-9]{16}',path.name):raise ValueError('Not a cache diagnostic artifact')
    meta=json.loads((path/'build.json').read_text())
    if meta.get('schema')!=1 or meta.get('sources')!=source_hashes(base) or meta.get('pins')!=PINS or meta.get('synthetic_only') is not True or meta.get('host_mock_passed') is not True:raise ValueError('Cache artifact inputs differ')
    modified=modified_hashes(base)
    if meta.get('modified_open_source')!=modified:raise ValueError('Cache overlay recipe differs')
    for name,digest in modified.items():
        file=path/'modified-open-source'/name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('Cache corresponding source differs')
    binaries={}
    for name in ('cache-decode-probe','libgstomx.so'):
        file=path/name;raw=file.read_bytes()
        if file.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40:raise ValueError('Cache artifact is not ARM ELF32')
        binaries[name]=hashlib.sha256(raw).hexdigest()
    if meta.get('binaries')!=binaries or path.name!='cache-omx-probe-'+identity(binaries,meta['sources']):raise ValueError('Cache artifact identity differs')
    return meta
