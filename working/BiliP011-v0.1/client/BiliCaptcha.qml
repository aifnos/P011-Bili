// SPDX-License-Identifier: GPL-3.0-or-later
// Only the genuine interactive Geetest widget. No solving/synthetic proof.
import QtQuick 2.7
import QtWebEngine 1.4
import QtWebChannel 1.0
Item {
    id: captcha
    property string gt: ""
    property string challenge: ""
    property bool sent: false
    property bool autoFit: true
    property bool measuring: false
    property real canvasHeight: 460
    // Keep the requested scale independent of WebEngine's asynchronous getter;
    // reading that getter back into viewport sizing can swallow a zoom step.
    property real pageZoom: 0.45
    property int zoomAttempts: 0
    property string fittedShape: ""
    signal completed(var proof)
    signal unavailable()
    signal environmentReady()
    onPageZoomChanged:{zoomAttempts=0;zoomApply.restart();}
    // Resize the browser canvas first, then confirm page zoom with a bounded
    // retry. Some WebEngine adapters do not apply their first new zoom value.
    Timer {id:zoomApply;interval:80;onTriggered:{view.zoomFactor=captcha.pageZoom;captcha.zoomAttempts++;if(Math.abs(view.zoomFactor-captcha.pageZoom)>0.001&&captcha.zoomAttempts<3)restart();}}
    // Only inspect visible widget geometry, never its text, images or answer.
    // Page zoom preserves Chromium's own input mapping. The native viewport
    // can pan the entire browser, including fixed-position challenge panels.
    function measurePage(force) {
        if(measuring||(!autoFit&&!force)||sent)return;
        measuring=true;
        view.runJavaScript('(function(){if(window._p011TouchActive||Date.now()<(window._p011TouchUntil||0))return null;var a=document.querySelectorAll(".geetest_panel_box,.geetest_popup_wrap,.geetest_holder,.geetest_widget,.geetest_wind,.geetest_box"),best=null;for(var i=0;i<a.length;i++){var e=a[i],s=getComputedStyle(e),r=e.getBoundingClientRect();if(s.display==="none"||s.visibility==="hidden"||Number(s.opacity)===0||r.width<80||r.height<120||(r.width>=window.innerWidth-2&&r.height>=window.innerHeight-2))continue;if(!best||r.width*r.height>best[0]*best[1])best=[r.width,r.height];}return best;})()',function(size){
            measuring=false;
            if(!autoFit||!size||size.length!==2||!isFinite(size[0])||!isFinite(size[1])||size[0]>3000||size[1]>3000)return;
            var shape=Math.round(size[0])+":"+Math.round(size[1]);
            if(!force&&shape===fittedShape)return;
            fittedShape=shape;canvasHeight=Math.max(420,size[1]+32);
            pageZoom=Math.max(0.25,Math.min(1,(viewport.height-4)/canvasHeight,(viewport.width-12)/(size[0]+16)));
            viewport.contentY=0;
        });
    }
    function fitPage() {
        autoFit=true;fittedShape="";canvasHeight=460;pageZoom=0.45;viewport.contentY=0;
        measurePage(true);
    }
    function enlarge() {
        autoFit=false;
        var center=viewport.contentY+viewport.height/2,old=pageZoom;
        pageZoom=Math.min(1.5,old*1.25);
        viewport.contentY=Math.max(0,Math.min(Math.max(viewport.height,canvasHeight*pageZoom)-viewport.height,center*pageZoom/old-viewport.height/2));
    }
    function panPage(direction) {
        autoFit=false;
        viewport.contentY=Math.max(0,Math.min(view.height-viewport.height,viewport.contentY+direction*viewport.height*0.65));
    }
    Timer {interval:500;repeat:true;running:captcha.visible&&captcha.autoFit&&!captcha.sent;onTriggered:captcha.measurePage(false)}
    // Bundled test page only: proves Qt WebEngine/WebChannel integration,
    // without contacting a login API, capturing a challenge or submitting it.
    function probe() {
        view.loadHtml('<!doctype html><meta charset="utf-8"><script src="qrc:///qtwebchannel/qwebchannel.js"></script><script>new QWebChannel(qt.webChannelTransport,function(c){c.objects.proof.environmentReady();});</script>',"https://passport.bilibili.com/");
    }
    function begin(g,c) {
        if(!/^[a-zA-Z0-9_-]{16,256}$/.test(g)||!/^[a-zA-Z0-9_-]{16,256}$/.test(c)){unavailable();return;}
        gt=g;challenge=c;sent=false;fitPage();
        var config=JSON.stringify({gt:g,challenge:c,offline:false,new_captcha:true,product:"embed",width:"100%",lang:"zh-cn"});
        view.loadHtml('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;background:#fff;font:16px sans-serif}#verify{max-width:500px;margin:8px auto}</style><div id="verify"></div><script>function touchStart(){window._p011TouchActive=true;}function touchEnd(){window._p011TouchActive=false;window._p011TouchUntil=Date.now()+1500;}document.addEventListener("touchstart",touchStart,true);document.addEventListener("touchend",touchEnd,true);document.addEventListener("touchcancel",touchEnd,true);document.addEventListener("mousedown",touchStart,true);document.addEventListener("mouseup",touchEnd,true);window.addEventListener("blur",touchEnd,true);</script><script src="qrc:///qtwebchannel/qwebchannel.js"></script><script src="https://static.geetest.com/static/tools/gt.js"></script><script>new QWebChannel(qt.webChannelTransport,function(ch){if(typeof initGeetest!=="function"){ch.objects.proof.failed();return;}initGeetest('+config+',function(c){c.appendTo("#verify");c.onSuccess(function(){var r=c.getValidate();if(r)ch.objects.proof.complete(JSON.stringify(r));});c.onError(function(){ch.objects.proof.failed();});});});</script>',"https://passport.bilibili.com/");
    }
    QtObject {
        id: proof
        WebChannel.id: "proof"
        function environmentReady(){captcha.environmentReady();}
        function failed(){captcha.unavailable();}
        function complete(value){
            if(captcha.sent||typeof value!=="string"||value.length>2048)return;
            try {var p=JSON.parse(value);for(var i=0;i<3;i++){var v=p[["geetest_challenge","geetest_validate","geetest_seccode"][i]];if(typeof v!=="string"||!v.length||v.length>512)return;}captcha.sent=true;captcha.completed({challenge:p.geetest_challenge,validate:p.geetest_validate,seccode:p.geetest_seccode});}catch(e){}
        }
    }
    WebChannel {id:channel;registeredObjects:[proof]}
    WebEngineProfile {id:profile;offTheRecord:true}
    Flickable {
        id:viewport;objectName:"captchaViewport";width:Math.max(1,parent.width-108);height:parent.height
        clip:true;interactive:false;contentWidth:width;contentHeight:view.height
        WebEngineView {
        id:view;objectName:"captchaWebView";width:viewport.width;height:Math.max(viewport.height,captcha.canvasHeight*captcha.pageZoom)
        zoomFactor:0.45;profile:profile;webChannel:channel
        settings.localStorageEnabled:false
        settings.pluginsEnabled:false
        settings.javascriptCanOpenWindows:false
        settings.javascriptCanAccessClipboard:false
        onJavaScriptConsoleMessage: {} // Never forward page messages or tokens.
        onCertificateError:error.rejectCertificate()
        onNewViewRequested: {} // No popups or external app navigation.
        onNavigationRequested:if(request.isMainFrame&&request.url.toString()!=="https://passport.bilibili.com/"&&request.url.toString()!=="about:blank"&&request.url.toString().indexOf("data:")!==0)request.action=WebEngineView.IgnoreRequest
        onLoadingChanged:if(loadRequest.status===WebEngineView.LoadFailedStatus)captcha.unavailable()
        }
    }
    Column {x:parent.width-100;spacing:3
        BiliButton {objectName:"captchaFit";width:100;height:48;textSize:19;label:"适配";selected:captcha.autoFit;onClicked:captcha.fitPage()}
        BiliButton {objectName:"captchaZoom";width:100;height:48;textSize:19;label:"放大";available:captcha.pageZoom<1.5;onClicked:captcha.enlarge()}
        BiliButton {objectName:"captchaUp";width:100;height:48;textSize:19;label:"上移";available:viewport.contentY>0;onClicked:captcha.panPage(-1)}
        BiliButton {objectName:"captchaDown";width:100;height:48;textSize:19;label:"下移";available:viewport.contentY<view.height-viewport.height-1;onClicked:captcha.panPage(1)}
    }
}
