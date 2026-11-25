"""Verified optional bundle plugin, preserving unknown geometry uncached."""
import hashlib,json,re
from cache_artifact import PINS,source_hashes as cache_sources,modified_hashes

EXTRA=('host/output_cache_artifact.py','host/output_cache_mock.cpp','build/build_output_cache.py','build/test_output_cache.py')
def source_hashes(base):
    return {**cache_sources(base),**{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in EXTRA}}
def identity(sha,sources):
    return 'omx-output-cache-'+hashlib.sha256(json.dumps([sha,sources],sort_keys=True).encode('ascii')).hexdigest()[:16]
def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch('omx-output-cache-[a-f0-9]{16}',path.name):raise ValueError('Not an output-cache plugin')
    meta=json.loads((path/'build.json').read_text(encoding='utf-8'))
    if meta.get('schema')!=1 or meta.get('sources')!=source_hashes(base) or meta.get('pins')!=PINS or meta.get('host_mock_passed') is not True:
        raise ValueError('Cache bundle source boundary differs')
    if meta.get('copy_mode')!=4 or meta.get('unverified_geometry_uncached') is not True or meta.get('cached_geometry')!=[1920,1080,1920,1088,3133440]:
        raise ValueError('Unverified cache geometry or fallback')
    file=path/'libgstomx.so';raw=file.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if file.is_symlink() or raw[:5]!=b'\x7fELF\x01' or raw[18:20]!=b'\x28\x00' or sha!=meta.get('sha256') or path.name!=identity(sha,meta['sources']):
        raise ValueError('Changed or invalid cache plugin')
    modified=modified_hashes(base,fallback=True)
    if meta.get('modified_open_source')!=modified:raise ValueError('Cache bundle corresponding source recipe differs')
    for name,digest in modified.items():
        file=path/'modified-open-source'/name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('Cache bundle corresponding source differs')
    return path/'libgstomx.so',meta
