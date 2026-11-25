"""Source/ELF gate for a finite copy experiment, never a production export."""
import hashlib,json,re

NAMES=('client/hardware_worker.cpp','client/hardware_protocol.hpp','client/hardware_pack.hpp',
       'client/hardware_output.hpp','client/hardware_allocation.hpp','client/h264_access_unit.hpp',
       'build/build_hardware.py','build/build_fused_worker.py','host/fused_worker_artifact.py')

def source_hashes(base):
    return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in NAMES}

def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch('fused-worker-[a-f0-9]{16}',path.name):raise ValueError('Not a private worker artifact')
    meta=json.loads((path/'build.json').read_text())
    if meta.get('schema')!=1 or meta.get('sources')!=source_hashes(base):raise ValueError('Stale fused worker source')
    binary=path/'bili-hw';raw=binary.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if binary.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40 or meta.get('sha256')!=digest or path.name!='fused-worker-'+digest[:16]:raise ValueError('Worker identity differs')
    return binary,meta
