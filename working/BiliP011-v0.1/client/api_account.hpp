// SPDX-License-Identifier: GPL-3.0-or-later
// Contracts verified against the official public website bundles, 2026-09-26.
// No guessed feedback endpoint, automatic account mutations or captcha bypass.
#pragma once
#include <fstream>
#include <sstream>
#include <openssl/pem.h>
#include <openssl/rsa.h>

static J password_challenge(){
    J d=get("https://passport.bilibili.com/x/passport-login/captcha?source=main_web");
    if(str(d,"type")!="geetest"||!d.contains("geetest"))throw Failure("CAPTCHA_UNSUPPORTED");
    J g=d["geetest"];return {{"token",str(d,"token")},{"gt",str(g,"gt")},{"challenge",str(g,"challenge")}};
}
static J password_login(const J&a){
    const char*allowed=getenv("P011_ACCOUNT_WRITES");if(!allowed||std::string(allowed)!="user-action")throw Failure("ACTION_DISABLED");
    std::string username=str(a,"username"),password=str(a,"password");
    if(username.empty()||username.size()>160||password.empty()||password.size()>256)throw Failure("BAD_INPUT");
    J k=get("https://passport.bilibili.com/x/passport-login/web/key");auto pem=str(k,"key");auto salt=str(k,"hash");
    if(pem.size()>8192||salt.size()>256)throw Failure("API_SCHEMA");
    BIO* bio=BIO_new_mem_buf(pem.data(),int(pem.size()));if(!bio)throw Failure("NETWORK_INIT");
    EVP_PKEY* key=PEM_read_bio_PUBKEY(bio,nullptr,nullptr,nullptr);BIO_free(bio);
    if(!key)throw Failure("API_SCHEMA");EVP_PKEY_CTX*ctx=EVP_PKEY_CTX_new(key,nullptr);
    std::string clear=salt+password;std::vector<unsigned char> cipher;size_t length=0;
    bool valid=ctx&&EVP_PKEY_encrypt_init(ctx)>0&&EVP_PKEY_CTX_set_rsa_padding(ctx,RSA_PKCS1_PADDING)>0&&EVP_PKEY_encrypt(ctx,nullptr,&length,reinterpret_cast<const unsigned char*>(clear.data()),clear.size())>0;
    if(valid&&length<=8192){cipher.resize(length);valid=EVP_PKEY_encrypt(ctx,cipher.data(),&length,reinterpret_cast<const unsigned char*>(clear.data()),clear.size())>0;}else valid=false;
    OPENSSL_cleanse(&clear[0],clear.size());OPENSSL_cleanse(&password[0],password.size());if(ctx)EVP_PKEY_CTX_free(ctx);EVP_PKEY_free(key);
    if(!valid)throw Failure("LOGIN_ENCRYPTION_FAILED");
    std::string encrypted(4*((length+2)/3)+1,'\0');int used=EVP_EncodeBlock(reinterpret_cast<unsigned char*>(&encrypted[0]),cipher.data(),int(length));encrypted.resize(used);
    std::map<std::string,std::string>fields={{"username",username},{"password",encrypted},{"keep","0"},{"source","main_web"},{"go_url","https://www.bilibili.com/"}};
    for(const char*k:{"token","challenge","validate","seccode"}){auto value=str(a,k);if(value.empty()||value.size()>512||value.find_first_of("\r\n\t")!=std::string::npos)throw Failure("BAD_INPUT");fields[k]=value;}
    std::string body=query(fields);auto r=request("https://passport.bilibili.com/x/passport-login/web/login",true,&body);
    J d=data(parse(r.body));if(number(d,"status",-1)!=0)throw Failure("LOGIN_SECOND_FACTOR",number(d,"status",-1));
    return {{"cookies",r.cookies}};
}

static std::string account_csrf(){
    const char* path=getenv("P011_BILI_COOKIES");if(!path)throw Failure("LOGIN_REQUIRED");
    std::ifstream f(path);std::string line,csrf;size_t bytes=0;
    while(std::getline(f,line)){
        bytes+=line.size();if(bytes>32768)throw Failure("COOKIE_REJECTED");
        if(line.rfind("#HttpOnly_",0)==0)line.erase(0,10);
        if(line.empty()||line[0]=='#')continue;
        std::vector<std::string> fields;std::istringstream row(line);std::string cell;
        while(std::getline(row,cell,'\t'))fields.push_back(cell);
        if(fields.size()!=7||fields[5]!="bili_jct")continue;
        if(fields[0]!=".bilibili.com"&&fields[0]!="bilibili.com")continue;
        if(std::regex_match(fields[6],std::regex("[a-fA-F0-9]{32}")))csrf=fields[6];
    }
    if(csrf.empty())throw Failure("LOGIN_REQUIRED");return csrf;
}
static J account_nav(){J d=get(API+"/x/web-interface/nav");if(!flag(d,"isLogin"))throw Failure("LOGIN_REQUIRED");return d;}
static J account_relation(const J&a){
    auto b=bv(a);J d=get(API+"/x/web-interface/archive/relation?bvid="+b);
    return {{"like",flag(d,"like")},{"favorite",flag(d,"favorite")},{"coin",number(d,"coin")}};
}
static J season_relation(const J&a){
    account_nav();J d=get(API+"/pgc/view/web/season?season_id="+id(a,"season"));
    auto s=d.value("user_status",J::object());if(!s.contains("follow"))throw Failure("API_SCHEMA");
    return {{"following",flag(s,"follow")},{"title",clean(str(d,"title"),180)}};
}
static J season_follow(const J&a){
    const char*allowed=getenv("P011_ACCOUNT_WRITES");if(!allowed||std::string(allowed)!="user-action")throw Failure("ACTION_DISABLED");
    if(!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
    auto season=id(a,"season"),csrf=account_csrf();season_relation(a);
    std::string body=query({{"season_id",season},{"csrf",csrf}}),url=API+(a["value"].get<bool>()?"/pgc/web/follow/add":"/pgc/web/follow/del");
    J raw;try{raw=parse(request(url,true,&body).body);}catch(const Failure&e){if(std::string(e.what())=="INVALID_JSON")throw Failure("ACTION_UNCONFIRMED");throw;}int code=number(raw,"code",-999);
    if(code==-999)throw Failure("ACTION_UNCONFIRMED");if(code)throw Failure(code==-101?"LOGIN_REQUIRED":code==-352||code==-412?"API_VERIFICATION_REQUIRED":"API_ERROR",code);
    return {{"confirmed",true},{"state_available",false}};
}
static J account_folders(const J&a){
    auto b=bv(a);J nav=account_nav(),v=get(API+"/x/web-interface/view?bvid="+b);
    J d=get(API+"/x/v3/fav/folder/created/list-all?"+query({{"type","2"},{"rid",id(v,"aid")},{"up_mid",id(nav,"mid")}}));
    J rows=J::array();auto list=d.value("list",J::array());
    if(list.is_null())list=J::array();if(!list.is_array()||list.size()>1000)throw Failure("API_SCHEMA");
    for(auto&r:list)rows.push_back({{"id",id(r,"id")},{"title",clean(str(r,"title"),120)},{"selected",number(r,"fav_state")==1}});
    return {{"items",rows}};
}
static std::pair<std::string,std::map<std::string,std::string>> interaction_form(const J&a,const std::string&aid){
    std::string action=str(a,"action");std::map<std::string,std::string>p={{"aid",aid}};std::string endpoint;
    if(action=="like"){
        if(!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
        endpoint="/x/web-interface/archive/like";p["like"]=a["value"].get<bool>()?"1":"2";
    }else if(action=="coin"){
        int coins=number(a,"count");if(coins!=1&&coins!=2)throw Failure("BAD_INPUT");
        endpoint="/x/web-interface/coin/add";p["multiply"]=std::to_string(coins);p["select_like"]="0";
    }else if(action=="triple")endpoint="/x/web-interface/archive/like/triple";
    else if(action=="favorite"){
        if(!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
        endpoint="/x/v3/fav/resource/deal";p.erase("aid");p["rid"]=aid;p["type"]="2";p["platform"]="web";
        p[a["value"].get<bool>()?"add_media_ids":"del_media_ids"]=id(a,"folder");
    }else if(action=="watchlater"){
        if(!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
        endpoint=a["value"].get<bool>()?"/x/v2/history/toview/add":"/x/v2/history/toview/del";
    }else if(action=="follow"){
        if(!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
        endpoint="/x/relation/modify";p.erase("aid");p["fid"]=id(a,"owner_mid");p["act"]=a["value"].get<bool>()?"1":"2";p["re_src"]="14";p["spmid"]="333.788.0.0";
    }else if(action=="comment"||action=="comment_like"){
        auto root=id(a,"root"),parent=id(a,"parent");p={{"oid",aid},{"type","1"},{"statistics","{\"appId\":100,\"platform\":5}"}};
        if((root=="0")!=(parent=="0"))throw Failure("BAD_INPUT");
        if(action=="comment"){
            auto message=str(a,"message");if(message.empty()||message.size()>640||std::any_of(message.begin(),message.end(),[](unsigned char c){return c<32;}))throw Failure("BAD_INPUT");
            endpoint="/x/v2/reply/add";p["plat"]="1";p["message"]=message;p["gaia_source"]="main_web";p["root"]=root;p["parent"]=parent;
        }else{
            if(parent=="0"||!a.contains("value")||!a["value"].is_boolean())throw Failure("BAD_INPUT");
            endpoint="/x/v2/reply/action";p["rpid"]=parent;p["action"]=a["value"].get<bool>()?"1":"0";
        }
    }else throw Failure("BAD_INPUT");
    return {endpoint,p};
}
static J account_interaction(const J&a){
    const char* allowed=getenv("P011_ACCOUNT_WRITES");if(!allowed||std::string(allowed)!="user-action")throw Failure("ACTION_DISABLED");
    auto b=bv(a);auto csrf=account_csrf();J v=get(API+"/x/web-interface/view?bvid="+b);
    J bound=a;if(str(a,"action")=="follow")bound["owner_mid"]=id(v.value("owner",J::object()),"mid");
    if((str(a,"action")=="comment"||str(a,"action")=="comment_like")&&id(a,"root")!="0"){
        auto context=get(API+"/x/v2/reply/detail?"+query({{"oid",id(v,"aid")},{"type","1"},{"root",id(a,"root")}}));
        auto root=context.value("root",J::object());if(str(root,"rpid_str",str(root,"rpid"))!=id(a,"root"))throw Failure("BAD_INPUT");
    }
    auto spec=interaction_form(bound,id(v,"aid"));spec.second["csrf"]=csrf;
    std::string body=query(spec.second);J raw;
    try{raw=parse(request(API+spec.first,true,&body).body);}catch(const Failure&e){if(std::string(e.what())=="INVALID_JSON")throw Failure("ACTION_UNCONFIRMED");throw;}
    int code=number(raw,"code",-999);if(code==-999)throw Failure("ACTION_UNCONFIRMED");if(code)throw Failure(code==-101?"LOGIN_REQUIRED":code==-352||code==-412?"API_VERIFICATION_REQUIRED":"API_ERROR",code);
    // A successful write does not justify inventing the resulting counters.
    J result={{"submitted",true},{"confirmed",true},{"state_available",false}};
    if(str(a,"action")=="triple"&&raw.contains("data")&&raw["data"].is_object()){
        auto d=raw["data"];result["triple"]={{"like",flag(d,"like")},{"coin",flag(d,"coin")},{"favorite",flag(d,"fav")}};
    }
    try{result["relation"]=account_relation(a);result["state_available"]=true;}catch(const Failure&){}
    return result;
}
static int account_form_selftest(){
    int count=0;auto require=[&](bool value){if(!value)throw Failure("INTERNAL_SELF_TEST");count++;};
    for(const auto&action:{"like","watchlater","follow","favorite","comment_like"})for(bool value:{false,true}){
        J a={{"action",action},{"value",value},{"owner_mid","7"},{"folder","8"},{"root","9"},{"parent","10"}};
        auto form=interaction_form(a,"42");require(form.first.rfind("/x/",0)==0);
        if(std::string(action)=="comment_like")require(form.second.at("rpid")=="10"&&form.second.at("action")== (value?"1":"0"));
    }
    for(const char*root:{"0","9"}){
        auto form=interaction_form({{"action","comment"},{"root",root},{"parent",root},{"message","synthetic only"}},"42");
        require(form.first=="/x/v2/reply/add"&&form.second.at("message")=="synthetic only"&&form.second.at("oid")=="42"&&form.second.at("plat")=="1");
    }
    for(const J&a:{J{{"action","comment"},{"root","0"},{"parent","9"},{"message","text"}},J{{"action","comment"},{"root","0"},{"parent","0"},{"message","bad\ntext"}},J{{"action","comment_like"},{"root","0"},{"parent","0"},{"value",true}}}){
        bool failed=false;try{interaction_form(a,"42");}catch(const Failure&){failed=true;}require(failed);
    }
    return count;
}
static J account_history(const J&a){
    account_nav();std::map<std::string,std::string>p={{"ps","20"},{"type","all"}};
    for(const char*k:{"max","view_at"}){auto value=str(a,k,"0");if(!digits(value))throw Failure("BAD_INPUT");p[k]=value;}
    auto business=str(a,"business");if(business.size()>32||!std::regex_match(business,std::regex("[a-z_]*")))throw Failure("BAD_INPUT");p["business"]=business;
    J d=get(API+"/x/web-interface/history/cursor?"+query(p));J rows=J::array();
    for(auto&r:d.value("list",J::array())){
        auto h=r.value("history",J::object());std::string kind=str(h,"business");J row=card(r);
        row["up"]=clean(str(r,"author_name"),90);row["position"]=std::max(0,number(r,"progress"));row["finished"]=number(r,"progress")==-1;
        row["bvid"]=str(h,"bvid");row["business"]=kind;row["playable"]=kind=="archive"||kind=="pgc"||kind=="live";
        row["cid"]=str(h,"cid");row["part_title"]=clean(str(h,"part"));row["mid"]=str(r,"author_mid");
        if(kind=="live"){row["kind"]="live";row["room"]=str(h,"oid");}
        else if(kind=="pgc"){row["kind"]="season";row["ep"]=str(h,"epid");}
        row["view_at"]=str(r,"view_at");rows.push_back(row);if(rows.size()>=20)break;
    }
    J cursor=d.value("cursor",J::object());return {{"items",rows},{"more",!rows.empty()&&str(cursor,"max","0")!="0"},{"cursor",{{"max",str(cursor,"max","0")},{"view_at",str(cursor,"view_at","0")},{"business",str(cursor,"business")}}}};
}
static const std::string LIVE="https://api.live.bilibili.com";
static J live_row(const J&r){
    std::string room=str(r,"roomid",str(r,"room_id"));if(!digits(room))throw Failure("API_SCHEMA");
    return {{"kind","live"},{"room",room},{"title",clean(str(r,"title"))},{"up",clean(str(r,"uname"),90)},
        {"cover",https(str(r,"cover",str(r,"user_cover",str(r,"keyframe"))))},{"duration","直播"}};
}
static J live_catalog(const J&){
    J d=get(LIVE+"/xlive/web-interface/v1/index/getList?platform=web"),rows=J::array();std::set<std::string> seen;
    // The official homepage supplies area groups; flatten their real room cards.
    auto append=[&](const J&r){if(!r.is_object())return;std::string room=str(r,"roomid",str(r,"room_id"));if(!digits(room)||!seen.insert(room).second||rows.size()>=60)return;rows.push_back(live_row(r));};
    for(const char*key:{"recommend_room_list","room_list"}){
        auto groups=d.value(key,J::array());if(!groups.is_array())continue;
        for(auto&group:groups){append(group);if(group.is_object())for(const char*list:{"list","room_list"})if(group.contains(list)&&group[list].is_array())for(auto&r:group[list])append(r);}
    }
    return {{"items",rows},{"more",false}};
}
static J live_detail(const J&a){
    J d=get(LIVE+"/room/v1/Room/get_info?room_id="+id(a,"room")),r=live_row(d);
    r["live_status"]=number(d,"live_status");r["description"]=clean(str(d,"description"),1000);return r;
}
// Private IPC only. Room-scoped short-lived auth material must never enter QML,
// command lines, general job results or diagnostic archives.
static J live_danmaku_info(const J&a){
    auto room=id(live_detail(a),"room");
    J d=get(LIVE+"/xlive/web-room/v1/index/getDanmuInfo?"+signed_query({{"id",room},{"type","0"}}));
    auto token=str(d,"token");if(token.empty()||token.size()>4096)throw Failure("API_SCHEMA");
    J servers=J::array();std::regex valid("[a-zA-Z0-9-]+(\\.[a-zA-Z0-9-]+)*\\.chat\\.bilibili\\.com");
    for(auto&s:d.value("host_list",J::array()))if(std::regex_match(str(s,"host"),valid)&&(number(s,"wss_port")==443||number(s,"wss_port")==2245)){
        servers.push_back({{"host",str(s,"host")},{"port",number(s,"wss_port")}});if(servers.size()>=6)break;
    }
    if(servers.empty())throw Failure("FEATURE_UNAVAILABLE");std::string uid="0";
    try{uid=id(account_nav(),"mid");}catch(const Failure&e){if(std::string(e.what())!="LOGIN_REQUIRED")throw;}
    return {{"room",room},{"uid",uid},{"token",token},{"servers",servers}};
}
static J live_play(const J&a){
    int q=number(a,"quality",0);if(q<0||q>65535)throw Failure("BAD_INPUT");
    // This private FFmpeg build contains HLS/MPEG-TS, not the FLV demuxer.
    // Request the actual official AVC HLS stream, without repackaging it.
    J d=get(LIVE+"/xlive/web-room/v2/index/getRoomPlayInfo?"+query({{"room_id",id(a,"room")},{"protocol","1"},{"format","1"},{"codec","0"},{"qn",std::to_string(q?q:150)},{"platform","web"},{"ptype","8"}}));
    if(flag(d,"is_locked")||flag(d,"is_hidden")||(flag(d,"encrypted")&&!flag(d,"pwd_verified")))throw Failure("LIVE_RESTRICTED");
    if(number(d,"live_status")!=1)throw Failure("LIVE_OFFLINE");
    J info=d.value("playurl_info",J::object()).value("playurl",J::object());
    for(auto&s:info.value("stream",J::array()))if(str(s,"protocol_name")=="http_hls")for(auto&f:s.value("format",J::array()))if(str(f,"format_name")=="ts")for(auto&c:f.value("codec",J::array()))if(str(c,"codec_name")=="avc"){
        int actual=number(c,"current_qn");if(q&&actual!=q)throw Failure("QUALITY_UNAVAILABLE");J qs=J::array();
        auto accepted=c.value("accept_qn",J::array());for(auto&v:info.value("g_qn_desc",J::array())){int n=number(v,"qn");if(std::find(accepted.begin(),accepted.end(),J(n))!=accepted.end())qs.push_back({{"id",n},{"label",clean(str(v,"desc"),40)}});}
        for(auto&u:c.value("url_info",J::array())){
            try{auto url=media_url(https(str(u,"host"))+str(c,"base_url")+str(u,"extra"));
                return {{"video",url},{"audio",""},{"live",true},{"room",id(a,"room")},{"codec",7},{"width",0},{"height",0},{"quality",actual},{"qualities",qs},{"codecs",J::array({J{{"id",7},{"label","AVC · 直播软解"}}})},{"preview",false}};
            }catch(const Failure&e){if(std::string(e.what())!="MEDIA_HOST_UNSUPPORTED")throw;}
        }
    }
    throw Failure("NO_SUPPORTED_STREAM");
}
