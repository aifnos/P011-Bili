// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <fcntl.h>
#include <sys/statvfs.h>
#include "cached_media.hpp"
// Private IPC operation only. No cookies, redirects, URLs in filenames/logs,
// DRM workarounds or additional decoder. Incomplete downloads are unusable.
struct CacheWrite {int fd=-1;size_t bytes=0,limit=0;};
static size_t cache_write(char*p,size_t a,size_t b,void*opaque){
    auto&w=*static_cast<CacheWrite*>(opaque);if(a&&b>SIZE_MAX/a)return 0;size_t n=a*b;
    if(n>w.limit-w.bytes)return 0;size_t at=0;
    while(at<n){ssize_t count=write(w.fd,p+at,n-at);if(count<=0)return 0;at+=size_t(count);}w.bytes+=n;return n;
}
static size_t cache_download(int dir,const std::string&name,const std::string&url,size_t cap){
    std::string h=host(url);if(!(domain(h,"bilivideo.com")||domain(h,"bilivideo.cn")||domain(h,"acgvideo.com")||domain(h,"biliapi.net")))return 0;
    std::string part=name+".part";int fd=openat(dir,part.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return 0;
    CacheWrite output{fd,0,cap};CURL*c=curl_easy_init();bool complete=false;
    if(c){
        curl_easy_setopt(c,CURLOPT_URL,url.c_str());curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,"https");curl_easy_setopt(c,CURLOPT_FOLLOWLOCATION,0L);
        curl_easy_setopt(c,CURLOPT_USERAGENT,"wiliwili");curl_easy_setopt(c,CURLOPT_REFERER,"https://www.bilibili.com/");
        curl_easy_setopt(c,CURLOPT_SSL_VERIFYPEER,1L);curl_easy_setopt(c,CURLOPT_SSL_VERIFYHOST,2L);
        const char*ca=getenv("P011_BILI_CA");curl_easy_setopt(c,CURLOPT_CAINFO,ca?ca:"/etc/ssl/certs/ca-certificates.crt");
        curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,4L);curl_easy_setopt(c,CURLOPT_TIMEOUT,20L);
        curl_easy_setopt(c,CURLOPT_MAXFILESIZE_LARGE,curl_off_t(cap));curl_easy_setopt(c,CURLOPT_MAX_RECV_SPEED_LARGE,curl_off_t(512*1024));
        curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,cache_write);curl_easy_setopt(c,CURLOPT_WRITEDATA,&output);
        auto rc=curl_easy_perform(c);long status=0;curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&status);curl_easy_cleanup(c);
        complete=rc==CURLE_OK&&status==200&&output.bytes>0;
    }
    close(fd);
    if(complete&&renameat(dir,part.c_str(),dir,name.c_str())==0)return output.bytes;
    unlinkat(dir,part.c_str(),0);return 0;
}
static J prefetch_media(const J&args){
    std::string key=str(args,"key"),video=str(args,"video"),audio=str(args,"audio");
    if(!std::regex_match(key,std::regex("[a-f0-9]{16}")))throw Failure("BAD_INPUT");
    const char*r=getenv("P011_CLIENT_ROOT");if(!r||*r!='/')throw Failure("BAD_INPUT");
    std::string dir=std::string(r)+"/preload";struct stat st{};struct statvfs space{};
    if(lstat(dir.c_str(),&st)||!S_ISDIR(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0077)||statvfs(dir.c_str(),&space)||uint64_t(space.f_bavail)*space.f_frsize<64*1024*1024)return {{"cached",false}};
    int fd=open(dir.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return {{"cached",false}};
    size_t v=0,a=0;
    try{v=cache_download(fd,key+"-v.m4s",video,8*1024*1024);if(v&&!audio.empty())a=cache_download(fd,key+"-a.m4s",audio,1024*1024);}catch(...){}
    bool complete=v&&(audio.empty()||a);
    if(!complete){unlinkat(fd,(key+"-v.m4s").c_str(),0);unlinkat(fd,(key+"-a.m4s").c_str(),0);}close(fd);
    return {{"cached",complete},{"bytes",complete?v+a:0}};
}
