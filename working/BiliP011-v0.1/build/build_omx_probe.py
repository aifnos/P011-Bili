"""PC-only pair of private gst-omx output-copy probes. Never invokes ADB."""
import argparse,hashlib,json,pathlib,subprocess,sys
from build_deps import B,S,TRIPLE,run
sys.path.insert(0,'/src/host')
from private_omx_artifact import source_hashes

base=pathlib.Path('/src');before=source_hashes(base)
parser=argparse.ArgumentParser();parser.add_argument('--mode',type=int,choices=(0,1,2,3,4),action='append')
modes=parser.parse_args().mode or (0,1,2,3)
if len(set(modes))!=len(modes):raise ValueError('Duplicate private copy mode')
src=base/'third_party/gst-omx-1.14.2-p011';vendor=base/'private-gst-linksysroot/usr'
core=S/'gstreamer-1.14.2';plugins=S/'gst-plugins-base-1.14.2'
generated=B/'gst-public-headers';work=B/'omx-copy-probe';work.mkdir(exist_ok=True)
# Release public enum headers are build-generated, never invented ABI structs.
for name in ('audio','pbutils'):
    folder=plugins/'gst-libs/gst'/name;target=generated/'gst'/name;target.mkdir(parents=True,exist_ok=True)
    run(['python3',folder/(name+'_mkenum.py'),'glib-mkenums',target/(name+'-enumtypes.h'),*sorted(folder.glob('*.h'))])
config='''#define PACKAGE "gst-omx"
#define PACKAGE_VERSION "1.14.2"
#define GST_LICENSE "LGPL"
#define GST_PACKAGE_NAME "P011 private output-copy experiment"
#define GST_PACKAGE_ORIGIN "https://gstreamer.freedesktop.org/"
#define GST_OMX_CONFIG_DIR "/etc/xdg"
#define GST_USE_UNSTABLE_API 1
#define HAVE_STDINT_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_UNISTD_H 1
'''
(work/'config.h').write_text(config)
includes=[work,generated,core,core/'libs',plugins/'gst-libs',src/'omx/openmax',vendor/'include/glib-2.0',vendor/'lib/glib-2.0/include']
names=['gstomx','gstomxbufferpool','gstomxvideo','gstomxvideodec','gstomxvideoenc','gstomxaudiodec','gstomxaudioenc','gstomxmjpegdec','gstomxmpeg4videodec','gstomxmpeg2videodec','gstomxh264dec','gstomxh264utils','gstomxh263dec','gstomxwmvdec','gstomxmpeg4videoenc','gstomxh264enc','gstomxh263enc','gstomxaacdec','gstomxmp3dec','gstomxmp3enc','gstomxaacenc','gstomxamrdec','gstomxaudiosink','gstomxanalogaudiosink','gstomxhdmiaudiosink']
stems=['gstaudio-1.0','gstpbutils-1.0','gstvideo-1.0','gstbase-1.0','gstallocators-1.0','gstreamer-1.0','gobject-2.0','gmodule-2.0','glib-2.0']
libs=[]
for stem in stems:
    found=list((vendor/'lib').glob('lib'+stem+'.so.*'))
    if len(found)!=1:raise ValueError('Ambiguous link ABI: '+stem)
    libs+=found
host_test=work/'parallel-host-test'
for extra in ([],['-DP011_OMX_THREE_COPY=1']):
    run(['/usr/bin/gcc','-O1','-g','-std=gnu99','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer','-DP011_OMX_PARALLEL_COPY=1',*extra,base/'host/omx_parallel_test.c','-o',host_test])
    subprocess.run([host_test],check=True,timeout=30)
run(['/usr/bin/g++','-O1','-g','-std=gnu++17','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer',
     '-DP011_OMX_PARALLEL_COPY=1',base/'host/omx_half_test.cpp','-o',host_test])
subprocess.run([host_test],check=True,timeout=30)
for mode in modes:
    neon=mode==1
    target=work/('libgstomx-mode'+str(mode)+'.so')
    cmd=[TRIPLE+'-gcc','-O2','-std=gnu99','-mfpu=neon','-fPIC','-shared','-pthread','-DHAVE_CONFIG_H=1']
    if neon:cmd+=['-DP011_OMX_NEON_COPY=1']
    if mode in (2,3,4):cmd+=['-DP011_OMX_PARALLEL_COPY=1']
    if mode==3:cmd+=['-DP011_OMX_THREE_COPY=1']
    if mode==4:cmd+=['-DP011_OMX_FUSED_HALF=1']
    run(cmd+['-I'+str(p) for p in includes]+[src/'omx'/(name+'.c') for name in names]+libs+['-Wl,--allow-shlib-undefined','-Wl,-soname,libgstomx.so','-o',target])
    if source_hashes(base)!=before:raise ValueError('Private OMX sources changed during build')
    raw=target.read_bytes();digest=hashlib.sha256(raw).hexdigest();out=base/'out'/('omx-probe-'+digest[:16])
    meta={'schema':4,'copy_mode':mode,'neon':neon,'fused_half':mode==4,'sha256':digest,'sources':before,'config':config,'host_sanitizer_checks':38056,'half_sanitizer_checks':2350,'device_tested':False,'vendor_binaries_included':False}
    if out.exists():
        if (out/'libgstomx.so').read_bytes()!=raw or json.loads((out/'build.json').read_text())!=meta:raise ValueError('Immutable OMX identity collision')
    else:
        out.mkdir(exist_ok=False);(out/'libgstomx.so').write_bytes(raw)
        (out/'build.json').write_text(json.dumps(meta,indent=2))
    print('PRIVATE_OMX='+str(out),flush=True)
