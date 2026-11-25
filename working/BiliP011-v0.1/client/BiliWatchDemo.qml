// SPDX-License-Identifier: GPL-3.0-or-later
// Explicit user-requested audible demonstration, never loaded by default.
import QtQuick 2.7
Item {
    id: demo
    property var target: null
    property int stage: 0
    property bool pending: false
    property bool done: false
    property double started: Date.now()
    property double playingAt: 0
    function finish() {
        if (done) return;
        done = true;
        if (target) target.quitTrial();
    }
    function tick() {
        if (!target || done) return;
        if (Date.now()-started > 240000 || playingAt && Date.now()-playingAt >= @DEMO_SECONDS@*1000) { finish(); return; }
        if (!target.token || pending) return;
        if (stage === 0) {
            if (target.busy) return;
            stage = 1;
            target.details({kind:"video", bvid:"BV1gi4y1V7Xx"}, "detail");
            return;
        }
        if (stage === 1) {
            if (target.busy) return;
            if (!target.partCount) { finish(); return; }
            target.selectedQuality = 116;
            target.selectedCodec = 7;
            target.playPart(0);
            stage = 2;
            return;
        }
        pending = true;
        target.http("GET", "/state", null, function(s) {
            pending = false;
            var p = s.player || {};
            if (p.loaded && p.active && !playingAt) {
                playingAt = Date.now();
                console.log("P011_BILI_DEMO PLAYING");
            }
            if (!s.playing && !s.preparing && (playingAt || s.play_end)) finish();
        }, false);
    }
    Timer { interval:1000; repeat:true; running:!demo.done; onTriggered:demo.tick() }
}
