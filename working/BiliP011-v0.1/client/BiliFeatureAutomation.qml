// SPDX-License-Identifier: GPL-3.0-or-later
// Public pages only. No credentials, account mutation or captcha solving.
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
    property var liveRow:({})
    property var checks:[]
    property var webProbe:null
    property string webResult:"pending"
    function next(s){stage=s;at=Date.now();}
    function check(n,ok){if(!ok)throw "ASSERTION";checks.push(n);}
    function item(n){var todo=[target];while(todo.length){var q=todo.pop();if(q.objectName===n&&q.visible)return q;if(q.children)for(var i=0;i<q.children.length;i++)todo.push(q.children[i]);}throw "INPUT_FAILED";}
    function click(n){var q=item(n);if(!q.enabled||!touch.mouseClick(q,q.width/2,q.height/2,Qt.LeftButton,Qt.NoModifier,20))throw "INPUT_FAILED";}
    function command(a){pending=true;target.http("POST","/player/test",{action:a},function(r){pending=false;if(!r.ok)finish(false,"INPUT_FAILED");},false);}
    function capture(n){if(target.playing||target.screen==="login"||target.screen==="extra"&&item("biliExtras").page!=="live")throw "INPUT_FAILED";target.opacity=.99;shot.wait(100);target.opacity=1;shot.wait(120);var image=shot.grabImage(target.Window.window.contentItem);if(image.width!==800||image.height!==480)throw "INPUT_FAILED";image.save("@REMOTE@/screenshots/"+n+".png");}
    function checkpoint(kind){pending=true;target.http("POST","/qa/features",{phase:"checkpoint",kind:kind},function(r){pending=false;if(!r.ok)finish(false,"ASSERTION");},false);}
    function finish(ok,error){if(finished)return;finished=true;if(webProbe){webProbe.destroy();webProbe=null;}function done(){target.http("POST","/qa/features",{phase:"finish",passed:ok,error:error,stage:stage,checks:checks,password_environment:webResult},function(r){target.quitTrial();},false);}if(ok)done();else target.http("POST","/player/stop",{},done,false);}
    function tick(){
        if(!target||!target.token||pending||finished)return;
        if(Date.now()-started>370000||Date.now()-at>90000){finish(false,"TIMEOUT");return;}
        if(!claimed){pending=true;target.http("POST","/qa/start",{},function(r){pending=false;if(!r.ok){finished=true;return;}claimed=true;next(0);},false);return;}
        pending=true;target.http("GET","/state",null,function(s){pending=false;try{run(s);}catch(e){finish(false,["ASSERTION","INPUT_FAILED"].indexOf(String(e))>=0?String(e):"QML_EXCEPTION");}},false);
    }
    function run(s){var p=s.player||{};switch(stage){
        case 0:if(target.busy)return;target.catalog("live_catalog");next(1);break;
        case 1:if(target.busy)return;if(Date.now()-at<3200||target.pendingCovers&&Date.now()-at<15000)return;check("live-catalog",target.rows.length>0&&item("biliCover0").status===Image.Ready);liveRow=target.rows[0];capture("feature-live-list");target.details(liveRow,"detail");next(2);break;
        case 2:if(item("biliExtras").busy)return;check("live-detail",item("biliLivePlay").available);capture("feature-live-detail");target.details({kind:"video",bvid:"BV1R7eg6gEnJ"},"detail");next(3);break;
        case 3:if(target.busy)return;if(!target.partCount)throw "ASSERTION";target.selectedQuality=32;target.selectedCodec=7;click("biliPlayPrimary");next(4);break;
        case 4:if(!p.active||p.position<4)return;check("video-playing",p.muted&&p.loaded);check("avc-hardware",p.hardware_backend&&p.hardware_verified);command("more");next(5);break;
        case 5:command("menu-next");next(6);break;
        case 6:command("menu-next");next(7);break;
        case 7:command("feature-comments");next(8);break;
        case 8:if(p.feature_busy||!p.feature_comment_reads)return;check("comments-in-player",p.menu===8&&p.active);checkpoint("comments");next(9);break;
        case 9:command("capture_comments");next(10);break;
        case 10:if(Date.now()-at<1200)return;command("feature-close");next(11);break;
        case 11:if(p.menu!==0)return;check("comments-close",p.active);command("more");next(12);break;
        case 12:command("menu-next");next(13);break;
        case 13:command("menu-next");next(14);break;
        case 14:command("listen");next(15);break;
        case 15:if(!p.active||!p.listen||p.hardware_backend)return;check("listen-audio-only",p.pulse_observed&&p.muted);position=p.position;command("capture_listen");next(16);break;
        case 16:if(Date.now()-at<67000)return;check("listen-continues",p.active&&p.listen&&p.position>position+58);checkpoint("listen");next(17);break;
        case 17:command("more");next(18);break;
        case 18:command("menu-next");next(19);break;
        case 19:command("menu-next");next(20);break;
        case 20:command("listen");next(21);break;
        case 21:if(!p.active||p.listen||!p.hardware_verified)return;check("video-return",p.hardware_backend&&p.muted);checkpoint("video-return");next(22);break;
        case 22:command("back");next(23);break;
        case 23:if(s.playing)return;check("first-clean-exit",s.play_exit_code===0);target.details(liveRow,"detail");next(24);break;
        case 24:if(item("biliExtras").busy)return;click("biliLivePlay");next(25);break;
        case 25:if(!p.active||p.generation!==2||p.position<8)return;check("live-playing",p.live&&p.muted&&p.pulse_observed);command("capture_live");next(26);break;
        case 26:command("seek+");next(27);break;
        case 27:if(Date.now()-at<61000)return;check("live-no-seek",p.live&&p.seek_actions===0&&p.active);check("live-websocket-auth",s.live_danmaku&&s.live_danmaku.ever_authenticated);check("live-websocket-heartbeat",s.live_danmaku.heartbeats>0);checkpoint("live");next(28);break;
        case 28:command("back");next(29);break;
        case 29:if(s.playing)return;check("second-clean-exit",s.play_exit_code===0);pending=true;target.job("interaction",{bvid:"BV1Da411Y7U4",action:"like",value:true,intent:"00000000000000000000000000000000"},function(r){pending=false;try{check("account-writes-blocked",!r.ok&&r.error==="ACTION_DISABLED");next(30);}catch(e){finish(false,"ASSERTION");}});next(30);break;
        case 30:
            var component=Qt.createComponent("BiliCaptcha.qml");
            if(component.status!==Component.Ready){webResult="component-unavailable";finish(true,"");return;}
            webProbe=component.createObject(qa,{width:800,height:268,visible:false});
            if(!webProbe){webResult="instance-unavailable";finish(true,"");return;}
            webProbe.environmentReady.connect(function(){webResult="bridge-ready";});
            webProbe.unavailable.connect(function(){webResult="load-unavailable";});
            webProbe.probe();next(31);break;
        case 31:if(webResult!=="pending"||Date.now()-at>12000){if(webResult==="pending")webResult="bridge-timeout";finish(true,"");}break;
    }}
    TestEvent{id:touch}
    // The factory process provides native helpers, not qmltestrunner's singleton.
    TestResult{id:shot}
    Timer{interval:550;repeat:true;running:!qa.finished;onTriggered:qa.tick()}
}
