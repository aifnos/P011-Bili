// SPDX-License-Identifier: GPL-3.0-or-later
// Built ONLY into explicitly automated, immutable trial bundles. No Qt.quit,
// system input injection, account-page screenshots or arbitrary test commands.
import QtQuick 2.7
import QtQuick.Window 2.2
import QtTest 1.2

Item {
    id: driver
    objectName: "biliAutomation"
    property var target: null
    property bool enhanced: false
    property bool claimed: false
    property bool claiming: false
    property bool finished: false
    property bool stepping: false
    property bool toolboxStarted: false
    property bool toolboxDone: false
    property var toolboxChecks: []
    property int step: 0
    property int detailStep: 0
    property int bangumiDetail: 0
    property double started: Date.now()
    property var checks: []
    property var captures: []
    property bool nativeKeyboardReused: false
    property string lastUiMessage: ""
    property string captureDirectory: "@REMOTE@/screenshots"
    function item(name) {
        var pending=[target.toolboxShell||target],hidden=null;
        while(pending.length) {
            var value=pending.pop();
            if(value.objectName===name){if(value.visible)return value;hidden=value;}
            if(value.children) for(var i=0;i<value.children.length;i++) pending.push(value.children[i]);
        }
        if(hidden)return hidden;
        throw "MISSING_ITEM";
    }
    function click(name) {
        if(name==="biliOpen"&&target.screen!=="searchInput")click("biliSearch");
        if(["biliRecommend","biliFollowing","biliBangumi","biliSearch","biliAccount","biliStory"].indexOf(name)>=0){
            for(var n=0;n<4&&target.screen!=="catalog";n++)click("biliBack");
        }
        if(/^biliCard[0-9]+$/.test(name)) {
            // A restored tab can have the selected card before the viewport.
            // Item.visible does not mean its center is inside a clipped list.
            var list=item("biliCatalog");list.forceLayout();
            list.positionViewAtIndex(Number(name.substr(8)),ListView.Contain);
            captureHelper.wait(120);
        }
        var value=item(name);
        if(!value.visible || !value.enabled) throw "INVISIBLE_ITEM";
        if(!touch.mouseClick(value,value.width/2,value.height/2,Qt.LeftButton,Qt.NoModifier,20)) throw "INVISIBLE_ITEM";
    }
    function check(name,value) {
        if(!value) throw "ASSERTION";
        checks.push(name);
    }
    function capture(name) {
        if(target.screen==="login" || target.screen==="extra" || target.playing) throw "CAPTURE_BLOCKED";
        // Qt 5.10 software renderer needs a full invalidation. QtTest's
        // window-backed grabImage avoids Item.grabToImage's inverted FBO.
        var visual=target.toolboxShell||target;
        visual.opacity=0.99;captureHelper.wait(120);visual.opacity=1;captureHelper.wait(180);
        // Qt 5.10's native helper clips to the requested item's size but does
        // not account for its 106px position in the factory window. Capture
        // the whole window and keep an explicitly derived host content crop.
        var picture=captureHelper.grabImage(target.Window.window.contentItem);
        if(picture.width!==800 || picture.height!==480) throw "CAPTURE_SIZE";
        // Qt 5.10/5.15's save() is void. Backend validates actual PNG headers
        // and dimensions before accepting the test report.
        picture.save(captureDirectory+"/"+name+".png");
        captures.push(name);
    }
    function finish(passed,error) {
        if(finished) return;
        lastUiMessage=target.message;
        finished=true;
        var diagnostic={failure:playerDriver.item?playerDriver.item.failure:"",parts:target.partCount,screen:target.screen,detail_error:target.detailError,detail_code:target.detailErrorCode,
            read_error:target.readError?target.readErrorKind:"",read_code:target.readError?target.readErrorCode:0,native_keyboard_reused:nativeKeyboardReused};
        target.http("POST","/qa/finish",{passed:passed,error:error,step:step,checks:checks,captures:captures,toolbox_checks:toolboxChecks,player_checks:playerDriver.item?playerDriver.item.checks:[],player_stage:playerDriver.item?playerDriver.item.stage:0,player_diagnostic:diagnostic},function(reply){
            // Even a rejected report must end this finite test. The host
            // treats a missing/failed report as failure, never as acceptance.
            target.quitTrial();
        },false);
    }
    function run() {
        if(stepping)return;
        stepping=true;
        try{runOnce();}finally{stepping=false;}
    }
    function runOnce() {
        if(!target || finished) return;
        if(Date.now()-started>(enhanced?480000:180000)) {finish(false,"TIMEOUT");return;}
        if(!target.token) return;
        if(!claimed) {
            if(claiming) return;
            claiming=true;
            target.http("POST","/qa/start",{},function(reply){
                if(reply.ok) {claimed=true;target.qaMode=true;started=Date.now();}
                // Recovery-only candidate must never rerun automation.
                else finished=true;
            },false);
            return;
        }
        try {
            if(target.toolboxShell&&!toolboxDone){
                if(!toolboxStarted&&toolboxDriver.item){toolboxStarted=true;toolboxDriver.item.begin(driver);}
                return;
            }
            if(target.busy) return;
            if(target.screen==="catalog" && target.pendingCovers>0 && Date.now()-target.coverStarted<18000) return;
            switch(step) {
            case 0:
                check("bootstrap",!!target.token);
                if(!target.rows.length) throw "NO_CONTENT";
                check("recommendations",target.screen==="catalog"&&target.tab==="recommend");
                capture("01-recommendations");click("biliNext");step++;break;
            case 1:
                check("pagination",target.rowAt===3);capture("02-next-cards");
                click("biliOpen");click("biliSample");step++;break;
            case 2:
                if(detailStep===0) {
                    check("details",target.screen==="detail"&&item("biliParts").count>0);
                    capture("03-video-details");click("biliDescription");detailStep++;break;
                }
                if(detailStep===1) {
                    check("description",target.screen==="description");capture("09-description");click("biliBack");click("biliQuality");detailStep++;break;
                }
                if(detailStep===2) {
                    check("qualities",item("biliQualityOption1").visible);capture("10-qualities");click("biliQualityOption0");
                    check("quality-selection",target.screen==="detail"&&target.selectedQuality===0);
                    click("biliComments");detailStep++;break;
                }
                if(detailStep===3) {
                    check("comments",target.screen==="comments"&&item("biliCommentList").count>0);capture("11-comments");
                    check("comment-has-more",target.commentMore);click("biliCommentNext");detailStep++;break;
                }
                if(detailStep===4) {
                    check("comment-pagination",target.commentPage===2&&item("biliCommentList").count>0);capture("12-comments-next");
                    click("biliCommentPrevious");detailStep++;break;
                }
                if(detailStep===5) {
                    check("comment-back-page",target.commentPage===1);
                    var replyIndex=-1;
                    for(var r=0;r<target.commentRows.length;r++)if(target.commentRows[r].replies>0){replyIndex=r;break;}
                    if(replyIndex<0)throw "NO_CONTENT";
                    var list=item("biliCommentList");list.positionViewAtIndex(replyIndex,ListView.Beginning);captureHelper.wait(120);
                    var replyButton=item("biliReplies"+replyIndex),location=replyButton.mapToItem(list,0,0);
                    list.contentY+=location.y-70;captureHelper.wait(120);click("biliReplies"+replyIndex);detailStep++;break;
                }
                if(detailStep===6){check("comment-replies",!!target.commentRoot&&item("biliCommentList").count>0);capture("14-comment-replies");click("biliBack");detailStep++;break;}
                if(detailStep===7){check("replies-return",target.commentRoot==="");click("biliCommentSort");detailStep++;break;}
                check("comment-sort",target.commentMode===2&&item("biliCommentList").count>0);
                click("biliBack");check("detail-return",target.screen==="detail");click("biliBack");
                check("back",target.screen==="catalog");click("biliSearch");click("biliEditInput");step++;break;
            case 3:
                check("keyboard",item("biliKeyboard").visible);
                var letters="dianying";
                for(var i=0;i<letters.length;i++) {click("biliKey_"+letters.charAt(i));captureHelper.wait(30);}
                step++;break;
            case 4:
                if(!item("biliKeyboard").candidates.length) return;
                capture("04-offline-keyboard");click("biliCandidate0");click("biliKeyboardDone");
                check("chinese-input",target.inputValue==="电影");capture("05-search-input");
                click("biliInputSubmit");step++;break;
            case 5:
                check("search",target.tab==="search"&&target.rows.length>0);
                capture("06-search-results");click("biliBangumi");step++;break;
            case 6:
                if(!bangumiDetail){check("bangumi",target.tab==="bangumi"&&target.rows.length>0);capture("07-bangumi");click("biliCard0");bangumiDetail=1;break;}
                if(bangumiDetail===1){
                    check("bangumi-details",target.screen==="detail"&&target.partCount>2);capture("13-bangumi-details");
                    var partList=item("biliParts"),partX=partList.width/2,partY=partList.height-12;
                    touch.mousePress(partList,partX,partY,Qt.LeftButton,Qt.NoModifier,20);
                    for(var dy=partY-13;dy>=16;dy-=13)touch.mouseMove(partList,partX,dy,30,Qt.LeftButton);
                    touch.mouseRelease(partList,partX,16,Qt.LeftButton,Qt.NoModifier,20);bangumiDetail=2;break;
                }
                check("parts-scroll",item("biliParts").contentY>10);capture("15-bangumi-scrolled");click("biliOpen");
                target.inputValue="not-a-valid-bv";click("biliInputSubmit");step++;break;
            case 7:
                check("input-error",target.screen==="detail"&&target.message.indexOf("请输入")>=0);
                capture("08-input-error");click("biliRetry");check("input-edit-retry",target.screen==="openInput"&&!target.readError);target.inputValue="";click("biliNativeInput");step=13;break;
            case 13:
                var board=item("biliKeyboard");nativeKeyboardReused=board.nativeActive;
                capture("16-input-component");
                if(board.nativeActive){var key=board.nativeKey("0");if(!key)throw "MISSING_ITEM";touch.mouseClick(key,key.width/2,key.height/2,Qt.LeftButton,Qt.NoModifier,20);check("input-component",board.nativeEditor.text==="0");click("biliNativeDone");}
                else{click("biliKey_a");click("biliKeyboardDone");check("input-component",target.inputValue==="a");}
                click("biliBack");target.details({kind:"video",bvid:"BV1a4421w7zK"},"detail");step=14;break;
            case 14:
                if(!target.partCount)throw "NO_CONTENT";click("biliQuality");step=15;break;
            case 15:
                check("api-high-qualities",target.qualityIds.indexOf(127)>=0&&target.qualityIds.indexOf(125)>=0);
                var qualityView=item("biliQualityScroll");qualityView.contentY=Math.max(0,qualityView.contentHeight-qualityView.height);captureHelper.wait(180);
                check("quality-scroll",qualityView.contentY>0);capture("17-api-high-qualities");click("biliFollowing");step=8;break;
            case 8:
                check("following-route",target.tab==="following"&&target.screen==="catalog");
                // Personalized following titles and account/QR never captured.
                check("no-player",!target.playing);
                if(enhanced){step++;playerDriver.item.begin(target,click);}else if(target.toolboxShell)step=10;else finish(true,"");break;
            case 9:break;
            case 10:click("biliExit");step++;break;
            case 11:
                if(target.toolboxShell.biliShown)return;
                toolboxChecks.push("bili-return");click("homeBili");step++;break;
            case 12:
                if(!target.visible)return;toolboxChecks.push("bili-reopen");finish(true,"");break;
            }
        } catch(e) {
            var allowed=["MISSING_ITEM","INVISIBLE_ITEM","ASSERTION","CAPTURE_BLOCKED","CAPTURE_SIZE","CAPTURE_FAILED","NO_CONTENT"];
            finish(false,allowed.indexOf(String(e))>=0?String(e):"QML_EXCEPTION");
        }
    }
    // Use only the native helpers: TestCase.qml requires qmltestrunner's
    // Qt.test.qtestroot singleton, which the original Z03 does not register.
    // These helpers neither run test discovery nor call Qt.quit.
    TestEvent {id:touch}
    TestResult {id:captureHelper}
    Loader {id:playerDriver;source:driver.enhanced?"PlayerAutomation.qml":""}
    Loader {id:toolboxDriver;source:driver.target&&driver.target.toolboxShell?"ToolboxAutomation.qml":""}
    Connections {target:toolboxDriver.item;ignoreUnknownSignals:true;onCompleted:{driver.toolboxChecks=toolboxDriver.item.checks;driver.toolboxDone=passed;if(!passed)driver.finish(false,"TOOLBOX_QA_FAILED");}}
    Connections {target:playerDriver.item;ignoreUnknownSignals:true;onCompleted:{if(passed&&driver.target.toolboxShell)driver.step=10;else driver.finish(passed,passed?"":"PLAYER_QA_FAILED");}}
    Timer {interval:1200;repeat:true;running:!driver.finished;onTriggered:driver.run()}
}
