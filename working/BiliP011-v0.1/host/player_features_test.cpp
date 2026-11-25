// Synthetic-only timed subtitle and serial boundary regression.
#include "../client/player_features.hpp"
#include <cassert>
#include <iostream>
int main(){
    using J=nlohmann::json;p011_player::Features f;
    f.page="subtitles";auto request=f.request("player_subtitle",J::object(),10);
    J cues=J::array({J{{"start",1},{"end",3},{"text","first"}},J{{"start",3},{"end",5},{"text","second"}}});
    J packet={{"op","feature"},{"serial",1},{"seq",request["seq"]},{"feature","player_subtitle"},{"ok",true},{"data",{{"track","123"},{"cues",cues}}}};
    assert(f.accept(packet));assert(f.subtitle(.9).empty());assert(f.subtitle(1)=="first");assert(f.subtitle(3)=="second");assert(f.subtitle(5).empty());
    f.subtitle_offset=.5;assert(f.subtitle(1.4).empty());assert(f.subtitle(1.5)=="first");
    f.close();assert(f.subtitle(1.5)=="first");f.reset(2);assert(f.subtitle(1.5).empty());assert(!f.accept(packet));
    p011_player::Layout l;for(const char*page:{"subtitles","chapters","subtitle-settings"}){
        f.page=page;auto buttons=f.buttons(l);assert(buttons.size()>=4);for(auto&b:buttons)assert(b.box.h>=44&&b.box.w>=80);
    }
    std::cout<<"timed media serial, seek, offset, controls passed\n";
}
