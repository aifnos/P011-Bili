"""Private ARMv7 dependencies; runs only in our PC builder container."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request

W = pathlib.Path('/work/p011')
P = W / 'prefix'
S = W / 'sources'
B = W / 'build'
for d in (S, B, W / 'downloads', W / 'stamps'):
    d.mkdir(parents=True, exist_ok=True)
TRIPLE = 'arm-buildroot-linux-gnueabihf'
ENV = dict(os.environ, CC=TRIPLE+'-gcc', CXX=TRIPLE+'-g++', AR=TRIPLE+'-ar', RANLIB=TRIPLE+'-ranlib', STRIP=TRIPLE+'-strip',
           PKG_CONFIG='/usr/bin/pkg-config', PKG_CONFIG_LIBDIR=str(P/'lib/pkgconfig'), PKG_CONFIG_PATH='',
           CFLAGS='-O2 -fPIC -march=armv7-a -mfpu=neon -mfloat-abi=hard',
           CXXFLAGS='-O2 -fPIC -march=armv7-a -mfpu=neon -mfloat-abi=hard',
           CPPFLAGS='-I'+str(P/'include'), LDFLAGS='-L'+str(P/'lib')+' -Wl,-rpath-link,'+str(P/'lib')+' -Wl,--allow-shlib-undefined')
JOBS = '8'


def run(args, cwd=None, env=None):
    print('RUN', ' '.join(map(str,args)), flush=True)
    subprocess.run(list(map(str,args)), cwd=cwd, env=env or ENV, check=True)


def source(name, url):
    archive = W/'downloads'/(name+'.tar')
    if not archive.exists():
        run(['curl','--fail','--location','--retry','2','--connect-timeout','15','--max-time','180','--output',str(archive)+'.part',url])
        pathlib.Path(str(archive)+'.part').rename(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    lockfile = W/'sources-lock.json'
    lock = json.loads(lockfile.read_text()) if lockfile.exists() else {}
    entry = {'url': url, 'sha256': digest}
    if name in lock and lock[name] != entry:
        raise ValueError('Existing source identity changed: '+name)
    lock[name] = entry
    lockfile.write_text(json.dumps(lock, indent=2))
    root = S/name
    if not root.exists():
        # Each download has one top-level directory. Reject escaping member paths;
        # Python's data filter additionally rejects escaping symlink/hardlink targets.
        temp = S/(name+'.extract')
        temp.mkdir(exist_ok=False)
        with tarfile.open(archive) as bundle:
            bundle.extractall(temp, filter='data')
        children = list(temp.iterdir())
        if len(children) != 1 or not children[0].is_dir():
            raise ValueError('Unexpected source layout')
        children[0].rename(root)
        temp.rmdir()
    return root


def cmake(name, path, options):
    target=B/name
    run(['cmake','-S',path,'-B',target,'-G','Ninja','-DCMAKE_TOOLCHAIN_FILE=/src/build/armv7.cmake',
         '-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=ON',*options])
    run(['cmake','--build',target,'-j',JOBS])
    run(['cmake','--install',target])


def meson(name, path, options):
    target=B/name
    if not (target/'build.ninja').exists():
        run(['meson','setup',target,path,'--cross-file=/src/build/armv7.ini','--auto-features=disabled',*options])
    run(['ninja','-C',target,'-j',JOBS])
    run(['ninja','-C',target,'install'])


def step(name, task):
    stamp=W/'stamps'/name
    if stamp.exists():
        print('CACHED',name,flush=True);return
    task()
    stamp.write_text('built\n')


def openssl():
    src=source('openssl-3.5.8','https://github.com/openssl/openssl/releases/download/openssl-3.5.8/openssl-3.5.8.tar.gz')
    target=B/'openssl';target.mkdir(exist_ok=True)
    run([src/'Configure','linux-armv4','--prefix='+str(P),'--libdir=lib','--openssldir=/etc/ssl','shared','no-tests','no-apps','no-docs','no-legacy','no-comp','no-module'],cwd=target)
    run(['make','-j'+JOBS],cwd=target)
    run(['make','install_sw'],cwd=target)


def dav1d():
    meson('dav1d-1.5.3',source('dav1d-1.5.3','https://github.com/videolan/dav1d/archive/refs/tags/1.5.3.tar.gz'),
          ['-Denable_tools=false','-Denable_tests=false','-Denable_examples=false','-Denable_docs=false'])


def ffmpeg():
    src=source('ffmpeg-6.1.6','https://ffmpeg.org/releases/ffmpeg-6.1.6.tar.xz')
    target=B/'ffmpeg-codecs';target.mkdir(exist_ok=True)
    run([src/'configure','--prefix='+str(P),'--cross-prefix='+TRIPLE+'-','--arch=arm','--cpu=cortex-a7','--target-os=linux',
         '--enable-cross-compile','--enable-shared','--disable-static','--enable-pic','--disable-debug','--disable-doc',
         '--disable-programs','--disable-autodetect','--disable-everything','--enable-network','--enable-openssl','--enable-libdav1d',
         '--enable-protocol=file,http,https,tcp,tls,crypto,data','--enable-demuxer=mov,matroska,hls,mpegts,aac,mp3,ogg,flac,wav',
         '--enable-decoder=h264,hevc,libdav1d,aac,aac_latm,mp3,mp3float,opus,vorbis,flac,pcm_s16le,pcm_f32le,mjpeg,png',
         '--enable-parser=h264,hevc,av1,aac,aac_latm,mpegaudio,opus,vorbis,flac',
         '--enable-filter=aresample,aformat,anull,volume,atempo,format,scale,null',
         '--enable-bsf=aac_adtstoasc,h264_mp4toannexb,extract_extradata',
         '--enable-muxer=null,mp4,matroska,wav,pcm_s16le','--enable-encoder=pcm_s16le,png,mjpeg',
         '--extra-cflags=-I'+str(P/'include')+' -mfpu=neon -mfloat-abi=hard',
         '--extra-ldflags=-L'+str(P/'lib')+' -Wl,-rpath-link,'+str(P/'lib'),'--pkg-config=/usr/bin/pkg-config'],cwd=target)
    run(['make','-j'+JOBS],cwd=target)
    run(['make','install'],cwd=target)


def libass():
    src=source('libass-0.17.5','https://github.com/libass/libass/releases/download/0.17.5/libass-0.17.5.tar.xz')
    target=B/'libass';target.mkdir(exist_ok=True)
    run([src/'configure','--host='+TRIPLE,'--prefix='+str(P),'--disable-static','--enable-shared','--disable-fontconfig','--disable-require-system-font-provider','--disable-asm'],cwd=target)
    run(['make','-j'+JOBS],cwd=target);run(['make','install'],cwd=target)


def curl():
    src=source('curl-8.22.0','https://curl.se/download/curl-8.22.0.tar.xz')
    target=B/'curl';target.mkdir(exist_ok=True)
    run([src/'configure','--host='+TRIPLE,'--prefix='+str(P),'--disable-static','--enable-shared',
         '--with-openssl='+str(P),'--with-ca-bundle=/etc/ssl/certs/ca-certificates.crt',
         '--without-libpsl','--without-zstd','--without-brotli','--without-libidn2','--without-nghttp2',
         '--without-zlib','--without-libssh2','--without-libssh','--without-ldap','--disable-ldap','--disable-ldaps',
         '--enable-threaded-resolver','--disable-docs','--disable-manual'],cwd=target)
    run(['make','-j'+JOBS],cwd=target);run(['make','install'],cwd=target)


def main():
    run(['python3','/src/build/setup_prefix.py'])
    tasks = {
        'openssl': openssl,
        'freetype': lambda:cmake('freetype',source('freetype-2.13.3','https://github.com/freetype/freetype/archive/refs/tags/VER-2-13-3.tar.gz'),['-DFT_DISABLE_ZLIB=ON','-DFT_DISABLE_BZIP2=ON','-DFT_DISABLE_PNG=ON','-DFT_DISABLE_HARFBUZZ=ON','-DFT_DISABLE_BROTLI=ON']),
        'harfbuzz': lambda:meson('harfbuzz',source('harfbuzz-8.5.0','https://github.com/harfbuzz/harfbuzz/releases/download/8.5.0/harfbuzz-8.5.0.tar.xz'),['-Dfreetype=enabled','-Dtests=disabled','-Ddocs=disabled','-Dutilities=disabled']),
        'fribidi': lambda:meson('fribidi',source('fribidi-1.0.17','https://github.com/fribidi/fribidi/releases/download/v1.0.17/fribidi-1.0.17.tar.xz'),['-Dtests=false','-Ddocs=false','-Dbin=false']),
        'libass': libass,
        'dav1d': dav1d,
        'ffmpeg-codecs-v1': ffmpeg,
        'curl': curl,
        # The embedded renderer receives GL functions/context from SDL. Do not
        # enable mpv's separate EGL window backend: it requires EGL > 1.4,
        # whereas the vendor EGL reports 1.4. No version spoofing is needed.
        'mpv': lambda:meson('mpv',source('mpv-0.36.0','https://github.com/mpv-player/mpv/archive/refs/tags/v0.36.0.tar.gz'),['-Dlibmpv=true','-Dcplayer=true','-Dgl=enabled','-Dplain-gl=enabled','-Degl=disabled','-Dpulse=enabled','-Dlua=disabled','-Dlibplacebo=disabled','-Dmanpage-build=disabled']),
    }
    selected=sys.argv[1:] or list(tasks)
    for name in selected:step(name,tasks[name])
    print('PRIVATE_DEPS_BUILD_COMPLETE',flush=True)


if __name__=='__main__':main()
