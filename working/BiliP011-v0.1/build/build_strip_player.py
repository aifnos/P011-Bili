"""Existing PC builder only. Build/test an isolated strip player; no ADB."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from build_deps import run,W
sys.path.insert(0,'/src/host')
from private_sdl_artifact import validate_private_artifact
from strip_player_artifact import source_hashes

base=Path('/src')
_,_,runtime,runtime_sha,_=validate_private_artifact(base)
sources=source_hashes(base)
omx=None
cached_output='--cached-output' in sys.argv
if '--private-omx' in sys.argv:
    if cached_output:
        from output_cache_artifact import validate
    else:
        from private_omx_artifact import validate
    omx_path=Path(sys.argv[sys.argv.index('--private-omx')+1]).resolve()
    _,omx=validate(base,omx_path)
    if omx['copy_mode'] not in (2,3,4):raise ValueError('Only the bounded parallel copy candidate may be integrated')
    if (omx['copy_mode']==4)!=('--fused-copy' in sys.argv):raise ValueError('Fused copy requires an explicit matching build option')
elif '--fused-copy' in sys.argv:raise ValueError('Fused copy requires private OMX')
if cached_output and not omx:raise ValueError('Output cache requires a verified matching OMX')
if cached_output:
    run(['python3',base/'build/test_cache_vendor_gate.py'])
    run(['python3',base/'build/test_cached_client.py','--bundled'])
tests={}
for name in ('media_range','player_geometry','player_surface','player_controls','player_phase','player_packets','player_features','danmaku_timeline','hardware_clock','h264_access_unit'):
    binary=W/'build'/(name+'-strip-host-test')
    sanitizer=['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if name in ('media_range','h264_access_unit','player_controls','player_phase','player_packets','danmaku_timeline') else []
    run(['/usr/bin/g++','-O2','-std=c++17','-pthread',*sanitizer,
         '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
         base/'host'/(name+'_test.cpp'),'-o',binary])
    result=subprocess.run([binary],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True)
    tests[name]={'stdout':result.stdout.decode('utf-8'),'exit':result.returncode}
run(['python3',base/'build/build_client.py','--enhanced','--graphics-trace','--strip-window','--display-first']+(['--bundled-omx'] if omx else [])+(['--cached-output'] if cached_output else [])+(['--presentation-feedback'] if '--presentation-feedback' in sys.argv else []))
run(['python3',base/'build/build_hardware.py']+(['--bundled-omx'] if omx else [])+(['--cached-output'] if cached_output else []))
if sources!=source_hashes(base):raise ValueError('Player sources changed during build')
validate_private_artifact(base)
meta={'schema':1,'sources':sources,'sdl_sha256':runtime_sha,'host_tests':tests,
      'presentation_feedback': '--presentation-feedback' in sys.argv,
      'binaries':{name:hashlib.sha256((base/'out'/name).read_bytes()).hexdigest()
                  for name in ('bili-player','bili-api','bili-hw')}}
if omx:
    _,after=validate(base,omx_path)
    if after!=omx:raise ValueError('Bundled OMX changed during build')
    meta['bundled_omx']={'artifact':omx_path.name,'sha256':omx['sha256'],'fused_copy':omx['copy_mode']==4}
    if cached_output:meta['bundled_omx']['output_cache']=True
(base/'out/strip-player.build.json').write_text(json.dumps(meta,indent=2))
run(['python3',base/'build/export_runtime.py','--client','--hardware','--private-sdl']+(['--private-omx'] if omx else []))
