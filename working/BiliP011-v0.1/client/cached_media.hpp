// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdlib>
#include <regex>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
namespace p011_media {
// Only the service-created capability endpoint, never arbitrary localhost.
inline bool relay_url(const std::string&url){
    const char*r=getenv("P011_MEDIA_RELAY");if(!r)return false;std::string prefix=r;
    return std::regex_match(prefix,std::regex("http://127\\.0\\.0\\.1:[0-9]{1,5}/[a-f0-9]{48}/"))&&
        url.rfind(prefix,0)==0&&std::regex_match(url.substr(prefix.size()),std::regex("[a-f0-9]{16}-[va]"));
}
// Only our private, complete, owner-only cache files may enter a player.
// This does not enable arbitrary file:// URLs from a page or API response.
inline std::string cached_path(const std::string&url){
    const char*r=getenv("P011_CLIENT_ROOT");if(!r||*r!='/')return {};
    std::string dir=std::string(r)+"/preload",prefix="file://"+dir+"/";
    if(url.rfind(prefix,0)!=0)return {};
    std::string name=url.substr(prefix.size());
    if(!std::regex_match(name,std::regex("[a-f0-9]{16}-[va]\\.m4s")))return {};
    struct stat ds{},fs{};std::string path=dir+"/"+name;
    if(lstat(dir.c_str(),&ds)||!S_ISDIR(ds.st_mode)||ds.st_uid!=geteuid()||(ds.st_mode&0077)||
       lstat(path.c_str(),&fs)||!S_ISREG(fs.st_mode)||fs.st_uid!=geteuid()||(fs.st_mode&0077)||fs.st_nlink!=1||fs.st_size<=0||fs.st_size>8*1024*1024)return {};
    return path;
}
}
