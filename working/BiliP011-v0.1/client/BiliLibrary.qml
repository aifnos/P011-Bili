// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick 2.7
import "BiliUx.js" as Ux
Item {
    id: library
    property var host: null
    property string origin: "catalog"
    property string title: "发现"
    property string category: "popular"
    property var request: ({})
    property var rows: []
    property var stack: []
    property int page: 1
    property bool more: false
    property bool busy: false
    property string note: ""
    property string description: ""
    property bool following: false
    property bool profileOpen: false
    property int version: 0
    property int observedGeneration: host?host.accountGeneration:0
    onObservedGenerationChanged:{version++;busy=false;rows=[];stack=[];description="";profileOpen=false;note="账号已变更，请刷新列表";}
    property var sections: [
        {id:"popular",title:"热门视频"},{id:"ranking",title:"排行榜"},{id:"weekly",title:"每周必看"},
        {id:"watchlater",title:"稍后再看"},{id:"folders",title:"收藏夹"},{id:"followings",title:"关注的 UP"},
        {id:"my_bangumi",title:"我的追番"},{id:"timeline",title:"新番时间表"},{id:"live_following",title:"关注的直播"}]
    function show(cat,value,from) {origin=from;stack=[];open(cat||"popular",value||{},false);}
    function open(cat,value,nested) {
        if(nested)stack=stack.concat([{category:category,request:request,rows:rows,page:page,more:more,title:title,description:description,following:following,y:list.contentY}]);
        category=cat;request=value||{};rows=[];page=1;more=false;note="";version++;busy=false;
        description="";following=false;profileOpen=false;
        title=value.title||"发现";
        for(var i=0;i<sections.length;i++)if(sections[i].id===cat)title=sections[i].title;
        if(cat==="related")title="相关推荐";
        if(cat==="collection")title="视频合集";
        list.positionViewAtBeginning();load(1,false);
    }
    function load(p,append) {
        if(busy)return;
        var mine=version,account=host.accountGeneration;
        var a={category:category,page:p};if(request.id)a.id=request.id;if(request.bvid)a.bvid=request.bvid;
        busy=true;note="";
        host.job("catalog_library",a,function(r){
            if(mine!==version||account!==host.accountGeneration)return;
            busy=false;
            if(!r.ok){note=host.errText(r);return;}
            page=p;more=r.data.more;if(r.data.title)title=r.data.title;
            description=r.data.description||"";following=r.data.following===true;
            var data=append?rows.slice(0):[];
            for(var i=0;i<r.data.items.length;i++){
                var row=r.data.items[i];row.source_page=p;
                var key=row.bvid||row.ep||row.season||row.room||row.id,exists=false;
                for(var n=0;n<data.length;n++)if((data[n].bvid||data[n].ep||data[n].season||data[n].room||data[n].id)===key){exists=true;break;}
                if(!exists)data.push(row);
            }
            rows=data;
            if(!rows.length)note="这里暂时没有内容";
            if(page>=100){more=false;note="已到接口分页上限";}
        });
    }
    function select(row) {
        if(busy)return;
        if(row.kind==="folder"){open("folder",row,true);return;}
        if(row.kind==="up"){open("up",row,true);return;}
        if(row.kind==="week"){open("week",row,true);return;}
        if(!row.playable){note="该条目当前不可播放";return;}
        var source={category:category,page:row.source_page||page};
        if(request.id)source.id=request.id;if(request.bvid)source.bvid=request.bvid;
        host.catalogQueueSource=source;host.details(row,"detail");
    }
    function back() {
        if(profileOpen){profileOpen=false;return;}
        version++;busy=false;note="";
        if(stack.length){var old=stack[stack.length-1];stack=stack.slice(0,-1);category=old.category;request=old.request;rows=old.rows;page=old.page;more=old.more;title=old.title;description=old.description||"";following=old.following===true;list.forceLayout();list.contentY=old.y;return;}
        host.screen=origin;host.message="";
    }
    Rectangle {width:144;height:parent.height;radius:10;color:Ux.surface}
    ListView {
        x:4;y:3;width:136;height:parent.height-6;clip:true;model:library.sections;spacing:4
        boundsBehavior:Flickable.StopAtBounds
        delegate:BiliButton {width:136;height:50;textSize:19;label:modelData.title;selected:library.category===modelData.id;
            onClicked:{library.stack=[];library.open(modelData.id,{},false);}}
    }
    Rectangle {x:152;width:parent.width-152;height:parent.height;radius:10;color:Ux.surface}
    BiliLabel {x:164;y:2;width:440;height:30;text:library.busy?"正在加载…":library.title+(library.category==="up"?(library.following?" · 已关注 · 简介 ›":" · 简介 ›"):"");font.pixelSize:19;color:Ux.accent
        MouseArea {anchors.fill:parent;enabled:library.category==="up"&&!library.busy;onClicked:library.profileOpen=true}}
    BiliButton {objectName:"biliLibraryRefresh";x:parent.width-88;y:0;width:80;height:34;textSize:17;flat:true;label:"刷新";available:!library.busy;onClicked:library.load(1,false)}
    ListView {
        id:list;objectName:"biliLibraryList";x:160;y:36;width:parent.width-168;height:parent.height-36;clip:true;model:library.rows;spacing:5
        boundsBehavior:Flickable.StopAtBounds;maximumFlickVelocity:1500;cacheBuffer:0
        delegate:Rectangle {
            width:list.width-6;height:72;radius:8;color:touch.pressed?"#392c35":Ux.raised
            property string imageSource: ""
            property int imageVersion: library.version
            Component.onCompleted:if(modelData.cover_key)host.job("thumbnail",{key:modelData.cover_key},function(r){if(r.ok&&imageVersion===library.version)imageSource=r.data.source;})
            Rectangle {x:5;y:5;width:91;height:62;radius:6;color:"#14151a";clip:true
                Image {anchors.fill:parent;source:parent.parent.imageSource;fillMode:Image.PreserveAspectCrop;asynchronous:true;cache:false}
                BiliLabel {anchors.centerIn:parent;text:!parent.parent.imageSource?(modelData.kind==="folder"?"收藏夹":modelData.kind==="up"?"UP":modelData.kind==="week"?"周刊":"bilibili"):"";font.pixelSize:17;color:Ux.muted}}
            BiliLabel {x:107;y:5;width:parent.width-139;height:30;text:modelData.title||"暂无标题";font.pixelSize:21}
            BiliLabel {x:107;y:36;width:parent.width-139;height:26;text:modelData.subtitle||modelData.up||modelData.duration||"查看详情";font.pixelSize:17;color:Ux.muted}
            BiliLabel {anchors.right:parent.right;anchors.rightMargin:10;anchors.verticalCenter:parent.verticalCenter;text:"›";font.pixelSize:27;color:Ux.accent}
            MouseArea {id:touch;anchors.fill:parent;onClicked:library.select(modelData)}
        }
        footer:Item {width:list.width;height:library.more||library.note?52:0
            BiliButton {anchors.fill:parent;visible:library.more&&!library.note;label:library.busy?"正在加载…":"加载更多";available:!library.busy;onClicked:library.load(library.page+1,true)}
            BiliLabel {anchors.fill:parent;visible:!!library.note;text:library.note;font.pixelSize:18;color:Ux.muted;wrapMode:Text.WordWrap}}
        onMovementEnded:if(atYEnd&&library.more&&!library.busy&&!library.note)library.load(library.page+1,true)
    }
    BiliLabel {x:171;y:67;width:parent.width-190;height:87;visible:!library.rows.length;text:library.busy?"正在读取 B 站内容…":library.note;font.pixelSize:20;wrapMode:Text.WordWrap;color:Ux.muted}
    Rectangle {x:156;y:35;width:parent.width-160;height:parent.height-39;radius:10;color:Ux.raised;visible:library.profileOpen;z:5
        MouseArea {anchors.fill:parent}
        Flickable {x:12;y:8;width:parent.width-112;height:parent.height-16;clip:true;contentHeight:bio.implicitHeight
            BiliLabel {id:bio;width:parent.width;text:library.description||"UP 主尚未填写简介";wrapMode:Text.Wrap;font.pixelSize:20;color:Ux.secondary}}
        BiliButton {anchors.right:parent.right;anchors.rightMargin:8;y:8;width:80;height:48;label:"关闭";textSize:18;onClicked:library.profileOpen=false}}
}
