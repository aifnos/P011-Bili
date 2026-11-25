"""Immutable private OMX experiment identity; no ADB or system install."""
import hashlib,json,re

def source_hashes(base):
    tree=base/'third_party/gst-omx-1.14.2-p011'
    names=[p.relative_to(base).as_posix() for p in tree.rglob('*') if p.is_file()]
    names+=['build/build_omx_probe.py','host/private_omx_artifact.py','host/omx_parallel_test.c',
            'host/omx_half_test.cpp','client/hardware_pack.hpp','client/hardware_output.hpp']
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in sorted(names)}

def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch(r'omx-probe-[a-f0-9]{16}',path.name):raise ValueError('Invalid private OMX artifact')
    meta=json.loads((path/'build.json').read_text())
    if meta.get('schema')!=4 or meta.get('sources')!=source_hashes(base):raise ValueError('Stale private OMX source')
    binary=path/'libgstomx.so';raw=binary.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if binary.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40 or meta.get('sha256')!=digest or path.name!='omx-probe-'+digest[:16]:raise ValueError('Private OMX binary differs')
    if type(meta.get('copy_mode')) is not int or meta['copy_mode'] not in (0,1,2,3,4) or type(meta.get('neon')) is not bool or meta['neon']!=(meta['copy_mode']==1):raise ValueError('Unknown private OMX mode')
    if type(meta.get('fused_half')) is not bool or meta['fused_half']!=(meta['copy_mode']==4):raise ValueError('Fused output mode differs')
    if meta.get('host_sanitizer_checks')!=38056 or meta.get('half_sanitizer_checks')!=2350:raise ValueError('Missing private copy sanitizer checks')
    return binary,meta
