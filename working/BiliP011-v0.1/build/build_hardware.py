"""Build isolated stock-GStreamer worker. No vendor library is distributed."""
import argparse,pathlib,re,subprocess
from build_deps import W,S,B,P,TRIPLE,run,source


def main(output='/src/out/bili-hw',bundled=False,cache_probe=False,cached_output=False):
    if bundled and cache_probe:raise ValueError('Cache diagnostic is not a production export')
    if cached_output and (not bundled or cache_probe):raise ValueError('Output cache needs the verified bundled player pair')
    core=source('gstreamer-1.14.2','https://gstreamer.freedesktop.org/src/gstreamer/gstreamer-1.14.2.tar.xz')
    base=source('gst-plugins-base-1.14.2','https://gstreamer.freedesktop.org/src/gst-plugins-base/gst-plugins-base-1.14.2.tar.xz')
    headers=B/'gst-public-headers';(headers/'gst').mkdir(parents=True,exist_ok=True)
    values={'GSTCONFIG_BUILT_WITH_MSVC':'0','GST_VERSION_MAJOR':'1','GST_VERSION_MINOR':'14','GST_VERSION_MICRO':'2','GST_VERSION_NANO':'0'}
    # Public header configuration only. Target has all four probed subsystems
    # enabled; target GLib's real glibconfig.h supplies ARM ABI definitions.
    for name in ['gstconfig.h','gstversion.h']:
        text=(core/'gst'/(name+'.in')).read_text()
        text=re.sub(r'@([A-Z0-9_]+)@',lambda m:values.get(m[1],'') if m[1].endswith('_DEFINE') or m[1] in values else m[0],text)
        if re.search(r'@[A-Z0-9_]+@',text):raise ValueError('Unresolved header configuration')
        (headers/'gst'/name).write_text(text)
    enum=subprocess.check_output(['glib-mkenums','--template',str(core/'gst/gstenumtypes.h.template'),*map(str,sorted((core/'gst').glob('*.h')))],text=True)
    (headers/'gst/gstenumtypes.h').write_text(enum)
    (headers/'gst/video').mkdir(exist_ok=True)
    video=base/'gst-libs/gst/video'
    run(['python3',video/'video_mkenum.py','glib-mkenums',headers/'gst/video/video-enumtypes.h',*sorted(video.glob('*.h'))])
    vendor=pathlib.Path('/src/private-gst-linksysroot/usr')
    includes=[headers,core,core/'libs',base/'gst-libs',vendor/'include/glib-2.0',vendor/'lib/glib-2.0/include',P/'include',pathlib.Path('/src/wiliwili/library/borealis/library/include/borealis/extern')]
    libs=[vendor/'lib'/p for p in ['libgstvideo-1.0.so.0.1402.0','libgstapp-1.0.so.0.1402.0','libgstbase-1.0.so.0.1402.0','libgstreamer-1.0.so.0.1402.0','libgobject-2.0.so.0.5400.3','libglib-2.0.so.0.5400.3']]
    run([TRIPLE+'-g++','-O2','-mfpu=neon','-std=c++17','-pthread',*(['-DP011_BUNDLED_OMX=1'] if bundled else []),
         *(['-DP011_OUTPUT_CACHE_PROBE=1','-DP011_CACHE_WORKER=1','-rdynamic'] if cache_probe else []),
         *(['-DP011_BUNDLED_OUTPUT_CACHE=1','-rdynamic'] if cached_output else []),*['-I'+str(i) for i in includes],
         '/src/client/hardware_worker.cpp',*(['/src/probes/memion_cache.cpp'] if cache_probe or cached_output else []),
         *libs,*(['-ldl'] if cache_probe or cached_output else []),'-Wl,--allow-shlib-undefined','-o',str(output)])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundled-omx',action='store_true')
    parser.add_argument('--cached-output',action='store_true');args=parser.parse_args()
    main(bundled=args.bundled_omx,cached_output=args.cached_output)
