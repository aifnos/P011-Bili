// Embedded in the existing factory page host. No extra offset or rotation.
import QtQuick 2.7
Rectangle {
    id:shell;objectName:"toolboxShell";width:800;height:268;color:"#080f17"
    property string pageType:"p011BiliPage"
    property bool biliShown:false
    property var toolbox:tools.item
    property var bili:biliLoader.item
    property string problem:"正在连接工具箱…"
    property bool alive:true
    function showBili(){biliShown=true;if(bili)bili.forceActiveFocus();}
    function showHome(){biliShown=false;if(toolbox)toolbox.forceActiveFocus();}
    function boot(){
        var xhr=new XMLHttpRequest();xhr.onreadystatechange=function(){
            if(!shell.alive||xhr.readyState!==XMLHttpRequest.DONE)return;
            try{var d=JSON.parse(xhr.responseText);
                if(!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(d.url)||!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(d.toolbox_url))throw "endpoint";
                tools.setSource("ExtensionPage.qml",{endpoint:d.toolbox_url,bootstrapAllowed:true,biliAvailable:true});
                biliLoader.setSource("BiliPanel.qml",{endpoint:d.url,toolboxShell:shell});
                problem="";
            }catch(e){problem="服务未就绪，请退出后重试";}
        };xhr.open("GET","file://@REMOTE@/bili-endpoint.json");xhr.send();
    }
    Loader{id:tools;anchors.fill:parent;visible:!shell.biliShown
        onLoaded:{item.biliRequested.connect(shell.showBili);item.exitRequested.connect(function(){if(shell.bili)shell.bili.quitTrial();});}
    }
    // Keep both pages alive: native bootstrap tokens are intentionally single-use.
    Loader{id:biliLoader;anchors.fill:parent;visible:shell.biliShown}
    BiliLabel{anchors.centerIn:parent;width:760;height:70;visible:shell.problem!=="";text:shell.problem;horizontalAlignment:Text.AlignHCenter;font.pixelSize:27}
    Component.onCompleted:boot()
    Component.onDestruction:alive=false
}
