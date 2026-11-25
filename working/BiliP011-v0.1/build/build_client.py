"""Build the private P011 client; PC container only, no device actions."""
from pathlib import Path
import sys
from build_deps import run, P, TRIPLE

out = Path('/src/out')
out.mkdir(exist_ok=True)
qr = Path('/src/wiliwili/library/QR-Code-generator/cpp')
common = ['-O2', '-std=c++17', '-I'+str(P/'include'),
          '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
          '-L'+str(P/'lib'), '-Wl,-rpath-link,'+str(P/'lib'),
          '-Wl,--allow-shlib-undefined']
run([TRIPLE+'-g++', *common, '-I'+str(qr), '/src/client/api.cpp',
     qr/'qrcodegen.cpp', '-lcurl', '-lcrypto', '-o', out/'bili-api'])
player = Path('/src/client/player_v2.cpp' if '--enhanced' in sys.argv else '/src/client/player.cpp')
diagnostic = ['-DP011_DRM_TRACE=1','-Wl,--export-dynamic'] if '--graphics-trace' in sys.argv else []
if '--bundled-omx' in sys.argv:
    if '--enhanced' not in sys.argv or '--strip-window' not in sys.argv:raise ValueError('Bundled OMX requires the fresh strip player')
    diagnostic.append('-DP011_BUNDLED_OMX=1')
if '--cached-output' in sys.argv:
    if '--bundled-omx' not in sys.argv:raise ValueError('Output cache requires a matching bundled OMX')
    diagnostic.append('-DP011_BUNDLED_OUTPUT_CACHE=1')
if '--frame-pacing' in sys.argv:diagnostic.append('-DP011_FRAME_PACING=1')
if '--presentation-feedback' in sys.argv:
    if '--strip-window' not in sys.argv:raise ValueError('Presentation observation requires the private strip player')
    from presentation_protocol import prepare
    diagnostic+=['-DP011_PRESENTATION_FEEDBACK=1',*prepare()]
if '--display-first' in sys.argv:
    if '--graphics-trace' not in sys.argv or '--strip-window' not in sys.argv:
        raise ValueError('Display-first requires traced private strip build')
    diagnostic.append('-DP011_DISPLAY_FIRST=1')
private_sdl=None
if '--strip-window' in sys.argv:
    if '--enhanced' not in sys.argv:raise ValueError('Strip window requires protocol 2')
    sys.path.insert(0,'/src/host')
    from private_sdl_artifact import validate_private_artifact
    _,_,private_sdl,_,_=validate_private_artifact(Path('/src'))
    diagnostic.append('-DP011_STRIP_WINDOW=1')
if player.exists():
    run([TRIPLE+'-g++', *common, *diagnostic, '-I'+str(P/'include/SDL2'),
         '-I'+str(P/'include/freetype2'), '-I/src/wiliwili/library/borealis/library/lib/extern/glfw/deps', player,
         str(private_sdl) if private_sdl else '-lSDL2-2.0', '-lGLESv2', '-lmali', '-lmpv', '-lfreetype',
         '-pthread', '-o', out/'bili-player'])
