// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick 2.7
import "BiliUx.js" as Ux
Item {
    id: extra
    property var host: null
    property string page: ""
    property string origin: "catalog"
    property var video: ({})
    property var relation: ({})
    property var rows: []
    property var cursor: ({})
    property var history: []
    property bool more: false
    property bool busy: false
    property string note: ""
    property string intent: ""
    property string confirm: ""
    property int version: 0
    property string username: ""
    property string password: ""
    property string loginNonce: ""
    property var challenge: ({})
    property bool agreeing: false
    property string editField: ""
    property string policyKind: ""
    property string draft: ""
    property int dmMode: 1
    property int dmPosition: 0
    property var cloudState: ({enabled:false,confirmed:0,error:""})
    property string mediaTitle: page==="compose-danmaku"?"发送弹幕":page==="cloud-sync"?"云端观看记录":""
    property string title: page==="compose-comment"?(video.parent&&video.parent!=="0"?"回复评论":"写评论"):page==="comment-actions"?"评论点赞":page==="season-follow"?"追番管理":page==="password"||page==="captcha"?"账号密码登录":page==="policy"?"B 站官方协议":page==="interaction"?"视频互动":page==="more-actions"?"关注与稍后再看":page==="favorites"?"收藏夹":page==="cloud"?"B 站账号历史":page==="live"?"直播间":"推荐反馈说明"
    function call(op,args,done) {
        var mine=version;busy=true;
        host.job(op,args,function(r){if(mine!==version||host.screen!=="extra")return;busy=false;if(!r.ok){note=host.errText(r);return;}done(r.data);});
    }
    function show(kind,value,from) {
        version++;page=kind;origin=from;video=value||{};rows=[];note="";intent="";confirm="";history=[];cursor={};busy=false;
        username="";password="";draft="";loginNonce="";agreeing=false;loginInput.clearSecret();captchaLoader.source="";policyLoader.source="";
        if(kind==="interaction"||kind==="more-actions"||kind==="compose-comment"||kind==="comment-actions"||kind==="season-follow")refreshRelation();
        if(kind==="cloud")cloud({});
        if(kind==="compose-danmaku"){dmMode=1;dmPosition=Math.floor(video.position||0);refreshMedia();}
        if(kind==="cloud-sync")refreshMedia();
        if(kind==="live")call("live_detail",{room:video.room},function(d){video=d;note=d.live_status===1?"正在直播":"主播暂未开播";});
    }
    function refreshMedia(){confirm="";intent="";var sync=page==="cloud-sync";
        call(sync?"cloud_state":"danmaku_context",sync?{}:{bvid:video.bvid,cid:video.cid,position:dmPosition},function(d){intent=d.intent;if(sync){cloudState=d;note=d.error?"上次上报未确认，已停止同步；请先在官方端核实":d.enabled?"本次会话已开启 · 退出工具箱后自动关闭":"默认关闭，不会写入 B 站观看记录";}else {dmPosition=d.position;note="发送到所选分 P 的 "+Ux.stamp(dmPosition)+" · 白色普通弹幕";}});}
    function sendDanmaku(){if(busy||!intent)return;if(confirm!=="danmaku"){confirm="danmaku";note="再次点击确认：向 B 站公开提交这条弹幕";return;}
        var a={bvid:video.bvid,cid:video.cid,position:dmPosition,mode:dmMode,message:draft,intent:intent};intent="";confirm="";
        call("danmaku_send",a,function(d){draft="";note=d.visible?"B 站已接收，实际展示以官方审核为准":"B 站已接收，当前未确认公开展示";});}
    function toggleCloud(){if(busy||!intent)return;var value=!cloudState.enabled;
        if(value&&confirm!=="cloud"){confirm="cloud";note="再次确认后，本次真实观看进度将写入 B 站账号";return;}
        var a={value:value,intent:intent};intent="";confirm="";call("cloud_enable",a,function(d){cloudState=d;note=d.enabled?"已开启本次同步；不会自动开启下一次会话":"已关闭云端同步";});}
    function refreshRelation() {confirm="";intent="";var season=page==="season-follow";call(season?"season_relation":"relation",season?{season:video.season}:{bvid:video.bvid},function(d){relation=d;intent=d.intent;note=season?(d.following?"已追番":"尚未追番"):page==="compose-comment"?"提交到 B 站，是否公开以官方审核为准":page==="comment-actions"?"操作将同步到 B 站账号":page==="more-actions"?"每项操作均须再次点击确认":"长按点赞可三连，将投币并收藏。投币不可撤回。";});}
    function act(action,value,folder) {
        if(busy)return;
        if(!intent){note="请先刷新状态再操作";return;}
        if(action==="coin"||action==="favorite"||action==="follow"||action==="watchlater"||action==="comment"||action==="comment_like"||action==="season_follow"){
            var key=action+":"+value+":"+(folder||"");
            if(confirm!==key){confirm=key;note=action==="coin"?"再次点击确认投 "+value+" 币，投币不可撤回":action==="comment"?"再次点发送确认，内容将公开提交到 B 站":action==="favorite"?"再次点击确认更改此收藏夹":"再次点击确认提交此账号操作";return;}
        }
        var a={bvid:video.bvid,action:action,intent:intent};
        if(action==="coin")a.count=value;
        if(action==="like"||action==="favorite"||action==="follow"||action==="watchlater"||action==="comment_like")a.value=value;
        if(action==="favorite")a.folder=folder;
        if(action==="comment"||action==="comment_like"){a.root=video.root||"0";a.parent=video.parent||"0";if(action==="comment")a.message=draft;}
        if(action==="season_follow")a={season:video.season,value:value,intent:intent};
        intent="";confirm="";
        call(action==="season_follow"?"season_follow":"interaction",a,function(d){
            if(d.state_available)relation=d.relation;
            if(action==="comment"){draft="";note="已提交给 B 站，是否公开以官方审核为准";return;}
            if(action==="comment_like"||action==="season_follow"){note="B 站已确认提交；返回或刷新查看最新状态";return;}
            page="interaction";note="B 站已确认提交。刷新状态后可继续操作。";
            if(d.triple)note="三连结果：点赞"+(d.triple.like?"成功":"未完成")+" · 投币"+(d.triple.coin?"成功":"未完成")+" · 收藏"+(d.triple.favorite?"成功":"未完成");
        });
    }
    function folders() {page="favorites";confirm="";rows=[];call("favorites",{bvid:video.bvid},function(d){rows=d.items;note=rows.length?"点选收藏夹，再次点击确认更改":"账号没有可用收藏夹，请在官方端创建";});}
    function cloud(c) {page="cloud";note="";call("account_history",c,function(d){rows=d.items;cursor=d.cursor;more=d.more;note="来自 B 站账号 · 云端观看记录";});}
    function nextCloud(){if(!more||busy)return;history=history.concat([{rows:rows,cursor:cursor,more:more}]);cloud(cursor);}
    function previousCloud(){if(busy||!history.length)return;var old=history[history.length-1];history=history.slice(0,-1);rows=old.rows;cursor=old.cursor;more=old.more;}
    function playLive(){call("play",{kind:"live",room:video.room,title:video.title,up:video.up},function(d){note="直播已打开 · 播放设置可选择实际可用画质";});}
    function edit(field){editField=field;loginInput.secret=field==="password";loginInput.open(extra[field],false,field!=="password");}
    function policy(which){policyKind=which;page="policy";note=which==="privacy"?"B 站官方隐私政策 · 上下滑动阅读":"B 站官方用户协议 · 上下滑动阅读";policyLoader.source="BiliPolicy.qml";}
    function closePolicy(){policyLoader.source="";page="password";note="";}
    function beginLogin(){
        if(!username||!password||!agreeing||busy)return;
        call("password_challenge",{},function(d){loginNonce=d.nonce;challenge=d;page="captcha";note="请手动完成官方验证码，不会自动解题";captchaLoader.source="BiliCaptcha.qml";});
    }
    function captchaFailed(){password="";loginNonce="";captchaLoader.source="";page="password";note="官方验证码未能加载，请改用扫码登录";host.job("password_cancel",{},function(r){});}
    function submitProof(proof){
        if(!loginNonce||busy)return;
        var args={username:username,password:password,nonce:loginNonce,challenge:proof.challenge,validate:proof.validate,seccode:proof.seccode};
        password="";loginNonce="";captchaLoader.source="";page="password";
        call("password_login",args,function(d){username="";note="登录成功";host.loggedIn=true;host.refreshAccount();});
    }
    function leave(){if(page==="policy"){closePolicy();return;}version++;username="";password="";draft="";loginNonce="";loginInput.clearSecret();commentInput.visible=false;captchaLoader.source="";policyLoader.source="";host.job("password_cancel",{},function(r){});host.screen=origin;host.busy=false;host.message="";if(origin==="login")host.refreshAccount();}
    BiliLabel {x:0;y:0;width:772;height:31;visible:extra.page!=="captcha";text:busy?"正在读取 B 站数据…":note;font.pixelSize:17;color:Ux.secondary}
    Item {y:38;width:772;height:160;visible:extra.page==="interaction"
        BiliLabel {width:772;height:37;text:extra.video.title||"视频互动";font.pixelSize:23}
        Row {y:48;spacing:10
            BiliButton {objectName:"biliLike";width:181;height:60;textSize:22;available:!extra.busy&&extra.intent!=="";selected:extra.relation.like===true;holdEnabled:true;label:extra.relation.like?"已点赞":"点赞";onClicked:extra.act("like",!extra.relation.like);onHeld:extra.act("triple")}
            BiliButton {objectName:"biliCoin1";width:181;height:60;available:!extra.busy&&extra.intent!=="";label:extra.confirm.indexOf("coin:1:")===0?"确认投 1 币":"投 1 币";onClicked:extra.act("coin",1)}
            BiliButton {objectName:"biliCoin2";width:181;height:60;available:!extra.busy&&extra.intent!=="";label:extra.confirm.indexOf("coin:2:")===0?"确认投 2 币":"投 2 币";onClicked:extra.act("coin",2)}
            BiliButton {objectName:"biliFavorites";width:181;height:60;available:!extra.busy;label:"收藏夹";onClicked:extra.folders()}
        }
        BiliLabel {y:119;width:330;height:40;text:"已投 "+(extra.relation.coin||0)+" 币 · "+(extra.relation.favorite?"已收藏":"未收藏");font.pixelSize:20;color:Ux.secondary}
        BiliButton {objectName:"biliMoreActions";x:359;y:117;width:202;height:44;label:"关注 / 稍后再看";textSize:18;available:!extra.busy;onClicked:{extra.page="more-actions";extra.refreshRelation();}}
        BiliButton {objectName:"biliRelationRefresh";x:573;y:117;width:181;height:44;label:"刷新状态";textSize:19;available:!extra.busy;onClicked:extra.refreshRelation()}
    }
    ListView {objectName:"biliFolderList";x:0;y:38;width:772;height:160;visible:extra.page==="favorites";clip:true;spacing:8;model:extra.rows
        delegate:BiliButton {objectName:"biliFolder"+index;width:756;height:58;selected:modelData.selected===true;available:!extra.busy;label:(modelData.selected?"已收藏 · ":"收藏至 · ")+modelData.title;onClicked:extra.act("favorite",!modelData.selected,modelData.id)}
    }
    Item {y:38;width:772;height:160;visible:extra.page==="compose-comment"
        Rectangle {width:772;height:99;radius:9;color:Ux.surface
            BiliLabel {x:12;y:6;width:746;height:84;text:extra.draft||"说说你的看法…";wrapMode:Text.Wrap;maximumLineCount:3;font.pixelSize:21;color:extra.draft?Ux.foreground:Ux.muted;verticalAlignment:Text.AlignTop}
            MouseArea {anchors.fill:parent;enabled:!extra.busy;onClicked:{extra.confirm="";commentInput.open(extra.draft,true,false);}}}
        BiliButton {objectName:"biliCommentEdit";y:110;width:196;height:48;label:"编辑内容";available:!extra.busy;onClicked:{extra.confirm="";commentInput.open(extra.draft,true,false);}}
        BiliLabel {x:207;y:110;width:175;height:48;font.pixelSize:19;color:extra.draft.length>160?Ux.accent:Ux.muted;text:extra.draft.length+" / 160 字"}
        BiliButton {objectName:"biliCommentRefresh";x:391;y:110;width:184;height:48;textSize:19;label:"刷新操作状态";available:!extra.busy;onClicked:extra.refreshRelation()}
        BiliButton {objectName:"biliCommentSend";x:587;y:110;width:185;height:48;selected:true;label:extra.confirm.indexOf("comment:")===0?"确认发送":"发送";available:!extra.busy&&!!extra.intent&&extra.draft.trim().length>0&&extra.draft.length<=160;onClicked:extra.act("comment")}}
    Item {y:38;width:772;height:160;visible:extra.page==="compose-danmaku"
        Rectangle {width:772;height:60;radius:9;color:Ux.surface
            BiliLabel {x:12;y:6;width:748;height:49;text:extra.draft||"说点什么…（100 字以内）";wrapMode:Text.Wrap;maximumLineCount:2;font.pixelSize:20;color:extra.draft?Ux.foreground:Ux.muted}
            MouseArea {anchors.fill:parent;enabled:!extra.busy;onClicked:{extra.confirm="";commentInput.open(extra.draft,true,false);}}}
        Row {y:70;spacing:9
            Repeater {model:[{id:1,name:"滚动"},{id:5,name:"顶部"},{id:4,name:"底部"}]
                BiliButton {width:160;height:42;textSize:20;label:modelData.name;selected:extra.dmMode===modelData.id;available:!extra.busy;onClicked:{extra.dmMode=modelData.id;extra.confirm="";}}}
            BiliLabel {width:255;height:42;text:extra.draft.length+" / 100 字";font.pixelSize:18;color:Ux.muted}}
        BiliButton {objectName:"biliDanmakuRefresh";y:120;width:242;height:42;textSize:19;label:"刷新发送状态";available:!extra.busy;onClicked:extra.refreshMedia()}
        BiliButton {objectName:"biliDanmakuEdit";x:254;y:120;width:242;height:42;textSize:19;label:"编辑内容";available:!extra.busy;onClicked:{extra.confirm="";commentInput.open(extra.draft,true,false);}}
        BiliButton {objectName:"biliDanmakuSend";x:509;y:120;width:263;height:42;textSize:19;selected:true;label:extra.confirm==="danmaku"?"确认发送":"发送";available:!extra.busy&&!!extra.intent&&extra.draft.trim().length>0&&extra.draft.length<=100;onClicked:extra.sendDanmaku()}}
    Item {y:38;width:772;height:160;visible:extra.page==="cloud-sync"
        BiliLabel {width:772;height:102;wrapMode:Text.Wrap;maximumLineCount:4;font.pixelSize:21;verticalAlignment:Text.AlignTop;color:Ux.secondary;text:"本次会话普通视频的真实播放进度将同步到 B 站。暂停、跳转不累计观看时长；不含番剧、短视频流和直播。\n服务器已确认 "+extra.cloudState.confirmed+" 次。异常或切换账号后停止，不自动重试。"}
        BiliButton {objectName:"biliCloudSyncRefresh";y:111;width:369;height:48;label:"刷新同步状态";available:!extra.busy;onClicked:extra.refreshMedia()}
        BiliButton {objectName:"biliCloudSyncToggle";x:383;y:111;width:389;height:48;selected:extra.cloudState.enabled;label:extra.cloudState.enabled?"关闭本次同步":extra.confirm==="cloud"?"确认开启本次同步":"开启本次同步";available:!extra.busy&&!!extra.intent;onClicked:extra.toggleCloud()}}
    Item {y:38;width:772;height:160;visible:extra.page==="comment-actions"||extra.page==="season-follow"
        BiliLabel {width:772;height:63;text:extra.video.excerpt||extra.video.title||extra.title;wrapMode:Text.Wrap;maximumLineCount:2;font.pixelSize:22}
        Row {y:81;spacing:12
            BiliButton {objectName:"biliExtraPositive";width:249;height:65;label:extra.page==="season-follow"?"追番":"点赞此评论";available:!extra.busy&&!!extra.intent;onClicked:extra.act(extra.page==="season-follow"?"season_follow":"comment_like",true)}
            BiliButton {objectName:"biliExtraNegative";width:249;height:65;label:extra.page==="season-follow"?"取消追番":"取消评论点赞";available:!extra.busy&&!!extra.intent;onClicked:extra.act(extra.page==="season-follow"?"season_follow":"comment_like",false)}
            BiliButton {objectName:"biliExtraRefresh";width:249;height:65;label:"刷新状态";available:!extra.busy;onClicked:extra.refreshRelation()}}}
    Item {y:38;width:772;height:160;visible:extra.page==="more-actions"
        Row {y:5;spacing:10
            BiliButton {width:181;height:65;textSize:20;label:"加入稍后看";available:!extra.busy&&!!extra.intent;onClicked:extra.act("watchlater",true)}
            BiliButton {width:181;height:65;textSize:20;label:"移出稍后看";available:!extra.busy&&!!extra.intent;onClicked:extra.act("watchlater",false)}
            BiliButton {width:181;height:65;textSize:20;label:"关注此 UP";available:!extra.busy&&!!extra.intent;onClicked:extra.act("follow",true)}
            BiliButton {width:181;height:65;textSize:20;label:"取消关注";available:!extra.busy&&!!extra.intent;onClicked:extra.act("follow",false)}}
        BiliLabel {y:79;width:543;height:73;wrapMode:Text.Wrap;font.pixelSize:19;text:"操作提交到 B 站账号；关注对象以服务器确认的视频作者为准。每项均须再次点击确认。";color:Ux.secondary}
        BiliButton {x:573;y:104;width:181;height:48;textSize:20;label:"刷新状态";available:!extra.busy;onClicked:extra.refreshRelation()}}
    Item {x:0;y:38;width:772;height:160;visible:extra.page==="cloud"
        ListView {id:cloudList;objectName:"biliCloudHistory";width:636;height:160;model:extra.rows;clip:true;spacing:8
            delegate:BiliButton {width:627;height:66;textSize:20;available:!extra.busy&&modelData.playable===true;label:(modelData.kind==="live"?"直播 · ":"")+modelData.title+(modelData.finished?" · 已看完":modelData.position>0?" · 看至 "+Math.floor(modelData.position/60)+":"+("0"+Math.floor(modelData.position%60)).slice(-2):"");onClicked:{extra.host.details(modelData,"detail");}}
            BiliScrollHint {x:632;view:cloudList}
        }
        Column {x:646;spacing:8
            BiliButton {objectName:"biliCloudPrevious";width:126;height:48;textSize:20;label:"上一页";available:!extra.busy&&extra.history.length>0;onClicked:extra.previousCloud()}
            BiliButton {objectName:"biliCloudNext";width:126;height:48;textSize:20;label:"下一页";available:!extra.busy&&extra.more;onClicked:extra.nextCloud()}
            BiliButton {width:126;height:48;textSize:20;label:"刷新";available:!extra.busy;onClicked:{extra.history=[];extra.cloud({});}}
        }
        BiliLabel {x:10;y:50;width:610;height:60;visible:extra.rows.length===0&&!extra.busy;text:extra.note.indexOf("来自")===0?"账号暂时没有观看历史":extra.note;wrapMode:Text.Wrap;font.pixelSize:22}
    }
    Item {x:0;y:38;width:772;height:160;visible:extra.page==="live"
        BiliLabel {width:750;height:64;text:extra.video.title||"直播间";wrapMode:Text.Wrap;maximumLineCount:2;font.pixelSize:25;verticalAlignment:Text.AlignTop}
        BiliLabel {y:68;width:750;height:36;text:"房间 "+(extra.video.room||"")+" · "+(extra.video.live_status===1?"直播中":"未开播");font.pixelSize:20;color:Ux.secondary}
        BiliButton {objectName:"biliLivePlay";y:113;width:240;height:48;selected:true;label:"进入直播";available:!extra.busy&&extra.video.live_status===1;onClicked:extra.playLive()}
        BiliButton {x:254;y:113;width:240;height:48;label:"刷新房间";available:!extra.busy;onClicked:extra.show("live",extra.video,extra.origin)}
    }
    Item {x:0;y:38;width:772;height:160;visible:extra.page==="password"
        BiliButton {objectName:"biliUsername";width:375;height:54;label:extra.username||"手机号 / 邮箱 / 账号";onClicked:extra.edit("username")}
        BiliButton {objectName:"biliPassword";x:389;width:375;height:54;label:extra.password?Array(extra.password.length+1).join("•"):"输入密码";onClicked:extra.edit("password")}
        BiliButton {objectName:"biliLoginAgree";y:64;width:530;height:42;textSize:18;selected:extra.agreeing;label:extra.agreeing?"已同意 B 站用户协议与隐私政策":"阅读后点击同意 B 站用户协议与隐私政策";onClicked:extra.agreeing=!extra.agreeing}
        BiliButton {objectName:"biliPasswordSubmit";x:542;y:64;width:222;height:42;textSize:19;selected:true;label:"验证并登录";available:!!extra.username&&!!extra.password&&extra.agreeing&&!extra.busy;onClicked:extra.beginLogin()}
        BiliLabel {y:114;width:420;height:46;font.pixelSize:18;wrapMode:Text.Wrap;text:"密码不保存；需本人完成官方验证码。";color:Ux.secondary}
        BiliButton {x:426;y:113;width:164;height:44;textSize:18;label:"阅读用户协议";onClicked:extra.policy("licence")}
        BiliButton {x:600;y:113;width:164;height:44;textSize:18;label:"阅读隐私政策";onClicked:extra.policy("privacy")}
    }
    Loader {id:policyLoader;x:0;y:37;width:772;height:165;visible:extra.page==="policy";onLoaded:{item.unavailable.connect(function(){extra.note="官方协议暂未加载，请返回后稍候重试";});item.open(extra.policyKind);}onStatusChanged:if(status===Loader.Error)extra.note="官方协议浏览组件未能加载，请改用官方客户端登录"}
    Loader {id:captchaLoader;objectName:"biliCaptchaLoader";x:0;y:0;width:772;height:extra.height;visible:extra.page==="captcha";onLoaded:{item.completed.connect(extra.submitProof);item.unavailable.connect(extra.captchaFailed);item.begin(extra.challenge.gt,extra.challenge.challenge);}onStatusChanged:if(status===Loader.Error)extra.captchaFailed()}
    BiliInput {id:loginInput;objectName:"biliLoginInput";x:-14;y:-60;width:800;height:268;z:30;visible:false;onAccepted:extra[extra.editField]=value}
    BiliInput {id:commentInput;objectName:"biliCommentInput";x:-14;y:-60;width:800;height:268;z:31;visible:false;lookup:function(code,callback){extra.host.http("POST","/pinyin",{code:code},callback,false);}
        onAccepted:{extra.draft=value;extra.confirm="";}}
    Flickable {x:0;y:38;width:772;height:160;contentWidth:width;contentHeight:capText.height;clip:true;visible:extra.page==="capabilities"
        BiliLabel {id:capText;width:752;height:implicitHeight;wrapMode:Text.Wrap;font.pixelSize:22;verticalAlignment:Text.AlignTop;text:"“不感兴趣”推荐反馈暂未适配，请在哔哩哔哩官方客户端操作。\n\n本页不会修改你的推荐偏好。"}
    }
    Component.onDestruction:{password="";username="";loginNonce="";}
}
