// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/progress_overlay.hpp"
#include <iostream>
using namespace p011_player;
int main() {
    unsigned checks=0;
    auto check=[&](bool value){if(!value)throw checks;++checks;};
    try {
        check(progress_overlay_selftest());
        ProgressOverlay p;
        p.playback(0,false);check(p.visible(0));check(p.visible(90000));
        p.playback(90000,true);check(p.visible(90000));check(p.visible(92999));check(!p.visible(93000));
        p.playback(93001,true);check(!p.visible(93001)); // no timer reset every frame
        p.tap(93002);check(p.visible(93002));check(p.visible(96001));check(!p.visible(96002));
        p.reveal(97000);check(p.visible(97000));p.tap(97001);check(!p.visible(97001));
        p.playback(97002,false);check(p.visible(97002));check(p.visible(990000));
        p.tap(990001);check(!p.visible(990001));p.playback(990002,false);check(!p.visible(990002));
        p.playback(990003,true);check(p.visible(990003));check(!p.visible(993003));
        p.reveal(993004);check(p.visible(993004)); // seek or volume action
        ProgressOverlay wrap;wrap.playback(0xfffffc18u,true); // wrap after 1,000 ms
        check(wrap.visible(1998));check(!wrap.visible(2000));
        std::cout<<"{\"checks\":"<<checks<<",\"passed\":true,\"device_tested\":false}\n";
        return 0;
    } catch(unsigned at) {
        std::cout<<"{\"failed_check\":"<<at<<",\"passed\":false,\"device_tested\":false}\n";
        return 1;
    }
}
