"""PC-only sanitizer tests of enabled and conservative fallback allocation."""
import os,subprocess,sys
if sys.platform!='linux':raise RuntimeError('Run this check inside the existing Linux build container')
from build_deps import B,run

work=B/'output-cache-mock';work.mkdir(exist_ok=True)
common=['g++','-std=c++17','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer']
mock='/src/host/cache_bridge_mock.cpp'
run(common+['-fPIC','-shared','-DP011_MOCK_LIBRARY=1',mock,'-o',work/'libmemion.so'])
run(common+['-DP011_CACHE_MOCK=1','-DP011_BUNDLED_OUTPUT_CACHE=1','-rdynamic',
    '/src/host/output_cache_mock.cpp','/src/probes/memion_cache.cpp','-pthread','-ldl','-o',work/'output-cache-mock'])
env=dict(os.environ,LD_LIBRARY_PATH=str(work))
subprocess.run([work/'output-cache-mock'],env=env,check=True,timeout=10)
subprocess.run([work/'output-cache-mock','disabled'],env=env,check=True,timeout=10)
# A changed vendor without the old getters must still use its original map.
unknown=work/'without-getters';unknown.mkdir(exist_ok=True)
run(common+['-fPIC','-shared','-DP011_MOCK_LIBRARY=1','-DP011_MOCK_NO_GETTERS=1',mock,'-o',unknown/'libmemion.so'])
subprocess.run([work/'output-cache-mock','disabled'],env=dict(env,LD_LIBRARY_PATH=str(unknown)),check=True,timeout=10)
run(common+['-DP011_CACHE_MOCK=1','-rdynamic',mock,'/src/probes/memion_cache.cpp','-pthread','-ldl','-o',work/'strict-cache-mock'])
subprocess.run([work/'strict-cache-mock'],env=env,check=True,timeout=10)
