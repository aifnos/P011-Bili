// SPDX-License-Identifier: GPL-3.0-or-later
// Fixed, read-only official contracts. No browser-supplied URLs or credentials.
#pragma once
static J catalog_slice(const J& rows,int pn){
    if(!rows.is_array()||rows.size()>10000)throw Failure("API_SCHEMA");
    J out=J::array();size_t begin=size_t(pn-1)*20,end=std::min(rows.size(),begin+20);
    for(size_t i=begin;i<end;i++)out.push_back(rows[i]);
    return {{"items",out},{"more",end<rows.size()},{"page",pn}};
}
static J collection_rows(const J&d){
    J rows=J::array();auto season=d.value("ugc_season",J::object());
    if(!season.is_object())return rows;
    for(auto&s:season.value("sections",J::array()))for(auto&e:s.value("episodes",J::array())){
        J r=card(e.value("arc",e.value("archive",e)));
        r["bvid"]=str(e,"bvid",str(r,"bvid"));r["title"]=clean(str(e,"title",str(r,"title")));
        r["cid"]=str(e,"cid");if(std::regex_match(str(r,"bvid"),std::regex("BV[0-9A-Za-z]{10}")))rows.push_back(r);
        if(rows.size()>=10000)return rows;
    }return rows;
}
static J catalog_library(const J&a){
    const auto kind=str(a,"category");const int pn=page(a);J rows=J::array(),d;bool more=false;
    std::string title;
    if(kind=="watchlater"){
        account_nav();d=get(API+"/x/v2/history/toview/web");for(auto&r:d.value("list",J::array()))rows.push_back(card(r));
    }else if(kind=="folders"){
        auto nav=account_nav();d=get(API+"/x/v3/fav/folder/created/list-all?up_mid="+id(nav,"mid"));
        auto list=d.value("list",J::array());if(list.is_null())list=J::array();
        for(auto&r:list)rows.push_back({{"kind","folder"},{"id",id(r,"id")},{"title",clean(str(r,"title"))},{"subtitle",std::to_string(number(r,"media_count"))+" 个视频"}});
    }else if(kind=="folder"){
        account_nav();d=get(API+"/x/v3/fav/resource/list?"+query({{"media_id",id(a,"id")},{"pn",std::to_string(pn)},{"ps","20"},{"platform","web"}}));
        auto list=d.value("medias",J::array());if(list.is_null())list=J::array();
        for(auto&r:list){auto row=card(r);if(r.contains("upper")){row["up"]=clean(str(r["upper"],"name"));row["mid"]=str(r["upper"],"mid");}rows.push_back(row);}more=flag(d,"has_more");
        return {{"items",rows},{"more",more},{"page",pn},{"title",clean(str(d.value("info",J::object()),"title"))}};
    }else if(kind=="followings"){
        auto nav=account_nav();d=get(API+"/x/relation/followings?"+query({{"vmid",id(nav,"mid")},{"pn",std::to_string(pn)},{"ps","20"}}));
        for(auto&r:d.value("list",J::array()))rows.push_back({{"kind","up"},{"id",id(r,"mid")},{"title",clean(str(r,"uname"))},{"subtitle",clean(str(r,"sign"),180)},{"cover",https(str(r,"face"))}});
        return {{"items",rows},{"more",pn*20<number(d,"total")},{"page",pn}};
    }else if(kind=="up"){
        auto mid=id(a,"id");J profile=get(API+"/x/space/wbi/acc/info?"+signed_query({{"mid",mid}}));
        d=get(API+"/x/space/wbi/arc/search?"+signed_query({{"mid",mid},{"pn",std::to_string(pn)},{"ps","20"},{"order","pubdate"}}));
        for(auto&r:d.value("list",J::object()).value("vlist",J::array())){auto row=card(r);row["mid"]=mid;rows.push_back(row);}
        return {{"items",rows},{"more",pn*20<number(d.value("page",J::object()),"count")},{"page",pn},{"title",clean(str(profile,"name"))},{"description",clean(str(profile,"sign"),240)},{"following",flag(profile,"is_followed")}};
    }else if(kind=="popular"){
        d=get(API+"/x/web-interface/popular?"+query({{"pn",std::to_string(pn)},{"ps","20"}}));
        for(auto&r:d.value("list",J::array()))rows.push_back(card(r));return {{"items",rows},{"more",!flag(d,"no_more")&&!rows.empty()},{"page",pn}};
    }else if(kind=="ranking"){
        d=get(API+"/x/web-interface/ranking/v2?rid=0&type=all");for(auto&r:d.value("list",J::array()))rows.push_back(card(r));
    }else if(kind=="weekly"){
        d=get(API+"/x/web-interface/popular/series/list");for(auto&r:d.value("list",J::array()))rows.push_back({{"kind","week"},{"id",id(r,"number")},{"title",clean(str(r,"name"))},{"subtitle",clean(str(r,"subject"))}});
    }else if(kind=="week"){
        d=get(API+"/x/web-interface/popular/series/one?"+signed_query({{"number",id(a,"id")}}));for(auto&r:d.value("list",J::array()))rows.push_back(card(r));
    }else if(kind=="related"){
        d=get(API+"/x/web-interface/archive/related?bvid="+bv(a));if(!d.is_array())throw Failure("API_SCHEMA");for(auto&r:d)rows.push_back(card(r));
    }else if(kind=="collection"){
        d=get(API+"/x/web-interface/view?bvid="+bv(a));rows=collection_rows(d);title=clean(str(d.value("ugc_season",J::object()),"title"));
    }else if(kind=="my_bangumi"){
        auto nav=account_nav();d=get(API+"/x/space/bangumi/follow/list?"+query({{"vmid",id(nav,"mid")},{"pn",std::to_string(pn)},{"ps","20"},{"type","1"}}));
        for(auto&r:d.value("list",J::array())){auto row=card(r,"season");row["subtitle"]=clean(str(r.value("new_ep",J::object()),"index_show"));rows.push_back(row);}
        return {{"items",rows},{"more",pn*20<number(d,"total")},{"page",pn}};
    }else if(kind=="timeline"){
        d=get(API+"/pgc/web/timeline?types=1&before=6&after=6");if(!d.is_array())throw Failure("API_SCHEMA");
        for(auto&day:d)for(auto&r:day.value("episodes",J::array())){auto row=card(r,"season");row["ep"]=str(r,"episode_id");row["subtitle"]=str(day,"date")+" "+str(r,"pub_time")+" · "+clean(str(r,"pub_index"));rows.push_back(row);}
    }else if(kind=="live_following"){
        account_nav();d=get(LIVE+"/xlive/web-ucenter/v1/xfetter/GetWebList?"+query({{"page",std::to_string(pn)},{"page_size","20"}}));
        for(auto&r:d.value("list",J::array())){auto row=live_row(r);row["subtitle"]=number(r,"live_status")==1?"正在直播":"暂未开播";rows.push_back(row);}
        return {{"items",rows},{"more",pn*20<number(d,"total")},{"page",pn}};
    }else throw Failure("BAD_CATALOG");
    J result=catalog_slice(rows,pn);result["title"]=title;return result;
}
static J player_metadata(const J&a){
    J d=get(API+"/x/player/wbi/v2?"+signed_query({{"bvid",bv(a)},{"cid",id(a,"cid")}}));
    J tracks=J::array(),chapters=J::array();
    for(auto&r:d.value("subtitle",J::object()).value("subtitles",J::array())){
        auto key=str(r,"id_str",str(r,"id"));if(!digits(key))continue;
        tracks.push_back({{"id",key},{"language",clean(str(r,"lan"),40)},{"label",clean(str(r,"lan_doc"),80)},{"ai",number(r,"ai_type")>0||str(r,"lan").rfind("ai-",0)==0},{"url",https(str(r,"subtitle_url"))}});
        if(tracks.size()>=32)break;
    }
    for(auto&r:d.value("view_points",J::array()))if(r.contains("from")&&r["from"].is_number()&&r.contains("to")&&r["to"].is_number()){
        double start=r["from"],end=r["to"];if(!std::isfinite(start)||!std::isfinite(end)||start<0||end<=start||end>604800)continue;
        chapters.push_back({{"start",start},{"end",end},{"title",clean(str(r,"content"),180)}});if(chapters.size()>=200)break;
    }
    return {{"tracks",tracks},{"chapters",chapters}};
}
static J player_subtitle(const J&a){
    auto selected=id(a,"track");auto meta=player_metadata(a);
    for(auto&r:meta["tracks"])if(str(r,"id")==selected){
        auto url=str(r,"url");J raw=parse(request(url,false).body),cues=J::array();
        auto list=raw.value("body",J::array());if(!list.is_array()||list.size()>12000)throw Failure("API_SCHEMA");
        for(auto&c:list)if(c.contains("from")&&c["from"].is_number()&&c.contains("to")&&c["to"].is_number()){
            double from=c["from"],to=c["to"];if(!std::isfinite(from)||!std::isfinite(to)||from<0||to<=from||to>604800)continue;
            cues.push_back({{"start",from},{"end",to},{"text",clean(str(c,"content"),600)}});
        }return {{"cues",cues},{"track",selected}};
    }throw Failure("BAD_INPUT");
}
static J player_preview(const J&a){
    if(!a.contains("position")||!a["position"].is_number())throw Failure("BAD_INPUT");
    double time=a["position"];if(!std::isfinite(time)||time<0||time>604800)throw Failure("BAD_INPUT");
    J d=get(API+"/x/player/videoshot?"+query({{"bvid",bv(a)},{"cid",id(a,"cid")},{"index","1"}}));
    auto times=d.value("index",J::array()),images=d.value("image",J::array());
    int w=number(d,"img_x_size"),h=number(d,"img_y_size"),cols=number(d,"img_x_len"),rows=number(d,"img_y_len");
    if(!times.is_array()||times.empty()||times.size()>20000||!images.is_array()||images.size()>200||w<1||h<1||w>640||h>360||cols<1||rows<1||cols>100||rows>100)throw Failure("FEATURE_UNAVAILABLE");
    size_t at=0;double previous=-1;
    for(size_t i=0;i<times.size();i++){
        if(!times[i].is_number())throw Failure("API_SCHEMA");double t=times[i];
        if(!std::isfinite(t)||t<previous||t>604800)throw Failure("API_SCHEMA");previous=t;if(t<=time)at=i;
    }
    if(time<times[0].get<double>())throw Failure("FEATURE_UNAVAILABLE");
    const size_t per=size_t(cols)*rows,sheet=at/per,cell=at%per;
    if(sheet>=images.size()||!images[sheet].is_string())throw Failure("FEATURE_UNAVAILABLE");
    auto raw=request(https(images[sheet].get<std::string>()),false).body;
    if(raw.size()>450000)throw Failure("RESOURCE_LIMIT");
    std::string encoded(4*((raw.size()+2)/3)+1,'\0');int used=EVP_EncodeBlock(reinterpret_cast<unsigned char*>(&encoded[0]),reinterpret_cast<const unsigned char*>(raw.data()),int(raw.size()));encoded.resize(used);
    return {{"jpeg",encoded},{"x",int(cell%cols)*w},{"y",int(cell/cols)*h},{"w",w},{"h",h},{"start",times[at]},{"end",at+1<times.size()?times[at+1]:J(604800)}};
}
