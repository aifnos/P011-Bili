"""Offline ARM build. /src and /work are read-only; only /output is writable."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
BASE = Path('/src')
NATIVE = BASE / 'formal/native'
OUT = Path('/output')
TRIPLE = 'arm-buildroot-linux-gnueabihf'
WORK = Path('/work/p011')
PREFIX = WORK / 'prefix'


def run(command, capture=False):
    command = list(map(str, command))
    print('RUN ' + ' '.join(command), flush=True)
    if capture:
        return subprocess.check_output(command, text=True)
    subprocess.run(command, check=True)


def main():
    # Revalidate the accepted SDL/cache pair without writing to legacy output.
    sys.path.insert(0, str(BASE / 'host'))
    from strip_player_artifact import validate_strip_player, validate_bundled_omx
    sdl = validate_strip_player(BASE)
    validate_bundled_omx(BASE)
    generated = OUT / 'generated'
    generated.mkdir()
    presentation = generated / 'presentation'
    presentation.mkdir()
    scanner = WORK / 'build/wayland-1.14-scanner-host-v1/wayland-scanner'
    wayland = WORK / 'sources/wayland-1.14.0'
    xml = BASE / 'third_party/presentation-time-v1.xml'
    run([scanner, 'client-header', wayland / 'protocol/wayland.xml', presentation / 'wayland-client-protocol.h'])
    run([scanner, 'client-header', xml, presentation / 'presentation-time-client-protocol.h'])
    run([scanner, 'code', xml, presentation / 'presentation-time-protocol.c'])
    obj = presentation / 'presentation-time-protocol.o'
    presentation_flags = ['-I' + str(presentation), '-I' + str(wayland / 'src')]
    run([TRIPLE + '-gcc', '-O2', '-fPIC', *presentation_flags, '-c', presentation / 'presentation-time-protocol.c', '-o', obj])
    common = ['-O2', '-std=c++17', '-I' + str(PREFIX / 'include'),
              '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
              '-L' + str(PREFIX / 'lib'), '-Wl,-rpath-link,' + str(PREFIX / 'lib'),
              '-Wl,--allow-shlib-undefined']
    definitions = ['-DP011_DRM_TRACE=1', '-Wl,--export-dynamic',
                   '-DP011_BUNDLED_OMX=1', '-DP011_BUNDLED_OUTPUT_CACHE=1',
                   '-DP011_PRESENTATION_FEEDBACK=1', '-DP011_DISPLAY_FIRST=1', '-DP011_STRIP_WINDOW=1']
    binary_dir = OUT / 'bin'
    binary_dir.mkdir()
    run([TRIPLE + '-g++', *common, *definitions, *presentation_flags, obj, '-lwayland-client',
         '-I' + str(PREFIX / 'include/SDL2'), '-I' + str(PREFIX / 'include/freetype2'),
         '-I/src/wiliwili/library/borealis/library/lib/extern/glfw/deps',
         NATIVE / 'client/player_v2.cpp', sdl, '-lGLESv2', '-lmali', '-lmpv', '-lfreetype',
         '-pthread', '-o', binary_dir / 'bili-player'])
    core = WORK / 'sources/gstreamer-1.14.2'
    base = WORK / 'sources/gst-plugins-base-1.14.2'
    headers = generated / 'gst-public-headers'
    (headers / 'gst/video').mkdir(parents=True)
    values = {'GSTCONFIG_BUILT_WITH_MSVC': '0', 'GST_VERSION_MAJOR': '1',
              'GST_VERSION_MINOR': '14', 'GST_VERSION_MICRO': '2', 'GST_VERSION_NANO': '0'}
    for name in ('gstconfig.h', 'gstversion.h'):
        body = (core / 'gst' / (name + '.in')).read_text()
        body = re.sub(r'@([A-Z0-9_]+)@', lambda m: values.get(m[1], '') if m[1].endswith('_DEFINE') or m[1] in values else m[0], body)
        if re.search(r'@[A-Z0-9_]+@', body):
            raise ValueError('Unresolved public GStreamer header')
        (headers / 'gst' / name).write_text(body)
    (headers / 'gst/gstenumtypes.h').write_text(run([
        'glib-mkenums', '--template', core / 'gst/gstenumtypes.h.template', *sorted((core / 'gst').glob('*.h'))], capture=True))
    video = base / 'gst-libs/gst/video'
    run(['python3', video / 'video_mkenum.py', 'glib-mkenums', headers / 'gst/video/video-enumtypes.h', *sorted(video.glob('*.h'))])
    vendor = BASE / 'private-gst-linksysroot/usr'
    includes = [headers, core, core / 'libs', base / 'gst-libs', vendor / 'include/glib-2.0',
                vendor / 'lib/glib-2.0/include', PREFIX / 'include',
                BASE / 'wiliwili/library/borealis/library/include/borealis/extern']
    libs = [vendor / 'lib' / name for name in (
        'libgstvideo-1.0.so.0.1402.0', 'libgstapp-1.0.so.0.1402.0', 'libgstbase-1.0.so.0.1402.0',
        'libgstreamer-1.0.so.0.1402.0', 'libgobject-2.0.so.0.5400.3', 'libglib-2.0.so.0.5400.3')]
    run([TRIPLE + '-g++', '-O2', '-mfpu=neon', '-std=c++17', '-pthread',
         '-DP011_BUNDLED_OMX=1', '-DP011_BUNDLED_OUTPUT_CACHE=1', '-rdynamic',
         *['-I' + str(path) for path in includes], NATIVE / 'client/hardware_worker.cpp',
         NATIVE / 'probes/memion_cache.cpp', *libs, '-ldl', '-Wl,--allow-shlib-undefined',
         '-o', binary_dir / 'bili-hw'])
    artifacts = {}
    for name in ('bili-player', 'bili-hw'):
        path = binary_dir / name
        raw = path.read_bytes()
        header = run([TRIPLE + '-readelf', '-h', path], capture=True)
        dynamic = run([TRIPLE + '-readelf', '-d', path], capture=True)
        versions_raw = run([TRIPLE + '-readelf', '-V', path], capture=True)
        (OUT / (name + '.elf-header.raw')).write_text(header)
        (OUT / (name + '.elf-dynamic.raw')).write_text(dynamic)
        (OUT / (name + '.elf-versions.raw')).write_text(versions_raw)
        versions = sorted(set(re.findall(r'\bGLIBC_(\d+\.\d+(?:\.\d+)?)', versions_raw)))
        if raw[:6] != b'\x7fELF\x01\x01' or raw[18:20] != b'\x28\x00' or any(tuple(map(int, v.split('.'))) > (2, 27) for v in versions):
            raise ValueError('Non-ARM32 or incompatible glibc: ' + name)
        artifacts['bin/' + name] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
            elf_class='ELF32', elf_machine='ARM', byte_order='little', glibc=versions,
            needed=re.findall(r'\(NEEDED\).*\[(.*?)\]', dynamic))
    toolchain = run([TRIPLE + '-g++', '--version'], capture=True)
    toolchain_sha = run(['sha256sum', '/opt/p011/sdk/bin/' + TRIPLE + '-g++.br_real'], capture=True)
    compiler = dict(version=toolchain, binary_sha256=toolchain_sha.split()[0], triple=TRIPLE)
    (OUT / 'container-result.json').write_text(json.dumps(dict(artifacts=artifacts, toolchain=compiler), indent=2))


if __name__ == '__main__':
    main()
