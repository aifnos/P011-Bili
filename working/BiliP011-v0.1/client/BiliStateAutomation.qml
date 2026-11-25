// SPDX-License-Identifier: GPL-3.0-or-later
// Explicit isolated, muted state probe. Never enters account/QR pages.
import QtQuick 2.7
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
    property double savedPosition:0
    property double pausedPosition:0
    property var checks:[]
    function check(name,ok){if(!ok)throw "ASSERTION";checks.push(name);}
    function next(value){stage=value;stageStarted=Date.now();}
    function item(name){var list=[target];while(list.length){var q=list.pop();if(q.objectName===name&&q.visible)return q;if(q.children)for(var i=0;i<q.children.length;i++)list.push(q.children[i]);}throw "INPUT_FAILED";}
    function click(name){var q=item(name);if(!q.enabled||!touch.mouseClick(q,q.width/2,q.height/2,Qt.LeftButton,Qt.NoModifier,20))throw "INPUT_FAILED";}
    function command(action){pending=true;target.http("POST","/player/test",{action:action},function(r){pending=false;if(!r.ok)finish(false,"INPUT_FAILED");},false);}
    function observe(to){pending=true;target.http("POST","/qa/state",{phase:"observe"},function(r){pending=false;if(!r.ok){finish(false,"CHECKPOINT_FAILED");return;}savedPosition=r.position;target.refreshLibrary();next(to);},false);}
    function finish(ok,error){
        if(finished)return;finished=true;
        function report(){target.http("POST","/qa/state",{phase:"finish",passed:ok,error:error,stage:stage,checks:checks},function(r){target.quitTrial();},false);}
        if(ok)report();else target.http("POST","/player/stop",{},function(r){report();},false);
    }
    function tick(){
        if(!target||!target.token||pending||finished)return;
        if(Date.now()-started>240000||Date.now()-stageStarted>45000){finish(false,"TIMEOUT");return;}
        pending=true;
        if(!claimed){target.http("POST","/qa/start",{},function(r){pending=false;if(!r.ok){finished=true;return;}claimed=true;target.qaMode=true;next(0);},false);return;}
        target.http("GET","/state",null,function(s){pending=false;try{run(s);}catch(e){finish(false,["ASSERTION","INPUT_FAILED"].indexOf(String(e))>=0?String(e):"QML_EXCEPTION");}},false);
    }
    function run(s){
        var p=s.player||{};
        switch(stage){
        case 0:
            if(target.busy||!target.libraryAvailable)return;
            target.details({kind:"video",bvid:"BV1Da411Y7U4"},"detail");next(1);break;
        case 1:
            if(target.busy)return;check("details",target.screen==="detail"&&target.partCount>0);
            target.selectedQuality=32;target.selectedCodec=7;click("biliPlayPrimary");next(2);break;
        case 2:
            if(p.generation!==1||!p.active||p.position<3)return;
            check("playing",p.muted&&p.loaded);check("avc-hardware",p.hardware_backend&&p.hardware_verified);
            command("seek+");next(3);break;
        case 3:
            if(!p.active||p.position<17)return;command("pause");next(15);break;
        case 15:
            if(!p.paused||p.switch_pending)return;pausedPosition=p.position;command("ux_unavailable_stream");next(16);break;
        case 16:
            if(p.switch_recoveries<1||p.switch_pending||!p.loaded)return;
            check("failed-switch-restored",p.switch_failures===1&&p.switch_recoveries===1&&p.hardware_verified&&p.quality_switches===0);
            check("paused-position-retained",p.paused&&Math.abs(p.position-pausedPosition)<1.5);
            command("back");next(4);break;
        case 4:
            if(s.playing||s.play_exit_code!==0)return;observe(5);break;
        case 5:
            if(target.busy||target.resumePosition<15)return;
            check("history-saved",target.localHistory.length===1);check("resume-ui",Math.abs(target.resumePosition-savedPosition)<1.5&&item("biliPlayRestart").visible);
            click("biliPlayPrimary");next(6);break;
        case 6:
            if(p.generation!==2||!p.active||!p.hardware_verified||p.submitted_frames<25)return;
            check("resume-playing",p.position>=savedPosition-1&&p.position<savedPosition+12);command("back");next(7);break;
        case 7:
            if(s.playing||s.play_exit_code!==0)return;observe(8);break;
        case 8:
            if(target.busy||target.resumePosition<15)return;
            check("restart-ui",item("biliPlayRestart").visible);click("biliPlayRestart");next(9);break;
        case 9:
            if(p.generation!==3||!p.active||p.position<3)return;
            check("from-start",p.position<8&&p.hardware_verified);command("back");next(10);break;
        case 10:
            if(s.playing||s.play_exit_code!==0)return;observe(11);break;
        case 11:
            target.historyPage();next(12);break;
        case 12:
            if(target.busy)return;check("history-visible",target.screen==="history"&&target.localHistory.length===1);
            click("biliHistoryClear");check("clear-confirm",target.clearConfirm==="history"&&target.localHistory.length===1);
            click("biliHistoryClear");next(13);break;
        case 13:
            if(target.localHistory.length||target.clearConfirm)return;
            if(Date.now()-stageStarted<17000)return;target.refreshLibrary();next(14);break;
        case 14:
            if(Date.now()-stageStarted<1500)return;check("clear-complete",target.localHistory.length===0);finish(true,"");break;
        }
    }
    TestEvent{id:touch}
    Timer{interval:450;running:!qa.finished;repeat:true;onTriggered:qa.tick()}
}
