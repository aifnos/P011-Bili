// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <nlohmann/json.hpp>
#include <algorithm>
#include <string>
#include <vector>
namespace p011_player {
struct Settings {
    int aspect=0,area=100,opacity=100,size=100,speed=100;
    static int pick(const nlohmann::json&j,const char*k,int fallback,std::initializer_list<int>valid){
        if(!j.is_object()||!j.contains(k)||!j[k].is_number_integer())return fallback;
        int n=j[k].get<int>();return std::find(valid.begin(),valid.end(),n)!=valid.end()?n:fallback;
    }
    static Settings from(const nlohmann::json&j){Settings s;s.aspect=pick(j,"aspect",0,{0,1,2,3,4});s.area=pick(j,"dm_area",100,{25,50,75,100});s.opacity=pick(j,"dm_opacity",100,{25,50,75,100});s.size=pick(j,"dm_size",100,{80,100,120,140});s.speed=pick(j,"dm_speed",100,{75,100,125,150});return s;}
    nlohmann::json json()const{return {{"aspect",aspect},{"dm_area",area},{"dm_opacity",opacity},{"dm_size",size},{"dm_speed",speed}};}
    static int cycle(int current,std::initializer_list<int>values){auto p=std::find(values.begin(),values.end(),current);return p==values.end()||++p==values.end()?*values.begin():*p;}
    bool change(const std::string&a,int value=0){
        if(a=="aspect")aspect=std::max(0,std::min(4,value));
        else if(a=="dm-area")area=cycle(area,{25,50,75,100});
        else if(a=="dm-opacity")opacity=cycle(opacity,{25,50,75,100});
        else if(a=="dm-size")size=cycle(size,{80,100,120,140});
        else if(a=="dm-speed")speed=cycle(speed,{75,100,125,150});
        else if(a=="dm-reset"){area=opacity=size=speed=100;}
        else return false;return true;
    }
};
inline std::string aspect_label(int a){return a==1?"填满裁切":a==2?"拉伸铺满":a==3?"16:9":a==4?"4:3":"原始比例";}
}
