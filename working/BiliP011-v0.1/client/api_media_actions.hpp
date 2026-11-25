// SPDX-License-Identifier: GPL-3.0-or-later
// Official web player dm/post and heartbeat contracts. Manual writes only.
#pragma once
static void require_user_write(){const char*p=getenv("P011_ACCOUNT_WRITES");if(!p||std::string(p)!="user-action")throw Failure("ACTION_DISABLED");}
static J media_context(const J&a){
    std::string b=bv(a),cid=id(a,"cid");J v=get(API+"/x/web-interface/view?bvid="+b);
    for(const auto&p:v.value("pages",J::array()))if(id(p,"cid")==cid){
        int duration=number(p,"duration");if(duration<=0||duration>86400)throw Failure("API_SCHEMA");
        return {{"aid",id(v,"aid")},{"cid",cid},{"duration",duration},{"ordinary",str(v,"redirect_url").empty()}};
    }
    throw Failure("BAD_INPUT");
}
static std::map<std::string,std::string> danmaku_form(const J&a,const J&context){
    std::string message=str(a,"message");int mode=number(a,"mode"),position=number(a,"position",-1);
    if(message.empty()||message.size()>400||std::any_of(message.begin(),message.end(),[](unsigned char c){return c<32;})||
        (mode!=1&&mode!=4&&mode!=5)||position<0||position>number(context,"duration"))throw Failure("BAD_INPUT");
    return {{"type","1"},{"oid",id(context,"cid")},{"aid",id(context,"aid")},{"msg",message},{"progress",std::to_string(position*1000)},
        {"color","16777215"},{"fontsize","25"},{"pool","0"},{"mode",std::to_string(mode)},{"plat","1"},
        {"polaris_app_id","100"},{"polaris_platform","5"},{"spmid","333.788.0.0"},{"statistics","{\"appId\":100,\"platform\":5}"}};
}
static J write_confirmed(const std::string&url,const std::map<std::string,std::string>&fields){
    std::string body=query(fields);J raw;
    try{raw=parse(request(url,true,&body).body);}catch(const Failure&e){if(std::string(e.what())=="INVALID_JSON")throw Failure("ACTION_UNCONFIRMED");throw;}
    int code=number(raw,"code",-999);if(code==-999)throw Failure("ACTION_UNCONFIRMED");
    if(code)throw Failure(code==-101?"LOGIN_REQUIRED":code==-352||code==-412?"API_VERIFICATION_REQUIRED":"API_ERROR",code);
    return raw;
}
static J danmaku_send(const J&a){
    require_user_write();auto context=media_context(a);auto fields=danmaku_form(a,context);
    fields["csrf"]=account_csrf();fields["rnd"]=std::to_string(int64_t(time(nullptr))*1000000);
    auto raw=write_confirmed(API+"/x/v2/dm/post",fields);auto d=raw.value("data",J::object());
    std::string dmid=str(d,"dmid_str",str(d,"dmid"));if(!digits(dmid)||dmid=="0")throw Failure("ACTION_UNCONFIRMED");
    return {{"confirmed",true},{"visible",flag(d,"visible")}};
}
static std::map<std::string,std::string> heartbeat_form(const J&a,const J&context,const std::string&mid){
    int duration=number(a,"video_duration"),played=number(a,"played_time",-2),type=number(a,"play_type",-1);
    if(!flag(context,"ordinary"))throw Failure("FEATURE_UNAVAILABLE");
    if(duration<=0||duration>number(context,"duration")+3||type<0||type>4||played< -1||played>duration+2||(played==-1)!=(type==4))throw Failure("BAD_INPUT");
    std::map<std::string,std::string> fields={{"aid",id(context,"aid")},{"cid",id(context,"cid")},{"mid",mid},{"type","3"},{"dt","2"},
        {"play_type",std::to_string(type)},{"played_time",std::to_string(played)},{"mobi_app","web"},{"device","web"},{"platform","web"},
        {"statistics","{\"appId\":100,\"platform\":5}"},{"spmid","333.788.0.0"}};
    for(const char*k:{"start_ts","realtime","real_played_time","video_duration","last_play_progress_time","max_play_progress_time"}){
        int v=number(a,k,-1);if(v<0||((std::string(k)!="start_ts")&&v>86402))throw Failure("BAD_INPUT");fields[k]=std::to_string(v);
    }
    return fields;
}
static J watch_heartbeat(const J&a){
    require_user_write();auto nav=account_nav();auto context=media_context(a);
    auto fields=heartbeat_form(a,context,id(nav,"mid"));fields["csrf"]=account_csrf();
    std::map<std::string,std::string> sign;
    for(const char*k:{"start_ts","mid","aid","dt","realtime","played_time","real_played_time","video_duration","last_play_progress_time"})sign[std::string("w_")+k]=fields.at(k);
    write_confirmed(API+"/x/click-interface/web/heartbeat?"+signed_query(sign),fields);
    return {{"confirmed",true}};
}
static int media_action_selftest(){
    int count=0;auto require=[&](bool v){if(!v)throw Failure("INTERNAL_SELF_TEST");count++;};
    J context={{"aid","1"},{"cid","2"},{"duration",120},{"ordinary",true}};
    for(int mode:{1,4,5}){auto f=danmaku_form({{"mode",mode},{"position",15},{"message","synthetic"}},context);require(f.at("progress")=="15000"&&f.at("pool")=="0"&&f.at("mode")==std::to_string(mode));}
    for(int mode:{6,7,8,9}){bool failed=false;try{danmaku_form({{"mode",mode},{"position",15},{"message","synthetic"}},context);}catch(const Failure&){failed=true;}require(failed);}
    J a={{"video_duration",120},{"played_time",15},{"play_type",0},{"start_ts",1700000000},{"realtime",15},{"real_played_time",10},{"last_play_progress_time",15},{"max_play_progress_time",15}};
    auto f=heartbeat_form(a,context,"3");require(f.at("type")=="3"&&f.at("dt")=="2"&&f.at("real_played_time")=="10");
    a["play_type"]=4;a["played_time"]=-1;require(heartbeat_form(a,context,"3").at("played_time")=="-1");
    a["play_type"]=0;bool failed=false;try{heartbeat_form(a,context,"3");}catch(const Failure&){failed=true;}require(failed);
    return count;
}
