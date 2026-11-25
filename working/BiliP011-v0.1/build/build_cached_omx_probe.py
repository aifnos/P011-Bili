"""PC-only cache experiment; original gst-omx source/artifacts remain intact."""
import hashlib,json,os,pathlib,subprocess,sys
from build_deps import B,S,TRIPLE,run
from build_cache_plugin import build_plugin
sys.path.insert(0,'/src/host')
from cache_artifact import PINS,identity,source_hashes
base=pathlib.Path('/src');before=source_hashes(base);work=B/'cached-omx-probe';work.mkdir(exist_ok=True)
mock=base/'host/cache_bridge_mock.cpp';bridge=base/'probes/memion_cache.cpp'
run(['g++','-std=c++17','-fPIC','-shared','-DP011_MOCK_LIBRARY=1',mock,'-o',work/'libmemion.so'])
run(['g++','-std=c++17','-DP011_CACHE_MOCK=1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
     '-rdynamic',mock,bridge,'-pthread','-ldl','-o',work/'cache-mock'])
env=dict(os.environ,LD_LIBRARY_PATH=str(work));subprocess.run([work/'cache-mock'],env=env,check=True,timeout=10)

vendor=base/'private-gst-linksysroot/usr'
plugin,modified,includes,libs=build_plugin(work)
app=list((vendor/'lib').glob('libgstapp-1.0.so.*'))
if len(app)!=1:raise ValueError('Ambiguous appsink ABI')
probe=work/'cache-decode-probe'
run([TRIPLE+'-g++','-O2','-std=c++17','-mfpu=neon','-pthread','-rdynamic',*['-I'+str(x) for x in includes],
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern',base/'probes/cache_decode_probe.cpp',bridge,
     *libs,*app,'-ldl','-Wl,--allow-shlib-undefined','-o',probe])
if source_hashes(base)!=before:raise ValueError('Cache experiment sources changed during build')
binaries={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in (probe,plugin)}
meta={'schema':1,'sources':before,'binaries':binaries,'pins':PINS,'synthetic_only':True,'modified_open_source':modified,'host_mock_passed':True}
out=base/'out'/('cache-omx-probe-'+identity(binaries,before))
if out.exists():
    if json.loads((out/'build.json').read_text())!=meta or any((out/x.name).read_bytes()!=x.read_bytes() for x in (probe,plugin)):raise ValueError('Immutable cache artifact collision')
else:
    out.mkdir()
    for file in (probe,plugin): (out/file.name).write_bytes(file.read_bytes())
    (out/'build.json').write_text(json.dumps(meta,indent=2))
    generated_source=out/'modified-open-source';generated_source.mkdir()
    for name in modified:(generated_source/name).write_bytes((work/name).read_bytes())
print('CACHE_PROBE='+str(out))
