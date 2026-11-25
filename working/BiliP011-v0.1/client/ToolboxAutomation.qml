// Candidate-only Qt events. Uses isolated generated files, never personal files.
import QtQuick 2.7
Item {
    id:qa
    property var driver:null
    property var checks:[]
    property int stage:0
    property double started:0
    property bool running:false
    property bool stepping:false
    signal completed(bool passed)
    function begin(d){driver=d;started=Date.now();running=true;}
    function mark(name,value){if(!value)throw "ASSERTION";checks.push(name);}
    function click(name){driver.click(name);}
    function capture(name){driver.capture(name);}
    function item(name){return driver.item(name);}
    function tick(){
        if(stepping)return;
        stepping=true;
        try{stepOnce();}finally{stepping=false;}
    }
    function stepOnce(){
        if(!running)return;
        if(Date.now()-started>95000){running=false;completed(false);return;}
        try{
            var shell=driver.target.toolboxShell,app=shell.toolbox;
            if(!app||!app.connected)return;
            var page=item("featureLoader").item;
            if(page&&page.loading)return;
            switch(stage){
            case 0:mark("home",!shell.biliShown&&app.biliAvailable);capture("toolbox-home");click("homeFiles");break;
            case 1:mark("files",page&&page.directory==="");mark("lan-off",!app.telemetry.transfer.enabled);capture("toolbox-files");click("fileFolderText");break;
            case 2:if(!page.entries.length)return;click("fileEntry0");break;
            case 3:if(page.selected.kind!=="text")return;mark("text",page.selected.text.indexOf("小屏幕")>=0);capture("toolbox-text");click("backButton");break;
            case 4:if(page.directory){click("backButton");return;}click("fileFolderPictures");break;
            case 5:if(!page.entries.length)return;click("fileEntry0");break;
            case 6:if(item("imagePreview").status!==Image.Ready)return;mark("image",page.selected.kind==="image");capture("toolbox-image");click("backButton");click("backButton");click("backButton");click("homeGames");break;
            // Exercise input while running, then freeze the simulation for
            // capture. Slow screenshot backends must not run Snake into a
            // wall and turn its Pause button unavailable mid-test.
            case 7:mark("snake",page.game==="snake");mark("large-controls",item("gameUpButton").width>=130&&item("gameUpButton").height>=90);click("gamePauseButton");click("gameUpButton");click("gamePauseButton");capture("toolbox-snake");click("mergeButton");break;
            case 8:mark("2048",page.game==="2048");click("gamePauseButton");click("gameLeftButton");click("gamePauseButton");capture("toolbox-2048");click("bricksButton");break;
            case 9:mark("bricks",page.game==="bricks");click("gamePauseButton");click("brickRightButton");mark("game-controls",page.state.paddle>300);click("gamePauseButton");capture("toolbox-bricks");click("gameBackButton");click("homeDashboard");break;
            case 10:if(!page.metrics.memory)return;mark("dashboard",page.metrics.memory.total>0);capture("toolbox-dashboard");click("chartToggle");break;
            case 11:mark("curves",page.history.length>1);capture("toolbox-curves");click("backButton");click("processToggle");break;
            case 12:if(!page.processes.length)return;mark("processes",page.mode==="processes");capture("toolbox-processes");click("backButton");click("headerAction");click("exportSamples");break;
            case 13:if(app.message.indexOf("已保存")<0)return;mark("export",true);app.message="";click("backButton");click("backButton");mark("toolbox-back",app.pageName==="");click("homeBili");break;
            case 14:mark("bili-entry",shell.biliShown&&driver.target.visible);running=false;completed(true);return;
            }stage++;
        }catch(e){running=false;completed(false);}
    }
    Timer{interval:700;running:qa.running;repeat:true;onTriggered:qa.tick()}
}
