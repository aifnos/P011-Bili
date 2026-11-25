// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/media_range.hpp"
#include <cassert>
#include <iostream>
using namespace p011_media;
static void word(std::string&s,uint32_t v){for(int n=3;n>=0;n--)s.push_back(char(v>>(n*8)));}
static std::string index(bool wide=false,uint32_t ref=2000,uint32_t offset=10){
    std::string s;word(s,wide?52:44);s+="sidx";word(s,wide?0x01000000:0);word(s,1);word(s,1000);
    if(wide)word(s,0);word(s,0);if(wide)word(s,0);word(s,offset);word(s,1);word(s,ref);word(s,5000);word(s,0x90000000);return s;
}
int main(){
    RangeReply r;r.line("HTTP/2 206\r\n");r.line("Content-Range: bytes 0-999/1000\r\n");assert(r.valid(0,4095)&&!r.valid(1,4095)&&!r.valid(0,998)&&!r.valid(0,4095,1001));
    r.line("HTTP/1.1 200 OK\r\n");assert(!r.valid(0,4095));
    for(const auto&s:{"Content-Range: bytes 0-1000/1000\r\n","Content-Range: bytes 2-1/1000\r\n","Content-Range: bytes 0-999/999999999999\r\n","Content-Range: bytes 0-999/*\r\n"}){r={};r.line("HTTP/1.1 206\r\n");r.line(s);assert(!r.valid(0,4095));}
    assert(opening_segment(index(),4096)==2054);assert(opening_segment(index(true),4096)==2062);
    assert(!opening_segment(index(false,0x80000001),4096));assert(!opening_segment(index(false,5000),4096));assert(!opening_segment(index(false,0),4096));
    for(bool wide:{false,true}){auto s=index(wide);for(size_t i=0;i<s.size();i++)assert(!opening_segment(s.substr(0,i),4096));}
    std::string ftyp;word(ftyp,12);ftyp+="ftypTEST";assert(opening_segment(ftyp+index(),4096)==2066);
    for(unsigned i=0;i<5000;i++){std::string garbage(i%300,'x');for(size_t n=0;n<garbage.size();n++)garbage[n]=char((i*33+n*71)&255);assert(opening_segment(garbage,4*1024*1024)<=4*1024*1024);}
    std::cout<<"range / index bounds and 5000 malformed inputs passed\n";
}
