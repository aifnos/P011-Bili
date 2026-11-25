// SPDX-License-Identifier: GPL-3.0-or-later
// Finite explicit muted public-page acceptance. No login/account operations.
import QtQuick 2.7
import QtQuick.Window 2.2
import QtTest 1.2
Item {
    id:qa
    property var target:null
    property bool pending:false
    property bool claimed:false
    property bool finished:false
    property int stage:0
    property double started:Date.now()
    property double stageStarted:Date.now()
    property double seekBase:0
    property var checks:[]
    function check(n,ok){if(!ok)throw "ASSERTION";checks.push(n);}
    function next(n){stage=n;stageStarted=Date.now();console.log("P011_STORY_STAGE "+stage);}
    function item(name){var list=[target];while(list.length){var q=list.pop();if(q.objectName===name&&q.visible)return q;if(q.children)for(var i=0;i<q.children.length;i++)list.push(q.children[i]);}throw "INPUT_FAILED";}
    function command(a){pending=true;target.http("POST","/player/test",{action:a},function(r){pending=false;if(!r.ok)finish(false,"INPUT_FAILED");},false);}
    function observe(to){pending=true;target.http("POST","/qa/state",{phase:"observe"},function(r){pending=false;if(!r.ok){finish(false,"CHECKPOINT_FAILED");return;}next(to);},false);}
    function capture(name,to){
        // The vendor's Item FBO grab is not the actual 800x480 window.
        // Match the already-verified public-page window capture mechanism.
        target.opacity=.99;shot.wait(100);target.opacity=1;shot.wait(120);
        var image=shot.grabImage(target.Window.window.contentItem);
        if(image.width!==800||image.height!==480)throw "ASSERTION";
        image.save("@REMOTE@/screenshots/"+name+".png");next(to);
    }
    function finish(ok,error){if(finished)return;finished=true;function report(){target.http("POST","/qa/state",{phase:"finish",passed:ok,error:error,stage:stage,checks:checks},function(r){target.quitTrial();},false);}if(ok)report();else target.http("POST","/player/stop",{},function(r){report();},false);}
    function tick(){
        if(!target||!target.token||pending||finished)return;
        if(Date.now()-started>300000||Date.now()-stageStarted>60000){finish(false,"TIMEOUT");return;}
        pending=true;
        if(!claimed){target.http("POST","/qa/start",{},function(r){pending=false;if(!r.ok){finished=true;return;}claimed=true;target.qaMode=true;next(0);},false);return;}
        target.http("GET","/state",null,function(s){pending=false;try{run(s);}catch(e){finish(false,["ASSERTION","INPUT_FAILED"].indexOf(String(e))>=0?String(e):"QML_EXCEPTION");}},false);
    }
    function run(s){var p=s.player||{};switch(stage){
    case 0:if(target.busy)return;check("discovery",item("biliLibraryOpen").label==="发现");target.libraryPage("popular",{});next(1);break;
    case 1:var lib=item("biliLibraryList");if(!lib.count)return;capture("catalog-popular",2);break;
    case 2:target.libraryPage("weekly",{});next(3);break;
    case 3:if(!item("biliLibraryList").count)return;check("weekly",true);capture("catalog-weekly",4);break;
    case 4:target.job("play",{story:true,quality:32,codec:7},function(r){if(!r.ok)finish(false,"INPUT_FAILED");});next(5);break;
    case 5:if(!p.active||p.position<2||!p.portrait)return;check("story-playing",p.muted&&p.hardware_verified&&p.prefix_cache_capable);next(6);break;
    case 6:if(p.prefetch_completed<2||!p.active||p.switch_pending)return;check("two-prefixes",true);observe(7);break;
    case 7:command("capture_story");next(25);break;
    case 25:command("swipe_next");next(8);break;
    case 8:if(!p.active||p.switch_pending||p.video_switches<1||p.position<2)return;check("cached-next",p.cached_media&&p.prefetch_media_hits>=1);observe(9);break;
    case 9:command("swipe_next");next(10);break;
    case 10:if(!p.active||p.switch_pending||p.video_switches<2||p.position<7)return;check("cached-second",p.cached_media&&p.prefetch_media_hits>=2);check("tail-continuation",p.relay_tail_bytes>0);observe(11);break;
    case 11:command("capture_story_next");next(26);break;
    case 26:command("swipe_previous");next(12);break;
    case 12:if(!p.active||p.switch_pending||p.video_switches<3||p.position<2)return;check("cached-back",p.cached_media&&p.prefetch_media_hits>=3);observe(13);break;
    case 13:command("more");next(14);break;
    case 14:if(p.menu!==2)return;command("menu-next");next(15);break;
    case 15:command("rotate");next(16);break;
    case 16:if(p.portrait||p.menu||!p.active)return;check("landscape",true);command("capture_landscape");next(17);break;
    case 17:if(Date.now()-stageStarted<12000)return;command("feature-comments");next(18);break;
    case 18:if(!p.feature_comment_reads||p.feature_busy)return;check("comments",true);command("capture_comments");next(19);break;
    case 19:command("feature-close");next(20);break;
    case 20:if(p.menu)return;command("rate-menu");next(21);break;
    case 21:if(p.menu!==9)return;check("rate-menu",true);command("close");next(22);break;
    case 22:if(p.menu||!p.active||p.switch_pending)return;seekBase=p.video_seek_actions||0;command("seek+");next(23);break;
    case 23:if(!p.loaded||p.switch_pending||p.video_seek_actions<=seekBase)return;check("swipe-seek",true);command("back");next(24);break;
    case 24:if(s.playing||s.play_exit_code!==0)return;check("exit",true);finish(true,"");break;
    }}
    Timer{interval:400;running:!qa.finished;repeat:true;onTriggered:qa.tick()}
    TestResult{id:shot}
}
