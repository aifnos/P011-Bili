"""Build the no-window driver only. Never runs ADB or starts a service."""
import hashlib,json,pathlib,sys
from build_deps import TRIPLE,run
sys.path.insert(0,'/src/host')
from hardware_seek_trial import probe_sources

base=pathlib.Path('/src');before=probe_sources(base)
target=base/'out/hardware-seek-probe'
run([TRIPLE+'-g++','-O2','-std=c++17','-pthread','-DP011_PRIVATE_OMX_PROBE=1',
     '-I/src/wiliwili/library/borealis/library/include/borealis/extern',
     str(base/'probes/hardware_seek_probe.cpp'),'-o',str(target)])
if before!=probe_sources(base):raise ValueError('Probe inputs changed during build')
(base/'out/hardware-seek-probe.build.json').write_text(json.dumps({
    'schema':1,'sources':before,'binary_sha256':hashlib.sha256(target.read_bytes()).hexdigest()},indent=2))
print('NO_WINDOW_PROBE_BUILT')
