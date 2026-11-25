"""Container-only generated link prefix. Vendor files are link-only, never packaged."""
import json
import pathlib
import re
import shutil
import subprocess

P = pathlib.Path('/work/p011/prefix')
P.mkdir(parents=True, exist_ok=True)
for directory in ('lib/pkgconfig', 'include', 'lib/cmake/SDL2'):
    (P / directory).mkdir(parents=True, exist_ok=True)
manifest = json.loads(pathlib.Path('/src/private-linksysroot/manifest.json').read_text())
for entry in manifest['libraries']:
    path = pathlib.Path(entry['path'])
    if 'libstdc++' in path.name:
        continue
    dest = P / 'lib' / path.name
    if not dest.exists():
        shutil.copy2('/src/private-linksysroot' + entry['path'], dest)
    output = subprocess.check_output(['arm-buildroot-linux-gnueabihf-readelf', '-d', str(dest)], text=True)
    soname = re.search(r'\(SONAME\).*\[(.*?)\]', output).group(1)
    for name in (soname, path.name.split('.so')[0] + '.so'):
        link = P / 'lib' / name
        if not link.exists():
            link.symlink_to(path.name)

for name in ('pulse',):
    dest = P / 'include' / name
    if not dest.exists():
        shutil.copytree('/src/private-linksysroot/usr/include/' + name, dest)
for name in ('zlib.h','zconf.h'):
    shutil.copy2('/src/private-linksysroot/usr/include/'+name,P/'include'/name)
for name in ('EGL', 'GLES2', 'GLES3', 'KHR', 'SDL2'):
    dest = P / 'include' / name
    if not dest.exists():
        shutil.copytree('/usr/include/' + name, dest)
# Do not use host x86 feature macros (immintrin, SIZEOF_VOIDP=8) for ARM.
shutil.copy2('/src/wiliwili/library/borealis/library/lib/extern/SDL/include/SDL_config_minimal.h', P / 'include/SDL2/SDL_config.h')

for name, version, libs, cflags in [
    ('egl', '1.4', '-lEGL -lmali', ''),
    ('glesv2', '2.0', '-lGLESv2 -lmali', ''),
    ('libpulse', '11.1', '-lpulse', '-D_REENTRANT'),
    ('sdl2', '2.0.8', '-lSDL2-2.0', '-I${includedir}/SDL2 -D_REENTRANT'),
]:
    text = 'prefix=' + str(P) + '\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\n'
    text += 'Name: ' + name + '\nDescription: P011 existing ABI link only\nVersion: ' + version + '\n'
    text += 'Libs: -L${libdir} ' + libs + '\nCflags: -I${includedir} ' + cflags + '\n'
    (P / 'lib/pkgconfig' / (name + '.pc')).write_text(text)
(P / 'lib/cmake/SDL2/SDL2Config.cmake').write_text('set(SDL2_FOUND TRUE)\nset(SDL2_INCLUDE_DIRS /work/p011/prefix/include/SDL2)\nset(SDL2_LIBRARIES /work/p011/prefix/lib/libSDL2-2.0.so)\n')
print('PRIVATE_LINK_PREFIX_READY')
