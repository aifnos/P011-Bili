"""Generate v1 bindings with the already built Wayland 1.14 host scanner.

No newer Wayland runtime is built or shipped. XML retains its upstream license.
"""
from pathlib import Path
from build_deps import W,S,TRIPLE,run

def prepare():
    work=W/'build/presentation-v1';work.mkdir(exist_ok=True)
    source=S/'wayland-1.14.0'
    scanner=W/'build/wayland-1.14-scanner-host-v1/wayland-scanner'
    xml=Path('/src/third_party/presentation-time-v1.xml')
    run([scanner,'client-header',source/'protocol/wayland.xml',work/'wayland-client-protocol.h'])
    run([scanner,'client-header',xml,work/'presentation-time-client-protocol.h'])
    run([scanner,'code',xml,work/'presentation-time-protocol.c'])
    flags=['-I'+str(work),'-I'+str(source/'src')]
    obj=work/'presentation-time-protocol.o'
    run([TRIPLE+'-gcc','-O2','-fPIC',*flags,'-c',work/'presentation-time-protocol.c','-o',obj])
    return flags+[str(obj),'-lwayland-client']
