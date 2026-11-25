// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <fcntl.h>
#include <sys/statvfs.h>
#include "cached_media.hpp"
#include "media_range.hpp"
// Private IPC only; signed URLs stay in anonymous pipes, never files/logs.
struct RangeTransfer {
    int fd=-1;uint64_t bytes=0,start=0,end=0,total=0,wanted=0;bool stream=false,announced=false;
    p011_media::RangeReply reply;std::string index;
};
static size_t range_header(char*p,size_t a,size_t b,void*opaque){
    if(a&&b>SIZE_MAX/a)return 0;size_t n=a*b;if(n>16384)return 0;
    try{static_cast<RangeTransfer*>(opaque)->reply.line(std::string(p,n));}catch(...){return 0;}return n;
}
static bool range_url(const std::string&url){auto h=host(url);return domain(h,"bilivideo.com")||domain(h,"bilivideo.cn")||domain(h,"acgvideo.com")||domain(h,"biliapi.net");}
static size_t range_write(char*p,size_t a,size_t b,void*opaque){
    auto&w=*static_cast<RangeTransfer*>(opaque);if(a&&b>SIZE_MAX/a)return 0;size_t n=a*b;
    if(!w.reply.valid(w.start,w.end,w.total))return 0;
    if(w.stream&&!w.announced){if(write(w.fd,"READY\n",6)!=6)return 0;w.announced=true;}
    if(!w.stream&&!w.wanted){
        w.index.append(p,std::min(n,65536-w.index.size()));
        w.wanted=p011_media::opening_segment(w.index,w.end+1);
        if(!w.wanted&&w.reply.total<=65536)w.wanted=w.reply.total;
        if(!w.wanted&&w.index.size()==65536)return 0;
    }
    uint64_t bound=w.stream?w.end-w.start+1:w.wanted?w.wanted:w.end+1;
    if(w.bytes>bound)return 0;
    size_t use=std::min(uint64_t(n),bound-w.bytes),at=0;
    while(at<use){ssize_t count=write(w.fd,p+at,use-at);if(count<=0)return 0;at+=size_t(count);}w.bytes+=use;
    return use==n&&(!w.wanted||w.bytes<w.wanted)?n:0;
}
static bool range_get(const std::string&url,RangeTransfer&w){
    if(!range_url(url))return false;CURL*c=curl_easy_init();if(!c)return false;
    std::string range=std::to_string(w.start)+"-"+std::to_string(w.end);
    curl_easy_setopt(c,CURLOPT_URL,url.c_str());curl_easy_setopt(c,CURLOPT_RANGE,range.c_str());
    curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,"https");curl_easy_setopt(c,CURLOPT_FOLLOWLOCATION,0L);curl_easy_setopt(c,CURLOPT_PROXY,"");
    curl_easy_setopt(c,CURLOPT_USERAGENT,"wiliwili");curl_easy_setopt(c,CURLOPT_REFERER,"https://www.bilibili.com/");
    curl_easy_setopt(c,CURLOPT_SSL_VERIFYPEER,1L);curl_easy_setopt(c,CURLOPT_SSL_VERIFYHOST,2L);
    const char*ca=getenv("P011_BILI_CA");curl_easy_setopt(c,CURLOPT_CAINFO,ca?ca:"/etc/ssl/certs/ca-certificates.crt");
    curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,4L);curl_easy_setopt(c,CURLOPT_TIMEOUT,w.stream?40L:20L);
    curl_easy_setopt(c,CURLOPT_LOW_SPEED_LIMIT,1024L);curl_easy_setopt(c,CURLOPT_LOW_SPEED_TIME,8L);
    if(!w.stream)curl_easy_setopt(c,CURLOPT_MAX_RECV_SPEED_LARGE,curl_off_t(384*1024));
    curl_easy_setopt(c,CURLOPT_HEADERFUNCTION,range_header);curl_easy_setopt(c,CURLOPT_HEADERDATA,&w);
    curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,range_write);curl_easy_setopt(c,CURLOPT_WRITEDATA,&w);
    auto rc=curl_easy_perform(c);curl_easy_cleanup(c);
    return w.reply.valid(w.start,w.end,w.total)&&(w.stream?rc==CURLE_OK&&w.bytes==w.end-w.start+1:
        w.wanted&&w.bytes==w.wanted&&(rc==CURLE_OK||rc==CURLE_WRITE_ERROR));
}
static J cache_head(int dir,const std::string&name,const std::string&url,uint64_t cap){
    std::string part=name+".part";int fd=openat(dir,part.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return J::object();
    RangeTransfer w;w.fd=fd;w.end=cap-1;bool ok=false;try{ok=range_get(url,w);}catch(...){}close(fd);
    if(ok&&renameat(dir,part.c_str(),dir,name.c_str())==0)return {{"bytes",w.bytes},{"total",w.reply.total},{"complete",w.bytes==w.reply.total}};
    unlinkat(dir,part.c_str(),0);return J::object();
}
static J prefetch_prefix(const J&args){
    std::string key=str(args,"key"),video=str(args,"video"),audio=str(args,"audio");
    if(!std::regex_match(key,std::regex("[a-f0-9]{16}")))throw Failure("BAD_INPUT");
    const char*r=getenv("P011_CLIENT_ROOT");if(!r||*r!='/')throw Failure("BAD_INPUT");
    std::string dir=std::string(r)+"/preload";struct stat st{};struct statvfs space{};
    if(lstat(dir.c_str(),&st)||!S_ISDIR(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0077)||statvfs(dir.c_str(),&space)||uint64_t(space.f_bavail)*space.f_frsize<64*1024*1024)return {{"cached",false}};
    int fd=open(dir.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return {{"cached",false}};
    J v=cache_head(fd,key+"-v.head",video,4*1024*1024),a=J::object();
    if(!v.empty()&&!audio.empty())a=cache_head(fd,key+"-a.head",audio,512*1024);
    bool ok=!v.empty()&&(audio.empty()||!a.empty());
    if(!ok){unlinkat(fd,(key+"-v.head").c_str(),0);unlinkat(fd,(key+"-a.head").c_str(),0);}close(fd);
    return {{"cached",ok},{"video",v},{"audio",a},{"bytes",ok?v.value("bytes",0u)+a.value("bytes",0u):0}};
}
static int stream_media(const J&args){
    try{
        RangeTransfer w;w.stream=true;w.fd=STDOUT_FILENO;w.start=args.at("start").get<uint64_t>();w.end=args.at("end").get<uint64_t>();w.total=args.at("total").get<uint64_t>();
        if(w.end<w.start||w.end>=w.total||w.end-w.start>=4*1024*1024||w.total>uint64_t(8)*1024*1024*1024)return 2;
        return range_get(str(args,"url"),w)?0:2;
    }catch(...){return 2;}
}
