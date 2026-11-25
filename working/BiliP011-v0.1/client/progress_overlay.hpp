// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

namespace p011_player {
class ProgressOverlay {
    std::uint32_t shown_at_ = 0;
    bool initialized_ = false, progressing_ = false, manually_hidden_ = false;
public:
    static constexpr std::uint32_t hide_after_ms = 3000;
    void reveal(std::uint32_t now) { shown_at_ = now; manually_hidden_ = false; }
    void playback(std::uint32_t now, bool progressing) {
        // Starting, pausing, resuming or buffering reveals useful status again.
        if (!initialized_ || progressing != progressing_) reveal(now);
        initialized_ = true; progressing_ = progressing;
    }
    bool visible(std::uint32_t now) const {
        return !manually_hidden_ && (!progressing_ ||
            std::uint32_t(now-shown_at_) < hide_after_ms);
    }
    void tap(std::uint32_t now) {
        if (visible(now)) manually_hidden_ = true;
        else reveal(now);
    }
};

// Called by the exact frozen ARM player's no-window preflight, as well as by
// PC tests. No SDL, display, audio, API or account interaction.
inline bool progress_overlay_selftest() {
    ProgressOverlay p;
    p.playback(0,false);
    if(!p.visible(20000))return false;
    p.playback(20000,true);
    if(!p.visible(22999)||p.visible(23000))return false;
    p.tap(23001);if(!p.visible(23001))return false;
    p.tap(23002);if(p.visible(23002))return false;
    p.playback(23003,false);if(!p.visible(50000))return false;
    p.tap(50001);if(p.visible(50001))return false;
    p.reveal(50002);if(!p.visible(50002))return false;
    return true;
}
} // namespace p011_player
