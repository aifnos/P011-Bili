// SPDX-License-Identifier: GPL-3.0-or-later
// Worker-only gate: read fixed vendor files; never change the system or cache
// flags based on a playback request, filename, or inherited environment.
#pragma once
#include <glib.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <initializer_list>
#include <regex>
#include <string>

namespace p011_hw {
inline std::string cache_bundle_plugin(){
    char path[4096];ssize_t length=readlink("/proc/self/exe",path,sizeof(path)-1);
    if(length<=0||length==ssize_t(sizeof(path)-1))return {};path[length]=0;
    std::string exe=path;
    if(!std::regex_match(exe,std::regex("(?:/mnt/data/p011-toolbox/bili-media/[a-f0-9]{16}|/mnt/data/p011-toolbox/bili-formal/releases/[a-f0-9]{24}/media|/opt/p011-bili/releases/[a-f0-9]{24}/media)/bin/bili-hw")))return {};
    auto root=exe.substr(0,exe.size()-strlen("/bin/bili-hw"));
    auto plugin=root+"/lib/gst/libgstomx.so";struct stat info{};
    if(lstat(plugin.c_str(),&info)||!S_ISREG(info.st_mode)||info.st_uid!=getuid())return {};
    const char*loaded=getenv("GST_PLUGIN_PATH_1_0");
    if(!loaded||root+"/lib/gst"!=loaded)return {};
    return plugin;
}
inline bool cache_vendor_file(const char*path,const char*sha){
    int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return false;
    struct stat before{},after{};bool ok=fstat(fd,&before)==0&&S_ISREG(before.st_mode)&&before.st_uid==0&&
        before.st_size>0&&before.st_size<=16*1024*1024;
    GChecksum*sum=g_checksum_new(G_CHECKSUM_SHA256);if(!sum)ok=false;
    char buffer[16384];off_t total=0;
    while(ok){
        ssize_t count=::read(fd,buffer,sizeof(buffer));if(count<0&&errno==EINTR)continue;
        if(count<0){ok=false;break;}if(!count)break;
        total+=count;if(total>before.st_size){ok=false;break;}
        g_checksum_update(sum,reinterpret_cast<const guchar*>(buffer),count);
    }
    ok=ok&&total==before.st_size&&fstat(fd,&after)==0&&before.st_dev==after.st_dev&&before.st_ino==after.st_ino&&
        before.st_size==after.st_size&&before.st_mtime==after.st_mtime&&before.st_ctime==after.st_ctime&&
        !strcmp(g_checksum_get_string(sum),sha);
    if(sum)g_checksum_free(sum);close(fd);return ok;
}
inline bool cache_vendor_verified(){
    struct Pin{const char*path;const char*sha;};
    for(const auto&pin:{Pin{"/usr/lib/libsprd_omx_core.so","bcf76bb48a53aa270ea0d901f0c1db10e2c3d9bc0289bfbe93c4ed302059428b"},
        Pin{"/usr/lib/libstagefright_sprd_h264dec.so","31435b48a7aaa48db9639ced66aca3519b55eafe717a97be4eea77b9b6d2dfc4"},
        Pin{"/usr/lib/libomx_avcdec_hw_sprd.so","10f78010d85ec6d93fce94e7ddf05fc9a783237aa59dff8bda2df7077badbe14"},
        Pin{"/usr/lib/libmemion.so","d19e0083e03c1c72a145af569eeb52af7dab558194ae39ebddf0112aceeb6628"}})
        if(!cache_vendor_file(pin.path,pin.sha))return false;
    return true;
}
}
