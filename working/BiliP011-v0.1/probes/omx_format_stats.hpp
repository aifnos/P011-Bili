// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>

struct OmxFormatStats {
    uint32_t count=0,overflow=0,invalid=0,rows[24][14]={{0}};
    void record(const uint32_t* values) {
        if(!values||values[0]<1||values[0]>3){if(invalid<UINT32_MAX)invalid++;return;}
        if(count==24){if(overflow<UINT32_MAX)overflow++;return;}
        memcpy(rows[count++],values,sizeof(rows[0]));
    }
    size_t format(char*line,size_t capacity)const {
        size_t used=0;
        auto add=[&](const char*format,auto... args){
            if(used>=capacity)return;
            const int n=snprintf(line+used,capacity-used,format,args...);
            if(n<0||size_t(n)>=capacity-used){used=capacity;return;}
            used+=size_t(n);
        };
        add("P011_OMX_FORMAT={\"schema\":1,\"count\":%u,\"overflow\":%u,\"invalid\":%u,\"records\":[",count,overflow,invalid);
        for(uint32_t i=0;i<count;i++){
            add("%s",i?",[":"[");
            for(unsigned j=0;j<14;j++)add(j?",%u":"%u",rows[i][j]);
            add("%s","]");
        }
        add("%s","]}\n");
        return used<capacity?used:0;
    }
};
