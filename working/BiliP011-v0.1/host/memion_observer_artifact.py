"""Immutable observer identity and exact vendor ABI pins; not a cache modifier."""
import hashlib,json,re
NAMES=('probes/memion_observer.cpp','build/build_memion_observer.py','host/memion_observer_artifact.py',
       'host/memion_observer_mock.cpp')
PINS={'/usr/lib/libmemion.so':'d19e0083e03c1c72a145af569eeb52af7dab558194ae39ebddf0112aceeb6628',
      '/usr/lib/libstagefright_sprd_h264dec.so':'31435b48a7aaa48db9639ced66aca3519b55eafe717a97be4eea77b9b6d2dfc4'}
def source_hashes(base):return {name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in NAMES}
def artifact_name(digest,sources):
    return 'memion-observer-'+hashlib.sha256(json.dumps([digest,sources],sort_keys=True).encode('ascii')).hexdigest()[:16]
def validate(base,path):
    path=path.resolve()
    if path.parent!=base/'out' or not re.fullmatch('memion-observer-[a-f0-9]{16}',path.name):raise ValueError('Not an observer artifact')
    meta=json.loads((path/'build.json').read_text());binary=path/'libmemion-observer.so';raw=binary.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if binary.is_symlink() or raw[:5]!=b'\x7fELF\x01' or int.from_bytes(raw[18:20],'little')!=40 or meta!={'schema':1,'sha256':digest,'sources':source_hashes(base),'pins':PINS,'read_only_arguments':True} or path.name!=artifact_name(digest,meta['sources']):raise ValueError('Observer identity/ABI differs')
    return binary,meta
