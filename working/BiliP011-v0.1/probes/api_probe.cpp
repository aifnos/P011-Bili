// Independent anonymous Bilibili network probe. GPL-3.0-or-later.
// WBI permutation follows wiliwili v1.6.0 source/api/util/wbi.cpp (GPL-3.0).
// No cookies, account state, server, downloaded video file, or PC relay.
#include <curl/curl.h>
#include <openssl/evp.h>
#include <nlohmann/json.hpp>
#include <unistd.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <ctime>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <map>
#include <stdexcept>
using Json=nlohmann::json;
static size_t append(char *data,size_t a,size_t b,void *p){
    auto &s=*static_cast<std::string*>(p);size_t n=a*b;
    if(n>2097152||s.size()>2097152-n)return 0;
    s.append(data,n);return n;
}
static Json get(const std::string &url){
    CURL *c=curl_easy_init();if(!c)throw std::runtime_error("CURL_INIT");std::string body;
    curl_easy_setopt(c,CURLOPT_URL,url.c_str());curl_easy_setopt(c,CURLOPT_USERAGENT,"wiliwili");
    curl_easy_setopt(c,CURLOPT_REFERER,"https://www.bilibili.com/client");
    curl_easy_setopt(c,CURLOPT_PROTOCOLS_STR,"https");curl_easy_setopt(c,CURLOPT_REDIR_PROTOCOLS_STR,"https");
    curl_easy_setopt(c,CURLOPT_CONNECTTIMEOUT,5L);curl_easy_setopt(c,CURLOPT_TIMEOUT,12L);
    curl_easy_setopt(c,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(c,CURLOPT_SSL_VERIFYPEER,1L);curl_easy_setopt(c,CURLOPT_SSL_VERIFYHOST,2L);
    curl_easy_setopt(c,CURLOPT_CAINFO,"/etc/ssl/certs/ca-certificates.crt");
    curl_easy_setopt(c,CURLOPT_WRITEFUNCTION,append);curl_easy_setopt(c,CURLOPT_WRITEDATA,&body);
    CURLcode rc=curl_easy_perform(c);long status=0;curl_easy_getinfo(c,CURLINFO_RESPONSE_CODE,&status);curl_easy_cleanup(c);
    if(rc!=CURLE_OK||status!=200)throw std::runtime_error("HTTPS_ERROR curl="+std::to_string(rc)+" http="+std::to_string(status));
    auto j=Json::parse(body,nullptr,false);if(j.is_discarded())throw std::runtime_error("INVALID_JSON");return j;
}
static std::string sign(std::map<std::string,std::string> params,const Json &keys){
    const int tab[]={46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13};
    std::string raw,mixin;
    for(const char *name:{"img_url","sub_url"}){std::string s=keys.at(name);auto a=s.find_last_of('/'),b=s.find_last_of('.');raw+=s.substr(a+1,b-a-1);}
    if(raw.size()!=64)throw std::runtime_error("WBI_KEY_SHAPE");
    for(int i:tab)mixin+=raw[i];
    params["wts"]=std::to_string(time(nullptr));CURL *c=curl_easy_init();std::string query;
    for(auto &p:params){std::string value;for(char v:p.second)if(std::string("!'()*").find(v)==std::string::npos)value+=v;
        char *esc=curl_easy_escape(c,value.c_str(),value.size());if(!query.empty())query+='&';query+=p.first+'='+esc;curl_free(esc);}
    curl_easy_cleanup(c);std::string input=query+mixin;unsigned char hash[EVP_MAX_MD_SIZE];unsigned n=0;
    if(!EVP_Digest(input.data(),input.size(),hash,&n,EVP_md5(),nullptr)||n!=16)throw std::runtime_error("WBI_DIGEST");
    char hex[33];for(unsigned i=0;i<n;i++)std::snprintf(hex+i*2,3,"%02x",hash[i]);return query+"&w_rid="+hex;
}
int main(int argc,char **argv){
    alarm(getenv("P011_AWAKE_SESSION")?200:125);setvbuf(stdout,nullptr,_IONBF,0);curl_global_init(CURL_GLOBAL_DEFAULT);
    try{
        auto nav=get("https://api.bilibili.com/x/web-interface/nav");auto keys=nav.at("data").at("wbi_img");
        printf("NAV_CODE=%d LOGIN=%d\n",nav.value("code",-999),nav.at("data").value("isLogin",false));
        if(argc==2 && std::string(argv[1])=="--catalog") {
            int failed=0;
            auto inspect=[&](const char *label,const std::string &url,const char *field,bool auth){
                try {
                    auto j=get(url);int code=j.value("code",-999);
                    Json data=j.contains("data")&&j["data"].is_object()?j["data"]:j.value("result",Json::object());
                    size_t count=data.is_object()&&data.contains(field)&&data[field].is_array()?data[field].size():0;
                    printf("CATALOG %s code=%d count=%zu login_required=%d\n",label,code,count,auth&&code==-101);
                    if(!auth&&(code!=0||count==0))failed++;
                } catch(...) {printf("CATALOG %s transport_or_schema_error=1\n",label);if(!auth)failed++;}
            };
            inspect("recommend","https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd?"+sign({{"fresh_idx","1"},{"ps","12"},{"feed_version","V1"},{"fresh_type","0"},{"plat","1"},{"x_num","3"},{"y_num","4"}},keys),"item",false);
            inspect("search","https://api.bilibili.com/x/web-interface/wbi/search/type?"+sign({{"keyword","树莓派"},{"search_type","video"},{"page","1"},{"page_size","20"},{"order","totalrank"}},keys),"result",false);
            inspect("bangumi","https://api.bilibili.com/pgc/page/pc/bangumi/tab?is_refresh=1&cursor=","modules",false);
            inspect("followed","https://api.bilibili.com/x/polymer/web-dynamic/desktop/v1/feed/video?page=1&offset=","items",true);
            return failed?18:0;
        }
        const std::string bv="BV1Da411Y7U4";
        auto video=get("https://api.bilibili.com/x/web-interface/view?bvid="+bv);printf("VIDEO_CODE=%d\n",video.value("code",-999));
        if(video.value("code",-999)!=0)return 11;
        auto data=video.at("data");std::string cid=std::to_string(data.at("cid").get<int64_t>());
        auto play=get("https://api.bilibili.com/x/player/wbi/playurl?"+sign({{"bvid",bv},{"cid",cid},{"qn","16"},{"fnval","4048"},{"fourk","0"}},keys));
        printf("PLAYURL_CODE=%d\n",play.value("code",-999));if(play.value("code",-999)!=0)return 12;
        auto streams=play.at("data");std::string vurl,aurl;int width=0,height=0;
        if(streams.contains("dash")){
            int64_t rate=INT64_MAX;
            for(auto &v:streams["dash"]["video"]){if(v.value("codecid",0)!=7)continue;
                int64_t next=v.value("bandwidth",int64_t(0));if(next<rate){rate=next;vurl=v.contains("baseUrl")?v["baseUrl"].get<std::string>():v["base_url"].get<std::string>();width=v.value("width",0);height=v.value("height",0);}}
            rate=INT64_MAX;
            for(auto &a:streams["dash"]["audio"]){int64_t next=a.value("bandwidth",int64_t(0));if(next<rate){rate=next;aurl=a.contains("baseUrl")?a["baseUrl"].get<std::string>():a["base_url"].get<std::string>();}}
        }else if(streams.contains("durl")&&!streams["durl"].empty())vurl=streams["durl"][0].at("url");
        auto https=[](std::string &s){if(s.rfind("http://",0)==0)s.replace(0,7,"https://");};https(vurl);https(aurl);
        printf("STREAM_SELECTED=%dx%d SEPARATE_AUDIO=%d\n",width,height,!aurl.empty());
        if(vurl.rfind("https://",0)!=0||vurl.size()>16000||aurl.size()>16000)return 13;
        if(argc==2 && std::string(argv[1])=="--play"){
            std::string exe=argv[0];exe=exe.substr(0,exe.find_last_of('/')+1)+"mpv-probe";
            int pipes[2];if(pipe(pipes))return 14;pid_t parent=getpid();pid_t child=fork();
            if(child<0)return 15;
            if(child==0){prctl(PR_SET_PDEATHSIG,SIGKILL);if(getppid()!=parent)_exit(99);dup2(pipes[0],STDIN_FILENO);close(pipes[0]);close(pipes[1]);execl(exe.c_str(),exe.c_str(),nullptr);_exit(98);}
            close(pipes[0]);std::string payload=vurl+'\n'+aurl+'\n';size_t sent=0;
            while(sent<payload.size()){ssize_t n=write(pipes[1],payload.data()+sent,payload.size()-sent);if(n<=0)break;sent+=n;}
            close(pipes[1]);int status=0;waitpid(child,&status,0);printf("PLAY_CHILD_EXIT=%d\n",WIFEXITED(status)?WEXITSTATUS(status):-1);
            return WIFEXITED(status)?WEXITSTATUS(status):16;
        }
        return 0;
    }catch(const std::exception &e){
        // JSON errors could include response data; only emit fixed categories.
        const std::string message=e.what();
        if(message.rfind("HTTPS_ERROR",0)==0||message.rfind("WBI_",0)==0||message=="INVALID_JSON")printf("PROBE_ERROR=%s\n",message.c_str());
        else puts("PROBE_ERROR=API_SCHEMA_OR_RESPONSE");return 17;
    }
}
