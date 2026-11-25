// SPDX-License-Identifier: GPL-3.0-or-later
// P011 adapter. API/WBI protocol follows xfangfang/wiliwili v1.6.0
// (88e5876bea9502d06f46a8656e3530684d3aaf7d). Private IPC, never raw log.
#include <curl/curl.h>
#include <openssl/evp.h>
#include <nlohmann/json.hpp>
#include "qrcodegen.hpp"
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <csignal>
#include <cmath>
#include <vector>
#include <ctime>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <sys/prctl.h>
using J=nlohmann::json;
struct Failure:std::runtime_error {int code;Failure(const char *s,int n=-1):std::runtime_error(s),code(n){}};
static std::string str(const J &j,const char *key,const std::string &fallback="") {
    if(!j.is_object()||!j.contains(key))return fallback;
    const auto &v=j[key];if(v.is_string())return v.get<std::string>();
    if(v.is_number_integer())return std::to_string(v.get<int64_t>());return fallback;
}
static int number(const J &j,const char *key,int fallback=0) {
    if(j.is_object()&&j.contains(key)&&j[key].is_number_integer())return j[key].get<int>();return fallback;
}
static bool flag(const J &j,const char *key) {
    if(!j.is_object()||!j.contains(key))return false;
    if(j[key].is_boolean())return j[key].get<bool>();
    return j[key].is_number_integer()&&j[key].get<int64_t>()!=0;
}
static std::string host(const std::string &url) {
    static const std::regex re("^https://([a-zA-Z0-9.-]+)(?::443)?(?:[/?#].*)?$");
    std::smatch m;if(!std::regex_match(url,m,re))throw Failure("URL_REJECTED");
    std::string value=m[1];std::transform(value.begin(),value.end(),value.begin(),::tolower);return value;
}
static bool domain(const std::string &name,const std::string &suffix) {
    return name==suffix||(name.size()>suffix.size()+1&&name.compare(name.size()-suffix.size()-1,suffix.size()+1,"."+suffix)==0);
}
static std::string https(std::string url) {
    if(url.rfind("//",0)==0)url="https:"+url;
    if(url.rfind("http://",0)==0)url.replace(0,7,"https://");return url;
}
static std::string clean(std::string text,size_t maximum=180) {
    text=std::regex_replace(text,std::regex("<[^>]*>"),"");
    const std::pair<const char*,const char*> entities[]={{"&amp;","&"},{"&lt;","<"},{"&gt;",">"},{"&quot;","\""},{"&#39;","'"},{"&nbsp;"," "}};
    for(auto &e:entities){size_t at=0;while((at=text.find(e.first,at))!=std::string::npos){text.replace(at,strlen(e.first),e.second);at+=strlen(e.second);}}
    for(char &c:text)if((unsigned char)c<32)c=' ';
    if(text.size()>maximum){size_t end=maximum;while(end>0&&((unsigned char)text[end]&0xc0)==0x80)--end;text.resize(end);}
    return text;
}
static size_t write_body(char *p,size_t a,size_t b,void *v) {
    std::string &out=*static_cast<std::string*>(v);size_t n=a*b;
    if(n>4*1024*1024||out.size()>4*1024*1024-n)return 0;out.append(p,n);return n;
}
struct Response {std::string body;std::vector<std::string> cookies;long status=0;};
static Response request(const std::string &url,bool account=true,const std::string *form=nullptr) {
    std::string h=host(url);
    if(account&&(h!="api.bilibili.com"&&h!="passport.bilibili.com"&&h!="app.bilibili.com"&&h!="api.live.bilibili.com"))throw Failure("API_HOST_REJECTED");
    if(!account&&!domain(h,"hdslb.com"))throw Failure("IMAGE_HOST_REJECTED");
    CURL *c=curl_easy_init();if(!c)throw Failure("NETWORK_INIT");Response result;
    curl_easy_setopt(c,CURLOPT_URL,url.c_str());curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,"https");
    curl_easy_setopt(c,CURLOPT_FOLLOWLOCATION,0L);curl_easy_setopt(c,CURLOPT_USERAGENT,"wiliwili");
    curl_easy_setopt(c,CURLOPT_REFERER,"https://www.bilibili.com/client");
    curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,5L);curl_easy_setopt(c,CURLOPT_TIMEOUT,12L);curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);
    curl_easy_setopt(c,CURLOPT_SSL_VERIFYPEER,1L);curl_easy_setopt(c,CURLOPT_SSL_VERIFYHOST,2L);
    const char *ca=getenv("P011_BILI_CA");curl_easy_setopt(c,CURLOPT_CAINFO,ca?ca:"/etc/ssl/certs/ca-certificates.crt");
    curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,write_body);curl_easy_setopt(c,CURLOPT_WRITEDATA,&result.body);
    if(account){const char *file=getenv("P011_BILI_COOKIES");curl_easy_setopt(c,CURLOPT_COOKIEFILE,file?file:"");}
    if(form){
        // No transport retries: a lost response may still have committed.
        curl_easy_setopt(c,CURLOPT_POST,1L);curl_easy_setopt(c,CURLOPT_POSTFIELDS,form->data());
        curl_easy_setopt(c,CURLOPT_POSTFIELDSIZE,long(form->size()));
    }
    CURLcode rc=curl_easy_perform(c);curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&result.status);
    if(account&&h=="passport.bilibili.com") {
        curl_slist *cookies=nullptr;curl_easy_getinfo(c,CURLINFO_COOKIELIST,&cookies);
        for(auto p=cookies;p;p=p->next)result.cookies.push_back(p->data);curl_slist_free_all(cookies);
    }
    curl_easy_cleanup(c);
    if(rc!=CURLE_OK)throw Failure(form?"ACTION_UNCONFIRMED":"NETWORK_ERROR",int(rc));
    if(result.status!=200)throw Failure(form?"ACTION_UNCONFIRMED":"HTTP_ERROR",int(result.status));return result;
}
static J parse(const std::string &raw) {J j=J::parse(raw,nullptr,false);if(j.is_discarded())throw Failure("INVALID_JSON");return j;}
static J data(const J &root) {
    int code=number(root,"code",-999);if(code!=0)throw Failure(code==-101?"LOGIN_REQUIRED":"API_ERROR",code);
    if(root.contains("data")&&!root["data"].is_null())return root["data"];
    if(root.contains("result"))return root["result"];throw Failure("API_SCHEMA");
}
static J get(const std::string &url) {return data(parse(request(url).body));}
static std::string encode(const std::string &value) {
    CURL *c=curl_easy_init();char *encoded=curl_easy_escape(c,value.data(),int(value.size()));
    if(!encoded){curl_easy_cleanup(c);throw Failure("ENCODING");}std::string out=encoded;curl_free(encoded);curl_easy_cleanup(c);return out;
}
static std::string query(const std::map<std::string,std::string> &params) {
    std::string result;for(auto &p:params){if(!result.empty())result+='&';result+=encode(p.first)+'='+encode(p.second);}return result;
}
static std::string signed_query(std::map<std::string,std::string> params) {
    J nav=parse(request("https://api.bilibili.com/x/web-interface/nav").body);
    if(!nav.contains("data")||!nav["data"].contains("wbi_img"))throw Failure("WBI_KEYS");
    auto keys=nav["data"]["wbi_img"];std::string raw,mixin;
    for(const char *name:{"img_url","sub_url"}) {std::string s=str(keys,name);size_t a=s.find_last_of('/'),b=s.find_last_of('.');if(a==s.npos||b==s.npos||b<=a)throw Failure("WBI_KEYS");raw+=s.substr(a+1,b-a-1);}
    const int perm[]={46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13};
    if(raw.size()!=64)throw Failure("WBI_KEYS");for(int i:perm)mixin+=raw[i];
    params["wts"]=std::to_string(time(nullptr));
    for(auto &p:params)p.second.erase(std::remove_if(p.second.begin(),p.second.end(),[](char c){return std::string("!'()*").find(c)!=std::string::npos;}),p.second.end());
    std::string q=query(params),input=q+mixin;unsigned char hash[EVP_MAX_MD_SIZE];unsigned count=0;
    if(!EVP_Digest(input.data(),input.size(),hash,&count,EVP_md5(),nullptr)||count!=16)throw Failure("WBI_SIGN");
    char hex[33];for(unsigned i=0;i<count;i++)snprintf(hex+2*i,3,"%02x",hash[i]);return q+"&w_rid="+hex;
}
static const std::string API="https://api.bilibili.com";
static bool digits(const std::string &s){return !s.empty()&&s.size()<=20&&s.find_first_not_of("0123456789")==s.npos;}
static std::string bv(const J &args){std::string value=str(args,"bvid");if(!std::regex_match(value,std::regex("BV[0-9A-Za-z]{10}")))throw Failure("BAD_BVID");return value;}
static std::string id(const J &args,const char *key){std::string value=str(args,key);if(!digits(value))throw Failure("BAD_ID");return value;}
static int page(const J &a){int v=number(a,"page",1);if(v<1||v>100)throw Failure("PAGE_LIMIT");return v;}
static J card(const J &v,const std::string &kind="video") {
    J result={{"kind",kind},{"title",clean(str(v,"title"))},{"bvid",str(v,"bvid")},{"cover",https(str(v,"pic",str(v,"cover")))},
              {"up",clean(str(v,"author"),90)},{"duration",str(v,"duration")},{"season",str(v,"season_id")},{"ep",str(v,"ep_id")},{"aid",str(v,"aid")}};
    if(v.contains("duration")&&v["duration"].is_number_integer()) {
        int total=number(v,"duration");char clock[32];snprintf(clock,sizeof(clock),"%d:%02d",std::max(0,total)/60,std::max(0,total)%60);result["duration"]=clock;
    }
    result["mid"]=str(v,"mid");
    if(v.contains("owner")){result["up"]=clean(str(v["owner"],"name"),90);result["mid"]=str(v["owner"],"mid");}
    else if(v.contains("author")&&v["author"].is_object())result["up"]=clean(str(v["author"],"name"),90);
    if(result["bvid"]==""&&v.contains("goto")&&str(v,"goto")!="av")result["skip"]=true;
    return result;
}
static J following_cards(const J &data) {
    if(!data.contains("items")||data["items"].is_null())return J::array();
    if(!data["items"].is_array())throw Failure("API_SCHEMA");
    J result=J::array();
    for(const auto &value:data["items"]) {
        if(!value.is_object())continue;
        // /feed/video returns flat video cards (unlike /feed/all modules).
        // Retain support for a wrapped archive without discarding the flat API.
        J row;
        if(!str(value,"bvid").empty())row=card(value);
        else if(value.contains("modules")&&value["modules"].is_object()) {
            const auto &m=value["modules"];
            if(!m.contains("module_dynamic")||!m["module_dynamic"].is_object())continue;
            const auto &d=m["module_dynamic"];
            if(!d.contains("major")||!d["major"].is_object()||!d["major"].contains("archive")||!d["major"]["archive"].is_object())continue;
            row=card(d["major"]["archive"]);
            if(m.contains("module_author"))row["up"]=clean(str(m["module_author"],"name"),90);
        }
        if(row.is_object()&&std::regex_match(str(row,"bvid"),std::regex("BV[0-9A-Za-z]{10}")))result.push_back(row);
    }
    // A nonempty video feed turning into zero cards is a schema failure, not
    // proof that the user's followed creators have no videos.
    if(!data["items"].empty()&&result.empty())throw Failure("API_SCHEMA");
    return result;
}
static J catalog(const std::string &op,const J &args) {
    int pn=page(args);J items=J::array();std::string next="";bool more=false;
    if(op=="recommend") {
        J d=get(API+"/x/web-interface/wbi/index/top/feed/rcmd?"+signed_query({{"fresh_idx",std::to_string(pn)},{"ps","12"},{"feed_version","V1"},{"fresh_type",pn==1?"0":"4"},{"plat","1"},{"x_num","3"},{"y_num","4"}}));
        for(auto &v:d.value("item",J::array()))if(str(v,"bvid")!="")items.push_back(card(v));more=!items.empty();
    } else if(op=="search") {
        std::string q=str(args,"query");if(q.empty()||q.size()>160)throw Failure("BAD_SEARCH");
        std::string type=str(args,"type","video");if(type!="video"&&type!="media_bangumi")throw Failure("BAD_SEARCH_TYPE");
        J d=get(API+"/x/web-interface/wbi/search/type?"+signed_query({{"keyword",q},{"search_type",type},{"page",std::to_string(pn)},{"page_size","20"},{"order","totalrank"}}));
        if(!str(d,"v_voucher").empty())throw Failure("API_VERIFICATION_REQUIRED");
        if(!d.contains("result")||!d["result"].is_array())throw Failure("API_SCHEMA");
        for(auto &v:d.value("result",J::array()))items.push_back(card(v,type=="video"?"video":"season"));more=pn<number(d,"numPages",pn);
    } else if(op=="following") {
        std::string offset=str(args,"offset");if(offset.size()>100||offset.find_first_not_of("0123456789,:")!=offset.npos)throw Failure("BAD_OFFSET");
        J d=get(API+"/x/polymer/web-dynamic/desktop/v1/feed/video?"+query({{"page",std::to_string(pn)},{"offset",offset}}));
        items=following_cards(d);
        next=str(d,"offset");more=flag(d,"has_more");
    } else if(op=="bangumi") {
        std::string cursor=str(args,"offset");if(cursor.size()>128||cursor.find_first_not_of("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-=.,:")!=cursor.npos)throw Failure("BAD_CURSOR");
        J d=get(API+"/pgc/page/pc/bangumi/tab?"+query({{"is_refresh",pn==1?"1":"0"},{"cursor",cursor}}));
        for(auto &m:d.value("modules",J::array()))for(auto &v:m.value("items",J::array())) {
            J row=card(v,"season");if(v.contains("season_id")||v.contains("ep_id"))items.push_back(row);
        }
        next=str(d,"next_cursor");more=!next.empty()&&next!=cursor;
    } else throw Failure("BAD_CATALOG");
    return J{{"items",items},{"page",pn},{"more",more},{"offset",next}};
}
static J detail(const J &args) {
    std::string kind=str(args,"kind","video");J parts=J::array(),result;
    if(kind=="video") {
        J d=get(API+"/x/web-interface/view?bvid="+bv(args));result=card(d);
        for(auto &p:d.value("pages",J::array()))parts.push_back({{"title",clean(str(p,"part"))},{"cid",str(p,"cid")},{"bvid",str(d,"bvid")},{"aid",str(d,"aid")},{"kind","video"}});
        result["description"]=clean(str(d,"desc"),1000);
        result["collection_available"]=d.contains("ugc_season")&&d["ugc_season"].is_object();
    } else {
        std::string parameter=args.contains("ep")&&str(args,"ep")!=""?"ep_id="+id(args,"ep"):"season_id="+id(args,"season");
        J d=get(API+"/pgc/view/pc/season?"+parameter);result=card(d,"season");result["description"]=clean(str(d,"evaluate"),1000);
        for(auto &p:d.value("episodes",J::array())) {
            parts.push_back({{"title",clean(str(p,"share_copy",str(p,"title")+" "+str(p,"long_title")))},{"ep",str(p,"id")},
                             {"bvid",str(p,"bvid")},{"cid",str(p,"cid")},{"aid",str(p,"aid")},{"kind","episode"},{"badge",clean(str(p,"badge"),30)}});
        }
    }
    result["parts"]=parts;return result;
}
static std::string media_url(std::string value) {
    value=https(value);std::string h=host(value);
    if(!(domain(h,"bilivideo.com")||domain(h,"bilivideo.cn")||domain(h,"acgvideo.com")||domain(h,"biliapi.net")))throw Failure("MEDIA_HOST_UNSUPPORTED");return value;
}
static std::string stream_url(const J &row) {
    std::vector<std::string> urls;
    for(const char *name:{"baseUrl","base_url","url"}){auto s=str(row,name);if(!s.empty())urls.push_back(s);}
    for(const char *name:{"backupUrl","backup_url"})if(row.contains(name)&&row[name].is_array())
        for(auto &v:row[name])if(v.is_string())urls.push_back(v.get<std::string>());
    // Some primary MCDN links are IP literals / nonstandard ports. Prefer an
    // ordinary certificate-verified CDN backup, never relax the host boundary.
    for(auto &url:urls){try{return media_url(url);}catch(const Failure&){}}
    throw Failure("MEDIA_HOST_UNSUPPORTED");
}
static void validate_qr(const std::string &url,const std::string &key) {
    // The official generate endpoint now also returns account.bilibili.com.
    // Keep an exact two-origin HTTPS boundary; do not allow arbitrary subdomains.
    std::string h=host(url);
    if(url.size()>2048||(h!="passport.bilibili.com"&&h!="account.bilibili.com")||
       !std::regex_match(key,std::regex("[0-9A-Za-z_-]{8,128}")))throw Failure("QR_SCHEMA");
}
#include "api_extensions.hpp"
static J self_test() {
    int count=0;auto require=[&](bool value){if(!value)throw Failure("INTERNAL_SELF_TEST");count++;};
    const std::string safe="https://upos-example.bilivideo.com/test.m4s";
    require(stream_url({{"baseUrl","https://10.0.0.1:4483/blocked"},{"backupUrl",J::array({safe})}})==safe);
    require(stream_url({{"base_url",safe}})==safe);
    require(stream_url({{"url","http://upos-example.bilivideo.com/test.m4s"}})==safe);
    require(stream_url({{"baseUrl","https://[::1]:4483/blocked"},{"backup_url",J::array({safe})}})==safe);
    for(const char *blocked:{"https://127.0.0.1/test","https://evil.test/test","https://bilivideo.com.evil.test/test","file:///etc/passwd","https://user:secret@upos-example.bilivideo.com/test","https://upos-example.bilivideo.com:4483/test"}){
        bool refused=false;try{stream_url({{"url",blocked}});}catch(const Failure&){refused=true;}require(refused);
    }
    require(flag(J{{"is_drm",true}},"is_drm"));require(flag(J{{"is_drm",1}},"is_drm"));require(!flag(J{{"is_drm",0}},"is_drm"));
    for(const char *url:{"https://passport.bilibili.com/scan","https://account.bilibili.com/scan"}){validate_qr(url,"FAKE_TEST_KEY");require(true);}
    for(const char *url:{"https://evil.test/scan","https://account.bilibili.com.evil.test/scan","https://evil.account.bilibili.com/scan","http://account.bilibili.com/scan","https://user:secret@account.bilibili.com/scan","https://account.bilibili.com:444/scan"}){
        bool refused=false;try{validate_qr(url,"FAKE_TEST_KEY");}catch(const Failure&){refused=true;}require(refused);
    }
    for(const char *key:{"","bad/key"}){bool refused=false;try{validate_qr("https://account.bilibili.com/scan",key);}catch(const Failure&){refused=true;}require(refused);}
    J flat={{"bvid","BV1Da411Y7U4"},{"title","Synthetic fixture"},{"pic","https://i0.hdslb.com/example.jpg"},{"owner",{{"name","Fixture owner"}}}};
    auto flat_cards=following_cards({{"items",J::array({flat})}});
    require(flat_cards.size()==1&&str(flat_cards[0],"bvid")=="BV1Da411Y7U4");require(str(flat_cards[0],"up")=="Fixture owner");
    J wrapped={{"modules",{{"module_dynamic",{{"major",{{"archive",flat}}}}},{"module_author",{{"name","Wrapped fixture"}}}}}};
    auto mixed=following_cards({{"items",J::array({flat,wrapped})}});require(mixed.size()==2&&str(mixed[1],"up")=="Wrapped fixture");
    require(following_cards({{"items",J::array()}}).empty());require(following_cards({{"items",nullptr}}).empty());
    for(const auto &bad:{J{{"items","not a list"}},J{{"items",J::array({J{{"unexpected",true}}})}}}){bool refused=false;try{following_cards(bad);}catch(const Failure&){refused=true;}require(refused);}
    extension_selftest(require);
    return J{{"checks",count},{"network_used",false},{"account_used",false}};
}
static J play(const J &args) {
    int q=quality_arg(args),codec=codec_arg(args);J d=play_data(args,q?q:16);
    std::string video,audio;int width=0,height=0;
    int chosen_quality=0,chosen_codec=7;
    if(d.contains("dash")&&d["dash"].is_object()) {
        int64_t best=INT64_MAX;
        for(auto &v:d["dash"].value("video",J::array()))if(stream_supported(v)&&(!codec||codec==number(v,"codecid"))&&(!q||q==number(v,"id"))) {
            int c=number(v,"codecid");int64_t rate=v.value("bandwidth",int64_t(0));if(rate<0||rate>200000000)continue;
            // Auto is conservative: AVC first, then lowest bandwidth. An
            // explicit codec never silently falls back to another encoding.
            if(!codec&&c!=7)rate+=1000000000LL;
            if(rate<best){try{auto chosen=stream_url(v);best=rate;video=chosen;width=number(v,"width");height=number(v,"height");chosen_quality=number(v,"id");chosen_codec=c;}catch(const Failure&){}}
        }
        best=INT64_MAX;
        for(auto &v:d["dash"].value("audio",J::array())) {int64_t rate=v.value("bandwidth",int64_t(0));if(rate<best){try{auto chosen=stream_url(v);best=rate;audio=chosen;}catch(const Failure&){}}}
        if(d["dash"].contains("audio")&&!d["dash"]["audio"].empty()&&audio.empty())throw Failure("MEDIA_HOST_UNSUPPORTED");
    } else if(d.contains("durl")&&d["durl"].is_array()&&d["durl"].size()==1) {
        chosen_quality=number(d,"quality");if((!q||q==chosen_quality)&&(!codec||codec==7)&&quality_supported(chosen_quality))video=stream_url(d["durl"][0]);
    }
    if(video.empty())throw Failure(codec?"CODEC_UNAVAILABLE":q?"QUALITY_UNAVAILABLE":"NO_SUPPORTED_STREAM");
    return J{{"video",media_url(video)},{"audio",audio.empty()?"":media_url(audio)},{"width",width},{"height",height},
             {"quality",chosen_quality},{"codec",chosen_codec},{"codec_preference",codec},{"qualities",quality_list(d,codec)["items"]},{"codecs",quality_list(d)["codecs"]},{"preview",flag(d,"is_preview")}};
}
#include "api_account.hpp"
#include "api_media_actions.hpp"
#include "api_catalog.hpp"
static J operation(const J &input) {
    std::string op=str(input,"op");J args=input.value("args",J::object());
    if(op=="self_test"){auto result=self_test();result["account_form_checks"]=account_form_selftest();result["media_action_checks"]=media_action_selftest();return result;}
    if(op=="media_context")return media_context(args);
    if(op=="danmaku_send")return danmaku_send(args);
    if(op=="watch_heartbeat")return watch_heartbeat(args);
    if(op=="recommend"||op=="search"||op=="following"||op=="bangumi")return catalog(op,args);
    if(op=="detail")return detail(args);
    if(op=="play")return play(args);
    if(op=="qualities")return quality_list(play_data(args,127),codec_arg(args));
    if(op=="story")return story(args);
    if(op=="comments")return comments(args);
    if(op=="relation")return account_relation(args);
    if(op=="season_relation")return season_relation(args);
    if(op=="season_follow")return season_follow(args);
    if(op=="favorites")return account_folders(args);
    if(op=="interaction")return account_interaction(args);
    if(op=="account_history")return account_history(args);
    if(op=="catalog_library")return catalog_library(args);
    if(op=="player_metadata"){auto r=player_metadata(args);for(auto&t:r["tracks"])t.erase("url");return r;}
    if(op=="player_subtitle")return player_subtitle(args);
    if(op=="player_preview")return player_preview(args);
    if(op=="live_catalog")return live_catalog(args);
    if(op=="live_detail")return live_detail(args);
    if(op=="live_danmaku_info")return live_danmaku_info(args);
    if(op=="live_play")return live_play(args);
    if(op=="password_challenge")return password_challenge();
    if(op=="password_login")return password_login(args);
    if(op=="status") {
        J raw=parse(request(API+"/x/web-interface/nav").body);J d=raw.value("data",J::object());
        return J{{"logged_in",flag(d,"isLogin")},{"name",clean(str(d,"uname"),60)}};
    }
    if(op=="qr_new") {
        J d=get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate");std::string url=str(d,"url"),key=str(d,"qrcode_key");
        validate_qr(url,key);
        auto code=qrcodegen::QrCode::encodeText(url.c_str(),qrcodegen::QrCode::Ecc::LOW);J matrix=J::array();
        for(int y=0;y<code.getSize();y++){std::string row;for(int x=0;x<code.getSize();x++)row+=code.getModule(x,y)?'1':'0';matrix.push_back(row);}
        return J{{"qr_key",key},{"matrix",matrix},{"expires",180}};
    }
    if(op=="qr_poll") {
        std::string key=str(args,"key");if(!std::regex_match(key,std::regex("[0-9A-Za-z_-]{8,128}")))throw Failure("BAD_QR_KEY");
        auto r=request("https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key="+encode(key));
        J d=data(parse(r.body));int code=number(d,"code",-1);return J{{"code",code},{"cookies",code==0?J(r.cookies):J::array()}};
    }
    throw Failure("UNKNOWN_OPERATION");
}
#include "media_prefetch.hpp"
#include "media_prefix.hpp"
int main() {
    prctl(PR_SET_PDEATHSIG,SIGTERM);
    const char *owner=getenv("P011_OWNER_PID");
    if(owner&&getppid()!=atoi(owner))return 90;
    alarm(45);curl_global_init(CURL_GLOBAL_DEFAULT);
    try {
        std::string input;char ch;
        while(std::cin.get(ch)){if(input.size()>=16384)throw Failure("INPUT_TOO_LARGE");input+=ch;}
        J req=parse(input);
        if(str(req,"op")=="media_stream")return stream_media(req.value("args",J::object()));
        if(str(req,"op")=="prefetch_prefix") {std::cout<<J{{"ok",true},{"data",prefetch_prefix(req.value("args",J::object()))}}.dump()<<std::endl;return 0;}
        if(str(req,"op")=="prefetch") {std::cout<<J{{"ok",true},{"data",prefetch_media(req.value("args",J::object()))}}.dump()<<std::endl;return 0;}
        if(str(req,"op")=="image") {auto r=request(str(req.value("args",J::object()),"url"),false);std::cout.write(r.body.data(),r.body.size());return 0;}
        if(str(req,"op")=="danmaku_xml") {auto r=request(API+"/x/v1/dm/list.so?oid="+id(req.value("args",J::object()),"cid"));std::cout.write(r.body.data(),r.body.size());return 0;}
        std::cout<<J{{"ok",true},{"data",operation(req)}}.dump()<<std::endl;return 0;
    } catch(const Failure &e){std::cout<<J{{"ok",false},{"error",e.what()},{"code",e.code}}.dump()<<std::endl;return 0;}
    catch(...){std::cout<<"{\"ok\":false,\"error\":\"API_SCHEMA_OR_INTERNAL\",\"code\":-1}"<<std::endl;return 0;}
}
