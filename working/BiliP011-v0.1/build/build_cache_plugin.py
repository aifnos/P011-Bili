"""Shared source-only private OMX build, strict probe or bundle fallback."""
import hashlib,pathlib
from build_deps import B,S,TRIPLE,run
from cache_omx_overlay import overlay

def build_plugin(work,fallback=False):
    base=pathlib.Path('/src');work.mkdir(exist_ok=True)
    src=base/'third_party/gst-omx-1.14.2-p011';vendor=base/'private-gst-linksysroot/usr'
    core=S/'gstreamer-1.14.2';plugins=S/'gst-plugins-base-1.14.2';generated=B/'gst-public-headers'
    config='''#define PACKAGE "gst-omx"
#define PACKAGE_VERSION "1.14.2"
#define GST_LICENSE "LGPL"
#define GST_PACKAGE_NAME "P011 private cache experiment"
#define GST_PACKAGE_ORIGIN "https://gstreamer.freedesktop.org/"
#define GST_OMX_CONFIG_DIR "/etc/xdg"
#define GST_USE_UNSTABLE_API 1
#define HAVE_STDINT_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_UNISTD_H 1
'''
    (work/'config.h').write_text(config)
    modified={}
    for name in ('gstomx.c','gstomxvideodec.c'):
        text=overlay(name,(src/'omx'/name).read_text(encoding='utf-8'),fallback=fallback)
        (work/name).write_bytes(text.encode('utf-8'));modified[name]=hashlib.sha256(text.encode('utf-8')).hexdigest()
    includes=[work,base/'probes',src/'omx',generated,core,core/'libs',plugins/'gst-libs',src/'omx/openmax',vendor/'include/glib-2.0',vendor/'lib/glib-2.0/include']
    names=['gstomx','gstomxbufferpool','gstomxvideo','gstomxvideodec','gstomxvideoenc','gstomxaudiodec','gstomxaudioenc','gstomxmjpegdec','gstomxmpeg4videodec','gstomxmpeg2videodec','gstomxh264dec','gstomxh264utils','gstomxh263dec','gstomxwmvdec','gstomxmpeg4videoenc','gstomxh264enc','gstomxh263enc','gstomxaacdec','gstomxmp3dec','gstomxmp3enc','gstomxaacenc','gstomxamrdec','gstomxaudiosink','gstomxanalogaudiosink','gstomxhdmiaudiosink']
    stems=['gstaudio-1.0','gstpbutils-1.0','gstvideo-1.0','gstbase-1.0','gstallocators-1.0','gstreamer-1.0','gobject-2.0','gmodule-2.0','glib-2.0']
    libs=[]
    for stem in stems:
        found=list((vendor/'lib').glob('lib'+stem+'.so.*'))
        if len(found)!=1:raise ValueError('Ambiguous target ABI library')
        libs+=found
    plugin=work/'libgstomx.so'
    run([TRIPLE+'-gcc','-O2','-std=gnu99','-mfpu=neon','-fPIC','-shared','-pthread','-DHAVE_CONFIG_H=1',
         '-DP011_OMX_PARALLEL_COPY=1','-DP011_OMX_FUSED_HALF=1',*['-I'+str(x) for x in includes],
         *[(work if name+'.c' in modified else src/'omx')/(name+'.c') for name in names],*libs,
         '-Wl,--allow-shlib-undefined','-Wl,-soname,libgstomx.so','-o',plugin])
    return plugin,modified,includes,libs
