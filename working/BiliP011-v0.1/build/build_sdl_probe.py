"""Host container only: isolated SDL 2.0.8 experiment, never replace link prefix."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from private_sdl_artifact import tree_hash, INPUT_NAMES

SRC=Path('/src')
SDL=SRC/'third_party/SDL2-2.0.8-p011'


def host_environment(environ):
    # Scanner is an executable for the build PC, not an ARM target program.
    # Merely removing CC is insufficient when the SDK precedes /usr/bin.
    cross_names={'CC','CXX','CPP','AS','AR','LD','NM','RANLIB','STRIP',
                 'PKG_CONFIG','PKG_CONFIG_LIBDIR','PKG_CONFIG_PATH',
                 'PKG_CONFIG_SYSROOT_DIR','CONFIG_SITE','CROSS_COMPILE',
                 'CPPFLAGS','CFLAGS','CXXFLAGS','LDFLAGS','LIBS',
                 'CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH',
                 'LD_LIBRARY_PATH','LD_PRELOAD'}
    env={k:v for k,v in environ.items() if k not in cross_names}
    env.update(PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               CC='/usr/bin/gcc',CXX='/usr/bin/g++',AR='/usr/bin/ar',
               RANLIB='/usr/bin/ranlib',PKG_CONFIG='/usr/bin/pkg-config',
               PKG_CONFIG_LIBDIR='/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig',
               PKG_CONFIG_PATH='',CONFIG_SITE='/dev/null')
    return env


def main():
    # build_deps creates container directories on import. Keep it out of pure
    # host environment tests and fail before touching any build state on a PC.
    if not Path('/opt/p011/sdk').is_dir() or not (SRC/'build/build_deps.py').is_file():
        raise RuntimeError('Run only inside the existing P011 builder container')
    from build_deps import P, W, S, TRIPLE, ENV, run
    sources={name:hashlib.sha256((SRC/name).read_bytes()).hexdigest() for name in
             INPUT_NAMES}
    before=tree_hash(SDL)
    build_identity=hashlib.sha256((before+json.dumps(sources,sort_keys=True)).encode()).hexdigest()
    work=W/'build'/('private-sdl-'+build_identity[:16]);work.mkdir(parents=True,exist_ok=True)
    metadata=work/'metadata';headers=metadata/'include';pc=metadata/'pkgconfig'
    for directory in (headers,pc):directory.mkdir(parents=True,exist_ok=True)
    wayland=S/'wayland-1.14.0'
    if not (wayland/'configure').is_file():raise ValueError('Pinned Wayland 1.14 source is required')
    # Use an old host scanner and its headers. A modern scanner may generate
    # wl_proxy_marshal_flags, unavailable on the pen. No Wayland runtime is built.
    scanner=W/'build/wayland-1.14-scanner-host-v1';scanner.mkdir(parents=True,exist_ok=True)
    hostenv=host_environment(os.environ)
    run(['/usr/bin/pkg-config','--exists','libxml-2.0','expat'],env=hostenv)
    if not (scanner/'Makefile').exists():
        run(['sh',wayland/'configure','--disable-libraries','--disable-documentation'],cwd=scanner,env=hostenv)
    run(['make','-j4','wayland-scanner'],cwd=scanner,env=hostenv)
    for path in (wayland/'src').glob('wayland-*.h'):shutil.copy2(path,headers/path.name)
    shutil.copy2(scanner/'src/wayland-version.h',headers/'wayland-version.h')
    run([scanner/'wayland-scanner','client-header',wayland/'protocol/wayland.xml',
         headers/'wayland-client-protocol.h'],env=hostenv)
    # These cursor/EGL headers are stable public structures, not host libc.
    for name in ('wayland-cursor.h','wayland-egl.h','wayland-egl-core.h'):
        shutil.copy2(Path('/usr/include')/name,headers/name)
    shutil.copytree('/usr/include/xkbcommon',headers/'xkbcommon',dirs_exist_ok=True)
    for name in ('wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'):
        lib='EGL' if name=='egl' else name
        extra=' -lmali' if name=='egl' else ''
        text=('prefix='+str(P)+'\nlibdir=${prefix}/lib\nincludedir='+str(headers)+'\n'
              'pkgdatadir='+str(wayland/'protocol')+'\nName: '+name+'\nDescription: Private P011 link metadata\n'
              'Version: 1.14.0\nLibs: -L${libdir} -l'+lib+extra+'\nCflags: -I${includedir}\n')
        (pc/(name+'.pc')).write_text(text)
    (pc/'wayland-scanner.pc').write_text('wayland_scanner='+str(scanner/'wayland-scanner')+'\nName: wayland-scanner\nDescription: Pinned host scanner\nVersion: 1.14.0\n')
    (pc/'wayland-protocols.pc').write_text('pkgdatadir=/usr/share/wayland-protocols\nName: wayland-protocols\nDescription: Protocol XML inputs\nVersion: 1.25\n')
    env=dict(ENV,PKG_CONFIG_LIBDIR=str(pc)+':'+str(P/'lib/pkgconfig'),
             CPPFLAGS='-I'+str(headers)+' -I'+str(P/'include'))
    prefix=work/'installed'
    if not (work/'Makefile').exists():
        run(['sh',SDL/'configure','--host='+TRIPLE,'--prefix='+str(prefix),
             '--disable-static','--enable-shared','--disable-video-x11','--disable-video-mir',
             '--disable-video-rpi','--disable-video-kmsdrm','--disable-video-vivante',
             '--disable-video-opengl','--enable-video-opengles','--enable-video-wayland',
             '--disable-video-wayland-qt-touch','--disable-audio','--disable-joystick',
             '--disable-haptic','--disable-video-vulkan'],cwd=work,env=env)
    config=(work/'include/SDL_config.h').read_text()
    for symbol in ('SDL_VIDEO_DRIVER_WAYLAND','SDL_VIDEO_OPENGL_EGL','SDL_VIDEO_OPENGL_ES2'):
        if '#define '+symbol+' 1' not in config:raise ValueError('Required SDL backend disabled: '+symbol)
    run(['make','-j8'],cwd=work,env=env)
    run(['make','install'],cwd=work,env=env)
    out=SRC/'out/private-sdl-probe';out.mkdir(parents=True,exist_ok=True)
    runtime=out/'libSDL2-2.0.so.0'
    shutil.copy2((prefix/'lib/libSDL2-2.0.so.0').resolve(),runtime)
    symbols=subprocess.check_output([TRIPLE+'-readelf','--dyn-syms','--wide',runtime],text=True)
    if 'P011_WaylandConfigureTimeoutMs' not in symbols:raise ValueError('Missing private SDL marker')
    if 'P011_WaylandCenterContentWindow' not in symbols:raise ValueError('Missing private centered-content API')
    run([TRIPLE+'-g++','-O2','-std=c++17','-DP011_DRM_TRACE=1','-DP011_PRIVATE_SDL_CONFIGURE=1',
         '-Wl,--export-dynamic',SRC/'probes/window_buffer_probe.cpp','-I'+str(prefix/'include/SDL2'),
         '-I'+str(P/'include'),'-I/src/wiliwili/library/borealis/library/include/borealis/extern',
         '-L'+str(out),'-L'+str(P/'lib'),'-Wl,-rpath-link,'+str(P/'lib'),
         '-Wl,--allow-shlib-undefined','-l:libSDL2-2.0.so.0','-lGLESv2','-lmali','-o',out/'window-buffer-probe'],env=env)
    if before!=tree_hash(SDL) or any(hashlib.sha256((SRC/name).read_bytes()).hexdigest()!=digest for name,digest in sources.items()):
        raise ValueError('Sources changed during build')
    manifest={'schema':2,'sources':sources,'sdl_tree_sha256':before,
              'binary_sha256':hashlib.sha256((out/'window-buffer-probe').read_bytes()).hexdigest(),
              'runtime_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest(),
              'configure_timeout_ms':500,
              'upstream_archives':{name:entry for name,entry in json.loads((W/'sources-lock.json').read_text()).items()
                                   if name in ('SDL2-2.0.8','wayland-1.14.0')}}
    (out/'build.json').write_text(json.dumps(manifest,indent=2))
    print('PRIVATE_SDL_PROBE_BUILT='+manifest['binary_sha256'])


if __name__=='__main__':main()
