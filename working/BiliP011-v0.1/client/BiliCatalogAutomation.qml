// SPDX-License-Identifier: GPL-3.0-or-later
// Isolated public playback, numeric account API checks; never account screenshots.
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
    property double at:Date.now()
    property double position:0
    property var checks:[]
    property var tasks:[]
    property var apiErrors:[]
    function next(s){stage=s;at=Date.now();}
    function check(n,ok){if(!ok)throw "ASSERTION";checks.push(n);}
    function item(n){var todo=[target];while(todo.length){var q=todo.pop();if(q.objectName===n)return q;if(q.children)for(var i=0;i<q.children.length;i++)todo.push(q.children[i]);}throw "INPUT_FAILED";}
    function command(a){pending=true;target.http("POST","/player/test",{action:a},function(r){pending=false;if(!r.ok)finish(false,"INPUT_FAILED");},false);}
    function capture(n){if(target.playing||target.screen!=="library"||["popular","weekly","timeline"].indexOf(item("biliLibrary").category)<0)throw "INPUT_FAILED";target.opacity=.99;shot.wait(100);target.opacity=1;shot.wait(120);var image=shot.grabImage(target.Window.window.contentItem);if(image.width!==800||image.height!==480)throw "INPUT_FAILED";image.save("@REMOTE@/screenshots/"+n+".png");}
    function checkpoint(kind){pending=true;target.http("POST","/qa/features",{phase:"checkpoint",kind:kind},function(r){pending=false;if(!r.ok)finish(false,"ASSERTION");},false);}
    function finish(ok,error){if(finished)return;finished=true;function done(){target.http("POST","/qa/features",{phase:"finish",passed:ok,error:error,stage:stage,checks:checks},function(r){target.quitTrial();},false);}if(ok)done();else target.http("POST","/player/stop",{},done,false);}
    function query(){
        if(!tasks.length){check("catalog-apis",apiErrors.length===0);target.details({kind:"video",bvid:"BV1Jt411P77c"},"detail");next(5);return;}
        var a=tasks.shift();pending=true;
        target.job("catalog_library",a,function(r){pending=false;
            if(!r.ok){apiErrors.push(a.category);finish(false,"API_FAILED");return;}
            var rows=r.data.items||[];
            if(rows.length&&a.category==="folders")tasks.push({category:"folder",id:rows[0].id,page:1},{category:"folder",id:rows[0].id,page:2});
            if(rows.length&&a.category==="weekly")tasks.push({category:"week",id:rows[0].id});
            if(rows.length&&a.category==="followings")tasks.push({category:"up",id:rows[0].id});
        });
    }
    function tick(){
        if(!target||!target.token||pending||finished)return;
        if(Date.now()-started>520000||Date.now()-at>95000){finish(false,"TIMEOUT");return;}
        if(!claimed){pending=true;target.http("POST","/qa/start",{},function(r){pending=false;if(!r.ok){finished=true;return;}claimed=true;next(0);},false);return;}
        pending=true;target.http("GET","/state",null,function(s){pending=false;try{run(s);}catch(e){finish(false,["ASSERTION","INPUT_FAILED"].indexOf(String(e))>=0?String(e):"QML_EXCEPTION");}},false);
    }
    function run(s){var p=s.player||{},lib=item("biliLibrary");switch(stage){
        case 0:if(target.busy)return;target.libraryPage("popular",{});next(1);break;
        case 1:if(lib.busy||Date.now()-at<2000)return;check("public-library",lib.rows.length>0&&!lib.note);capture("catalog-popular");lib.open("weekly",{},false);next(2);break;
        case 2:if(lib.busy||Date.now()-at<2000)return;check("catalog-navigation",lib.rows.length>0);capture("catalog-weekly");lib.open("timeline",{},false);next(3);break;
        case 3:if(lib.busy||Date.now()-at<1500)return;capture("catalog-timeline");tasks=[{category:"ranking"},{category:"weekly"},{category:"watchlater"},{category:"folders"},{category:"followings"},{category:"related",bvid:"BV1Da411Y7U4"},{category:"collection",bvid:"BV1Da411Y7U4"},{category:"my_bangumi"},{category:"live_following"}];next(4);break;
        case 4:query();break;
        case 5:if(target.busy)return;if(target.partCount<2)throw "ASSERTION";target.selectedQuality=32;target.selectedCodec=7;target.playPart(1,true,false);next(6);break;
        case 6:if(!s.playing&&!s.preparing&&!target.busy&&Date.now()-at>5000){finish(false,"API_FAILED");return;}if(!p.active||p.position<4)return;check("subtitle-playing",p.hardware_backend&&p.hardware_verified&&p.muted);command("more");next(7);break;
        case 7:command("menu-next");next(8);break;
        case 8:command("menu-next");next(9);break;
        case 9:command("feature-subtitles");next(10);break;
        case 10:if(p.feature_busy||!p.subtitle_tracks)return;command("feature-select");next(11);break;
        case 11:if(p.feature_busy||!p.subtitle_cues)return;check("subtitle-loaded",p.subtitle_enabled);command("capture_subtitles");next(12);break;
        case 12:command("feature-sub-settings");next(13);break;
        case 13:command("feature-sub-size+");next(14);break;
        case 14:command("feature-sub-delay+");next(15);break;
        case 15:command("capture_subtitle_settings");next(16);break;
        case 16:check("subtitle-controls",p.active);command("feature-close");next(17);break;
        case 17:command("video_seek_hold");next(18);break;
        case 18:if(p.feature_busy||!p.preview_images)return;check("preview-image",p.preview_images>0);command("capture_timed_preview");next(19);break;
        case 19:checkpoint("subtitle");next(20);break;
        case 20:command("gesture_release");next(21);break;
        case 21:if(!p.active||p.switch_pending)return;command("rate_150");next(22);break;
        case 22:if(!p.active||p.switch_pending||p.playback_rate!==1.5)return;position=p.position;next(23);break;
        case 23:if(Date.now()-at<10000)return;check("rate-clock",p.active&&p.position-position>=12&&p.position-position<=18&&p.hardware_backend);checkpoint("rate");next(24);break;
        case 24:command("rate_100");next(25);break;
        case 25:if(!p.active||p.switch_pending||p.playback_rate!==1)return;check("rate-reset",p.subtitle_cues>0);command("hold_rate_start");next(40);break;
        case 40:if(!p.active||p.switch_pending||!p.hold_rate_active||p.playback_rate!==2)return;position=p.position;next(41);break;
        case 41:if(Date.now()-at<6000)return;check("hold-rate-clock",p.position-position>=9&&p.position-position<=15&&p.hold_rate_active);command("hold_rate_release");next(42);break;
        case 42:if(!p.active||p.switch_pending||p.hold_rate_restore_pending||p.playback_rate!==1)return;check("hold-rate-restored",!p.hold_rate_active&&p.hold_rate_restores===1);checkpoint("hold-rate");next(45);break;
        case 45:command("hold_rate_start");next(43);break;
        case 43:if(Date.now()-at<1100)return;command("hold_rate_release");next(44);break;
        case 44:if(!p.active||p.switch_pending||p.hold_rate_restore_pending||p.playback_rate!==1)return;check("hold-rate-early-release",!p.hold_rate_active&&p.hold_rate_restores===2);command("back");next(26);break;
        case 26:if(s.playing)return;if(s.play_exit_code!==0)throw "ASSERTION";target.details({kind:"video",bvid:"BV1seYteFEvy"},"detail");next(27);break;
        case 27:if(target.busy||target.playing)return;if(!target.partCount)throw "ASSERTION";target.selectedQuality=32;target.selectedCodec=7;target.playPart(0,true,false);next(28);break;
        case 28:if(!s.playing&&!s.preparing&&!target.busy&&Date.now()-at>5000){finish(false,"API_FAILED");return;}if(!p.active||p.generation!==2||p.position<3)return;command("more");next(29);break;
        case 29:command("menu-next");next(30);break;
        case 30:command("menu-next");next(31);break;
        case 31:command("feature-chapters");next(32);break;
        case 32:if(p.feature_busy||!p.chapter_count)return;check("chapter-list",p.chapter_count>0);command("capture_chapters");next(33);break;
        case 33:command("feature-next");next(34);break;
        case 34:command("feature-select");next(35);break;
        case 35:if(!p.active||p.switch_pending||!p.seek_actions)return;check("chapter-jump",p.hardware_verified&&p.subtitle_cues===0);checkpoint("chapter");next(36);break;
        case 36:command("back");next(37);break;
        case 37:if(s.playing)return;check("clean-exits",s.play_exit_code===0);pending=true;target.job("interaction",{bvid:"BV1Da411Y7U4",action:"watchlater",value:true,intent:"00000000000000000000000000000000"},function(r){pending=false;try{check("writes-blocked",!r.ok&&r.error==="ACTION_DISABLED");}catch(e){finish(false,"ASSERTION");}});next(38);break;
        case 38:pending=true;target.job("danmaku_send",{bvid:"BV1Da411Y7U4",cid:"1",position:0,message:"NEVER SENT",mode:1,intent:"00000000000000000000000000000000"},function(r){pending=false;try{check("danmaku-write-blocked",!r.ok&&r.error==="ACTION_DISABLED");}catch(e){finish(false,"ASSERTION");}});next(46);break;
        case 46:pending=true;target.job("cloud_enable",{value:true,intent:"00000000000000000000000000000000"},function(r){pending=false;try{check("cloud-write-blocked",!r.ok&&r.error==="ACTION_DISABLED");finish(true,"");}catch(e){finish(false,"ASSERTION");}});next(47);break;
    }}
    TestEvent{id:touch}
    TestResult{id:shot}
    Timer{interval:550;repeat:true;running:!qa.finished;onTriggered:qa.tick()}
}
