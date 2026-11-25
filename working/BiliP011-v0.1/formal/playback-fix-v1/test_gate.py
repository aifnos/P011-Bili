"""Execute the actual C++ bundle gate using bounded host syscall fixtures."""
from pathlib import Path
import subprocess

out = Path('/output/gate-test')
out.mkdir()
(out/'glib.h').write_text('''#pragma once
#include <stddef.h>
typedef unsigned char guchar; struct GChecksum; enum {G_CHECKSUM_SHA256=2};
extern GChecksum*g_checksum_new(int);
extern void g_checksum_update(GChecksum*,const guchar*,size_t);
extern const char*g_checksum_get_string(GChecksum*);
extern void g_checksum_free(GChecksum*);
''')
source = r'''
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstring>
#include <cstdlib>
#include <string>
#include <cassert>
static std::string exe, plugin_env; static bool exists=true, regular=true, owned=true;
static ssize_t fake_readlink(const char*p,char*b,size_t n){
    assert(std::string(p)=="/proc/self/exe");
    size_t size=std::min(n,exe.size());memcpy(b,exe.data(),size);return size;
}
static int fake_lstat(const char*p,struct stat*s){
    if(!exists)return -1;
    assert(std::string(p)==exe.substr(0,exe.size()-strlen("/bin/bili-hw"))+"/lib/gst/libgstomx.so");
    s->st_mode=regular?S_IFREG:S_IFLNK;s->st_uid=owned?getuid():getuid()+1;return 0;
}
static char*fake_getenv(const char*p){assert(std::string(p)=="GST_PLUGIN_PATH_1_0");return plugin_env.empty()?nullptr:&plugin_env[0];}
#define readlink fake_readlink
#define lstat fake_lstat
#define getenv fake_getenv
#include "/src/formal/playback-fix-v1/native/client/hardware_cache_gate.hpp"
#undef readlink
#undef lstat
#undef getenv
static void setup(const std::string&p){exe=p;plugin_env=p.substr(0,p.size()-strlen("/bin/bili-hw"))+"/lib/gst";}
int main(){
    const std::string a(24,'a'), b(16,'b');int checks=0;
    for(const auto&root:{"/mnt/data/p011-toolbox/bili-media/"+b,
        "/mnt/data/p011-toolbox/bili-formal/releases/"+a+"/media",
        "/opt/p011-bili/releases/"+a+"/media"}){
        setup(root+"/bin/bili-hw");assert(p011_hw::cache_bundle_plugin()==root+"/lib/gst/libgstomx.so");checks++;
        for(int mode=0;mode<4;mode++){
            exists=mode!=0;regular=mode!=1;owned=mode!=2;
            auto old=plugin_env;if(mode==3)plugin_env="/tmp/arbitrary";
            assert(p011_hw::cache_bundle_plugin().empty());checks++;plugin_env=old;
        }
        exists=regular=owned=true;
    }
    for(const auto&path:{std::string("/tmp/bili-hw"), "/opt/p011-bili/releases/"+a+"/bin/bili-hw",
        "/mnt/data/p011-toolbox/bili-formal/releases/"+b+"/media/bin/bili-hw",
        "/mnt/data/p011-toolbox/bili-formal/releases/"+a+"/media/bin/bili-hw.evil",
        "/mnt/data/p011-toolbox/bili-formal/releases/"+a+"/../media/bin/bili-hw",
        "/opt/p011-bili/releases/"+std::string(24,'A')+"/media/bin/bili-hw",
        "/opt/p011-bili/releases/"+a+"/media/bin/bili-hw (deleted)"}){
        setup(path);assert(p011_hw::cache_bundle_plugin().empty());checks++;
    }
    printf("actual_gate_checks=%d\n",checks);
}
'''
(out/'gate.cpp').write_text(source)
subprocess.run(['g++','-O2','-std=c++17','-I'+str(out),str(out/'gate.cpp'),'-o',str(out/'gate')],check=True)
subprocess.run([str(out/'gate')],check=True)
