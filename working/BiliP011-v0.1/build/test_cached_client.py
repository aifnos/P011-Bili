"""PC-only sanitizer check of final cache-report draining during close."""
import pathlib,subprocess,sys
from build_deps import B,run
work=B/'cache-close-mock';work.mkdir(exist_ok=True)
common=['g++','-std=c++17','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I/src/wiliwili/library/borealis/library/include/borealis/extern']
if '--bundled' in sys.argv:common+=['-DP011_MOCK_CACHE_BUNDLE=1']
source='/src/host/hardware_cache_close_test.cpp'
run(common+['-DP011_MOCK_CACHE_WORKER=1',source,'-o',work/'bili-hw'])
run(common+[source,'-o',work/'cache-close-driver'])
subprocess.run([work/'cache-close-driver'],check=True,timeout=12)
