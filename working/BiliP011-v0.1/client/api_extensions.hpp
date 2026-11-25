// SPDX-License-Identifier: GPL-3.0-or-later
// Included after the confined request/normalization helpers in api.cpp.
#pragma once
// IDs are service data, not a resolution whitelist. Existence/permission is
// checked against the actual DASH/durl response, never accept_quality alone.
static bool quality_supported(int q) {return q>0&&q<=65535;}
static int codec_arg(const J&args){int c=number(args,"codec",0);if(args.contains("codec")&&!args["codec"].is_number_integer())throw Failure("BAD_INPUT");if(c!=0&&c!=7&&c!=12&&c!=13)throw Failure("BAD_INPUT");return c;}
static const char*codec_name(int c){return c==7?"AVC":c==12?"HEVC":c==13?"AV1":"自动 · AVC优先";}
static bool codec_supported(int c){return c==7||c==12||c==13;}
static int quality_arg(const J &args) {
    if(args.contains("quality")&&!args["quality"].is_number_integer())throw Failure("BAD_INPUT");
    int q=number(args,"quality",0);if(q&&!quality_supported(q))throw Failure("BAD_INPUT");return q;
}
static std::string quality_name(int q) {
    switch(q){case 0:return "自动 · 流畅优先";case 6:return "240P";case 16:return "360P";case 32:return "480P";case 64:return "720P";case 74:return "720P60";case 80:return "1080P";case 112:return "1080P+";case 116:return "1080P60";case 120:return "4K";case 125:return "HDR";case 126:return "杜比视界";case 127:return "8K";default:return "画质 "+std::to_string(q);}
}
static std::string quality_description(const J&d,int q){
    if(d.contains("support_formats")&&d["support_formats"].is_array())for(const auto&r:d["support_formats"]){
        if(number(r,"quality")==q){auto label=clean(str(r,"new_description",str(r,"display_desc",str(r,"description"))),48);if(!label.empty())return label;}
    }
    if(d.contains("accept_quality")&&d["accept_quality"].is_array()&&d.contains("accept_description")&&d["accept_description"].is_array())
        for(size_t i=0;i<d["accept_quality"].size()&&i<d["accept_description"].size();i++)if(d["accept_quality"][i]==q&&d["accept_description"][i].is_string())return clean(d["accept_description"][i].get<std::string>(),48);
    return quality_name(q);
}
static J play_data(const J &args,int q) {
    J d;
    if(str(args,"kind")=="episode")d=get(API+"/pgc/player/web/playurl?"+query({{"ep_id",id(args,"ep")},{"qn",std::to_string(q)},{"fnval","4048"},{"fourk","1"}}));
    else d=get(API+"/x/player/wbi/playurl?"+signed_query({{"bvid",bv(args)},{"cid",id(args,"cid")},{"qn",std::to_string(q)},{"fnval","4048"},{"fourk","1"}}));
    if(flag(d,"is_drm")||flag(d,"drm_tech_type"))throw Failure("DRM_UNSUPPORTED");return d;
}
static bool stream_supported(const J&v){return quality_supported(number(v,"id"))&&codec_supported(number(v,"codecid"));}
static J quality_list(const J &d,int codec=0) {
    if(flag(d,"is_drm")||flag(d,"drm_tech_type"))throw Failure("DRM_UNSUPPORTED");
    std::set<int> ids,codecs;J variants=J::array();
    if(d.contains("dash")&&d["dash"].is_object()) {
        for(const auto &v:d["dash"].value("video",J::array())) {
            int q=number(v,"id"),c=number(v,"codecid");if(stream_supported(v))
                try{stream_url(v);codecs.insert(c);variants.push_back({{"quality",q},{"codec",c},{"width",number(v,"width")},{"height",number(v,"height")}});if(!codec||codec==c)ids.insert(q);}catch(const Failure&){}
        }
    } else if(d.contains("durl")&&d["durl"].is_array()&&d["durl"].size()==1&&quality_supported(number(d,"quality"))) {
        stream_url(d["durl"][0]);if(!codec||codec==7)ids.insert(number(d,"quality"));codecs.insert(7);
    }
    if(ids.empty())throw Failure("NO_SUPPORTED_STREAM");
    J rows=J::array();rows.push_back({{"id",0},{"label",quality_name(0)}});
    for(int q:ids)rows.push_back({{"id",q},{"label",quality_description(d,q)}});
    J cs=J::array({{{"id",0},{"label",codec_name(0)}}});for(int c:codecs)cs.push_back({{"id",c},{"label",codec_name(c)}});
    return {{"items",rows},{"preview",flag(d,"is_preview")},{"codecs",cs},{"variants",variants},{"codec",codec}};
}
static J story(const J&args){
    int display=number(args,"page",1);if(display<1||display>10000)throw Failure("BAD_INPUT");
    std::map<std::string,std::string> params={{"display_id",std::to_string(display)}};
    std::string idx=str(args,"offset");if(!idx.empty()){if(!digits(idx))throw Failure("BAD_OFFSET");params["idx"]=idx;}
    J d=get("https://app.bilibili.com/x/v2/feed/index/story?"+query(params));
    if(!d.contains("items")||!d["items"].is_array())throw Failure("API_SCHEMA");J rows=J::array();
    for(const auto&r:d["items"]){
        if(rows.size()>=20)break;if(!r.is_object()||(str(r,"goto")!="vertical_av"&&str(r,"goto")!="av")||r.contains("ad_info"))continue;
        J p=r.value("player_args",J::object());std::string cid=str(p,"cid"),bid=str(r,"bvid");
        if(!digits(cid)||!std::regex_match(bid,std::regex("BV[0-9A-Za-z]{10}")))continue;
        J v=card(r);v["kind"]="video";v["cid"]=cid;v["bvid"]=bid;v["aid"]=str(p,"aid");
        v["up"]=clean(str(r.value("owner",J::object()),"name"),120);rows.push_back(v);
        std::string next=str(r,"idx");if(digits(next))idx=next;
    }
    return {{"items",rows},{"offset",idx},{"more",!rows.empty()},{"source","official-story"},{"page",display}};
}
static J comment_row(const J &raw,bool pinned=false) {
    if(!raw.is_object()||!raw.contains("content")||!raw["content"].is_object())throw Failure("API_SCHEMA");
    std::string rpid=str(raw,"rpid_str",str(raw,"rpid"));if(!digits(rpid))throw Failure("API_SCHEMA");
    J member=raw.value("member",J::object());
    return {{"id",rpid},{"author",clean(str(member,"uname","用户"),120)},
            {"text",clean(str(raw["content"],"message"),3600)},
            {"likes",std::max(0,number(raw,"like"))},{"replies",std::max(0,number(raw,"rcount"))},
            {"pinned",pinned}};
}
static J comment_list(const J &d) {
    if(!str(d,"v_voucher").empty())throw Failure("API_VERIFICATION_REQUIRED");
    if(!d.contains("cursor")||!d["cursor"].is_object())throw Failure("API_SCHEMA");
    J rows=J::array();std::set<std::string> seen;
    J source=d;
    if(d.contains("root")) {
        if(!d["root"].is_object())throw Failure("API_SCHEMA");
        source["replies"]=d["root"].value("replies",J::array());
        source["top_replies"]=J::array();
    }
    for(const char *key:{"top_replies","replies"}) {
        if(!source.contains(key)||source[key].is_null())continue;
        if(!source[key].is_array())throw Failure("API_SCHEMA");
        for(const auto &r:source[key]) {
            if(rows.size()>=40)break;
            J row=comment_row(r,std::string(key)=="top_replies");
            if(seen.insert(str(row,"id")).second)rows.push_back(row);
        }
    }
    auto cursor=d["cursor"];return {{"items",rows},{"next",std::max(0,number(cursor,"next"))},
        {"more",!flag(cursor,"is_end")},{"total",std::max(0,number(cursor,"all_count"))}};
}
static J comments(const J &args) {
    std::string aid=str(args,"aid");
    if(aid.empty())aid=str(get(API+"/x/web-interface/view?bvid="+bv(args)),"aid");
    if(!digits(aid))throw Failure("BAD_ID");
    int mode=number(args,"mode",3),next=number(args,"next",0);
    if((mode!=2&&mode!=3)||next<0||next>1000000000)throw Failure("BAD_INPUT");
    std::string rpid=str(args,"root");
    std::map<std::string,std::string> params={{"type","1"},{"oid",aid},{"next",std::to_string(next)},{"mode",std::to_string(mode)},{"plat","1"}};
    if(!rpid.empty()){if(!digits(rpid))throw Failure("BAD_ID");params["root"]=rpid;}
    J d=get(API+(rpid.empty()?"/x/v2/reply/main?":"/x/v2/reply/detail?")+query(params));
    J result=comment_list(d);result["aid"]=aid;return result;
}
static J parse_danmaku(const std::string &xml) {
    // Legacy public XML pool, as used by pinned wiliwili. Deliberately not an
    // XML engine: never resolves DTD/entities/URLs. Bound scan and text memory.
    if(xml.size()>4*1024*1024 || xml.find("<!DOCTYPE")!=xml.npos || xml.find("<!ENTITY")!=xml.npos || xml.find("<i>")==xml.npos)throw Failure("API_SCHEMA");
    J rows=J::array();size_t at=0;int total=0;
    while((at=xml.find("<d p=\"",at))!=xml.npos) {
        size_t fields=at+6,quote=xml.find("\">",fields),end=xml.find("</d>",fields);
        if(quote==xml.npos||end==xml.npos||quote>end||quote-fields>256)break;
        at=end+4;total++;
        if(rows.size()>=2000 || end-quote>4096)continue;
        std::string p=xml.substr(fields,quote-fields);std::vector<std::string> values;
        size_t prev=0;
        for(int i=0;i<4;i++){size_t comma=p.find(',',prev);values.push_back(p.substr(prev,comma==p.npos?p.size()-prev:comma-prev));if(comma==p.npos)break;prev=comma+1;}
        if(values.size()<4)continue;
        try {
            size_t used=0;double time=std::stod(values[0],&used);if(used!=values[0].size()||!std::isfinite(time)||time<0||time>86400)continue;
            int mode=std::stoi(values[1]);if(mode!=1&&mode!=4&&mode!=5&&mode!=6)continue;
            int color=std::stoi(values[3]);if(color<0||color>0xffffff)continue;
            std::string text=clean(xml.substr(quote+2,end-quote-2),180);
            if(!text.empty())rows.push_back({{"time",time},{"mode",mode},{"color",color},{"text",text}});
        } catch(const std::exception&) {continue;}
    }
    std::stable_sort(rows.begin(),rows.end(),[](const J &a,const J &b){return a["time"].get<double>()<b["time"].get<double>();});
    return {{"items",rows},{"truncated",total>int(rows.size())},{"source","public-pool"}};
}
template<class Check> static void extension_selftest(Check require) {
    const std::string safe="https://upos-example.bilivideo.com/test.m4s";
    require(quality_arg(J::object())==0);require(quality_arg({{"quality",32}})==32);
    for(auto bad:{J{{"quality",true}},J{{"quality",65536}},J{{"quality",-1}}}) {
        bool refused=false;try{quality_arg(bad);}catch(const Failure&){refused=true;}require(refused);
    }
    J d={{"dash",{{"video",J::array({J{{"id",32},{"codecid",7},{"baseUrl",safe}},
        J{{"id",64},{"codecid",12},{"baseUrl",safe}},J{{"id",80},{"codecid",7},{"baseUrl","https://evil.test/test"}}})}}}};
    auto qualities=quality_list(d,7);require(qualities["items"].size()==2);require(number(qualities["items"][1],"id")==32);require(qualities["codecs"].size()==3);require(quality_arg({{"quality",120}})==120);
    require(qualities.dump().find("https:")==std::string::npos);
    J extended={{"dash",{{"video",J::array({J{{"id",127},{"codecid",13},{"width",7680},{"height",4320},{"baseUrl",safe}},J{{"id",333},{"codecid",7},{"baseUrl",safe}}})}}},
        {"support_formats",J::array({J{{"quality",333},{"new_description","未来画质"}},J{{"quality",999},{"new_description","未授权"}}})}};
    auto eq=quality_list(extended);require(eq["items"].size()==3);require(str(eq["items"][2],"label")=="未来画质");require(number(eq["items"][1],"id")==127);require(quality_arg({{"quality",333}})==333);
    J r={{"rpid_str","123"},{"member",{{"uname","Synthetic"}}},{"content",{{"message","Long <b>text</b>"}}},{"rcount",2}};
    auto c=comment_list({{"cursor",{{"next",2},{"is_end",true}}},{"top_replies",J::array({r})},{"replies",J::array({r})}});
    require(c["items"].size()==1);require(str(c["items"][0],"text")=="Long text");require(flag(c["items"][0],"pinned"));require(!flag(c,"more"));
    auto nested=comment_list({{"cursor",{{"next",2},{"is_end",true}}},{"root",{{"replies",J::array({r})}}}});
    require(nested["items"].size()==1);require(!flag(nested["items"][0],"pinned"));
    require(card({{"duration",422}})["duration"]=="7:02");
    auto dm=parse_danmaku("<i><d p=\"1.25,1,25,16777215,0,0,user,1\">Hi &amp; text</d><d p=\"0.5,5,25,1\">早</d><d p=\"nan,1,25,1\">reject</d></i>");
    require(dm["items"].size()==2);require(str(dm["items"][1],"text")=="Hi & text");require(dm["items"][0]["time"].get<double>()==.5);
    require(dm.dump().find("user")==std::string::npos);
    for(const char *bad:{"<!DOCTYPE x><i></i>","<!ENTITY x><i></i>","not XML"}){bool refused=false;try{parse_danmaku(bad);}catch(const Failure&){refused=true;}require(refused);}
}
