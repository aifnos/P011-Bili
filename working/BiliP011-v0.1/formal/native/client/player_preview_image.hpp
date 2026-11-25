// SPDX-License-Identifier: GPL-3.0-or-later
// Decode a bounded official sprite cell off the render thread; no file/network I/O.
#pragma once
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO
#define STBI_MAX_DIMENSIONS 4096
#include <nanovg/stb_image.h>
static void decode_preview_image(p011_ipc::Packet&p){
    auto&j=p.value;if(j.value("op","")!="feature"||j.value("feature","")!="player_preview"||!j.value("ok",false))return;
    auto&d=j["data"];std::string encoded=d.value("jpeg","");d.erase("jpeg");
    if(encoded.size()>600000)return;std::vector<unsigned char> bytes;bytes.reserve(encoded.size()*3/4);
    unsigned bits=0;int count=0;const std::string alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for(char c:encoded){if(c=='=')break;auto n=alphabet.find(c);if(n==std::string::npos)return;bits=(bits<<6)|unsigned(n);count+=6;if(count>=8){count-=8;bytes.push_back((bits>>count)&255);}}
    int iw=0,ih=0,ch=0;if(bytes.empty()||!stbi_info_from_memory(bytes.data(),int(bytes.size()),&iw,&ih,&ch)||iw<1||ih<1||int64_t(iw)*ih>4000000)return;
    int x=d.value("x",0),y=d.value("y",0),w=d.value("w",0),h=d.value("h",0);
    if(x<0||y<0||w<1||h<1||w>640||h>360||x>iw-w||y>ih-h)return;
    auto*image=stbi_load_from_memory(bytes.data(),int(bytes.size()),&iw,&ih,&ch,4);if(!image)return;
    p.image.resize(size_t(w)*h*4);for(int row=0;row<h;row++)memcpy(p.image.data()+size_t(row)*w*4,image+(size_t(y+row)*iw+x)*4,size_t(w)*4);
    stbi_image_free(image);p.image_width=w;p.image_height=h;
}
