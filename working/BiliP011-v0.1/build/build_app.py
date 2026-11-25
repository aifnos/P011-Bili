"""Compile, but never launch/install, the isolated ARMv7 client candidate."""
from build_deps import run, B

target=B/'wiliwili'
run(['cmake','-S','/src/wiliwili','-B',target,'-G','Ninja',
     '-DCMAKE_TOOLCHAIN_FILE=/src/build/armv7.cmake','-DCMAKE_BUILD_TYPE=Release',
     '-DPLATFORM_DESKTOP=ON','-DP011=ON','-DUSE_SDL2=ON','-DUSE_SYSTEM_SDL2=ON',
     '-DUSE_GLES2=ON','-DUSE_EGL=ON','-DUSE_SYSTEM_CURL=ON','-DUSE_LIBROMFS=OFF',
     '-DDISABLE_OPENCC=ON','-DDISABLE_WEBP=ON','-DANALYTICS=OFF','-DCUSTOM_RESOURCES_DIR=resources'])
run(['cmake','--build',target,'--target','wiliwili','-j','8'])
