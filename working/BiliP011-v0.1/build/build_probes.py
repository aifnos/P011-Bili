"""Build finite native probes; only run inside the dedicated PC container."""
from pathlib import Path
from build_deps import run, P, TRIPLE

out=Path('/src/out');out.mkdir(exist_ok=True)
for name in ('gles_probe', 'mpv_probe'):
    src=Path('/src/probes')/(name+'.c')
    if not src.exists():continue
    libs=['-lSDL2-2.0','-lGLESv2','-lmali']
    if name=='mpv_probe':libs+=['-lmpv']
    run([TRIPLE+'-gcc','-O2',src,'-I'+str(P/'include/SDL2'),'-I'+str(P/'include'),
         '-L'+str(P/'lib'),'-Wl,-rpath-link,'+str(P/'lib'),'-Wl,--allow-shlib-undefined',
         *libs,'-o',out/name.replace('_','-')])
run([TRIPLE+'-g++','-O2','-std=c++17','/src/probes/api_probe.cpp',
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern','-I'+str(P/'include'),
     '-L'+str(P/'lib'),'-Wl,-rpath-link,'+str(P/'lib'),'-Wl,--allow-shlib-undefined',
     '-lcurl','-lcrypto','-o',out/'api-probe'])
