"""Build a private, finite graphics experiment on the host only."""
from build_deps import P, TRIPLE, run
import hashlib
import json
from pathlib import Path

names = ('probes/window_buffer_probe.cpp', 'client/drm_trace.hpp', 'build/build_window_probe.py')
sources = {name: hashlib.sha256((Path('/src')/name).read_bytes()).hexdigest() for name in names}

run([TRIPLE+'-g++','-O2','-std=c++17','-DP011_DRM_TRACE=1','-Wl,--export-dynamic',
     '/src/probes/window_buffer_probe.cpp','-I'+str(P/'include/SDL2'),'-I'+str(P/'include'),
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
     '-L'+str(P/'lib'),'-Wl,-rpath-link,'+str(P/'lib'),'-Wl,--allow-shlib-undefined',
     '-lSDL2-2.0','-lGLESv2','-lmali','-o','/src/out/window-buffer-probe'])
if any(hashlib.sha256((Path('/src')/name).read_bytes()).hexdigest()!=digest for name,digest in sources.items()):
    raise ValueError('Sources changed during compilation')
manifest = {'schema': 1, 'sources': sources,
            'binary_sha256': hashlib.sha256(Path('/src/out/window-buffer-probe').read_bytes()).hexdigest()}
Path('/src/out/window-buffer-probe.build.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
