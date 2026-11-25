.pragma library
// SPDX-License-Identifier: GPL-3.0-or-later
// Shared small-screen presentation and bounded, pure navigation helpers.
var background = "#101115";
var surface = "#1b1d24";
var raised = "#242630";
var accent = "#fb7299";
var selected = "#ad4269";
var foreground = "#f5f5f7";
var secondary = "#a7a9b7";
var muted = "#858896";
function identity(row) { return row.kind === "season" ? "ss:" + row.season : row.kind === "episode" ? "ep:" + row.ep : "bv:" + row.bvid; }
function playlist(rows, video, parts, index) {
    var result=[],at=-1,i;
    // Multi-part titles must advance to the next part, not an unrelated card.
    if(parts.length>1) {
        var start=Math.max(0,Math.min(index-8,parts.length-24));
        for(i=start;i<Math.min(parts.length,start+24);i++)result.push(parts[i]);
        return {rows:result,index:index-start};
    }
    var videos=[];
    for(i=0;i<rows.length;i++)if(rows[i].kind==="video") {if(rows[i].bvid===video.bvid)at=videos.length;videos.push(rows[i]);}
    if(at>=0) {
        var first=Math.max(0,Math.min(at-8,videos.length-24));
        for(i=first;i<Math.min(videos.length,first+24);i++)result.push({kind:"video",bvid:videos[i].bvid});
        return {rows:result,index:at-first};
    }
    return {rows:[parts[index]],index:0};
}
function stamp(seconds) {var s=Math.max(0,Math.floor(seconds||0));return Math.floor(s/60)+":"+(s%60<10?"0":"")+s%60;}
