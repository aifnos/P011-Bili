"""PC-only checks of the exact bounded read/hash function used by the worker."""
import os,subprocess,sys
if sys.platform!='linux':raise RuntimeError('Run this check inside the existing Linux build container')
from build_deps import B,run
# build_deps.run intentionally gives child scripts ARM pkg-config variables;
# this sanitizer executable is x86-64 and must use the HOST development ABI.
host_env={k:v for k,v in os.environ.items() if not k.startswith('PKG_CONFIG')}
host_env['PKG_CONFIG_LIBDIR']='/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig'
flags=subprocess.check_output(['/usr/bin/pkg-config','--cflags','--libs','glib-2.0'],env=host_env,text=True).split()
binary=B/'hardware-cache-gate-test'
run(['/usr/bin/g++','-std=c++17','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
     '/src/host/hardware_cache_gate_test.cpp',*flags,'-o',binary])
subprocess.run([binary],check=True,timeout=10)
