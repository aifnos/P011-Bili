// SPDX-License-Identifier: GPL-3.0-or-later
// Embedded 800 x 268; the original parent owns the physical offset/rotation.
import QtQuick 2.7
import "BiliUx.js" as Ux

Rectangle {
    id: panel
    objectName: "biliPanel"
    width: 800; height: 268; color: Ux.background
    property string pageType: "p011BiliPage"
    property var keyboard: null
    property string endpointFile: "file://@REMOTE@/bili-endpoint.json"
    property string endpoint: typeof biliPreviewEndpoint !== "undefined" ? biliPreviewEndpoint : ""
    property string token: ""
    property string screen: "catalog"
    property string tab: "recommend"
    property string message: "正在连接笔上服务…"
    property bool disposed: false
    property bool qaMode: false
    property bool busy: false
    property int epoch: 0
    property var requests: []
    property var jobs: ({})
    property var rows: []
    property var backPages: []
    property var catalogStates: ({})
    property bool appendError: false
    property var commentParent: null
    property double restoreCommentY: 0
    property string detailOrigin: "catalog"
    property var catalogQueueSource: ({})
    property bool detailMore: false
    property var localHistory: []
    property string historyOrigin: "login"
    property var searchHistory: []
    property bool libraryAvailable: false
    property double resumePosition: 0
    property string clearConfirm: ""
    property int rowAt: 0
    property int pageNumber: 1
    property bool more: false
    property string offset: ""
    property string inputValue: ""
    property bool waitingInput: false
    property string searchTerm: ""
    property string searchType: "video"
    property var selectedVideo: ({})
    property int selectedPart: -1
    property int partCount: parts.count
    property string detailError: ""
    property int detailErrorCode: 0
    property int selectedQuality: 0
    property int selectedCodec: 0
    property var codecOptions: []
    property var qualityIds: []
    property string qualityLabel: "自动"
    property int pendingCovers: 0
    property int coverEpoch: 0
    property double coverStarted: 0
    property double catalogX: 0
    property var coverQueue: []
    property var commentRows: []
    property var commentHistory: []
    property string commentAid: ""
    property string commentRoot: ""
    property int commentNext: 0
    property int commentMode: 3
    property int commentPage: 1
    property bool commentMore: false
    property bool loggedIn: false
    property string accountName: ""
    property var qrMatrix: []
    property double qrUntil: 0
    property bool qrPolling: false
    property bool logoutConfirm: false
    property int accountGeneration: 0
    property int qrGeneration: 0
    property bool playing: false
    property var toolboxShell: null
    property string lastPlayEnd: ""
    property int secondsLeft: 0
    property bool readError: false
    property string readErrorKind: ""
    property int readErrorCode: 0
    property int retryPage: 1
    property string retryCursor: ""
    property var detailRequest: ({})
    property string detailOperation: "detail"
    property int commentCursor: 0
    signal exitRequested()

    function errText(reply) {
        var code = reply ? reply.code : -1;
        var kind = reply ? reply.error : "";
        if (kind === "LOGIN_REQUIRED" || code === -101) return "请先在“我的”登录 B 站账号";
        if (kind === "ACTION_DISABLED") return "自动测试中禁止修改账号";
        if (kind === "ACTION_UNCONFIRMED") return "提交结果未确认，请到官方端核对，不要重复提交";
        if (kind === "ACTION_EXPIRED") return "操作已过期，请刷新状态再试";
        if (kind === "LIVE_OFFLINE") return "主播暂未开播，请稍后重试";
        if (kind === "LIVE_RESTRICTED") return "该直播间受限，请在官方端查看提示";
        if (kind === "LOGIN_SECOND_FACTOR") return "账号需要官方二次验证，请先在官方端完成或改用扫码";
        if (kind === "CAPTCHA_UNSUPPORTED") return "当前官方验证码类型尚未适配，请使用扫码登录";
        if (kind === "DRM_UNSUPPORTED") return "该内容启用了 DRM，本机不支持";
        if (kind === "API_VERIFICATION_REQUIRED") return "B 站要求账号验证，请先登录或稍后重试";
        if (code === -10403 || code === -403 || code === 10015002) return "该内容需要相应账号权限，或受地区限制";
        if (code === -352 || code === -412 || code === 412) return "B 站暂时限制了请求，请稍后再试";
        if (kind === "BAD_INPUT" || kind === "BAD_BVID") return "请输入 BV 号、视频或直播链接、ep/ss 号";
        if (kind === "BAD_SEARCH") return "关键词不能为空，中文最多约 50 字";
        if (kind === "QR_EXPIRED") return "二维码已过期，请点重新生成";
        if (kind === "QR_SCHEMA") return "登录地址格式未识别，需要更新客户端适配";
        if (kind === "PLAYER_BUSY") return "播放器正在启动，请稍候";
        if (kind === "QUALITY_UNAVAILABLE") return "该画质当前不可用，请重新选择自动或其他画质";
        if (kind === "CODEC_UNAVAILABLE") return "该视频没有此编码/画质组合，请改为自动或其他编码";
        if (kind === "STORY_UNAVAILABLE") return "官方短视频流暂不可用，请稍后重试";
        if (kind === "NO_SUPPORTED_STREAM" || kind === "MEDIA_HOST_UNSUPPORTED") return "没有本机可播放的视频流";
        if (kind === "RESOURCE_LIMIT") return "此规格预计内存不足，请选择较低画质或其他编码";
        if (kind === "BUSY") return "请求较多，请稍候再试";
        if (kind === "CANCELED") return "操作已取消或试验已结束";
        if (kind === "NETWORK_ERROR" || kind === "HELPER_TIMEOUT") return "网络连接超时，请检查 Wi-Fi 后重试";
        return "请求失败（" + (kind || "本地连接") + " / " + code + "）";
    }
    function http(method, path, data, callback, bootstrap) {
        if (disposed) return;
        var xhr = new XMLHttpRequest();
        var request = {xhr: xhr, at: Date.now(), done: false, callback: callback};
        requests.push(request);
        function finish(value) {
            if (request.done || disposed) return;
            request.done = true; callback(value);
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return;
            if (xhr.status !== 200) {
                var error = null;
                try { error = JSON.parse(xhr.responseText); } catch(e) {}
                finish(error && error.error ? error : {ok:false, error:"LOCAL_HTTP", code:xhr.status}); return;
            }
            try { finish(JSON.parse(xhr.responseText)); }
            catch(e) { finish({ok:false,error:"INVALID_JSON",code:-1}); }
        };
        xhr.open(method, endpoint + path);
        if (bootstrap) xhr.setRequestHeader("X-P011-Native-UI", "bili-qml-runtime");
        else xhr.setRequestHeader("X-P011-Token", token);
        if (method === "POST") xhr.setRequestHeader("Content-Type", "application/json");
        xhr.send(data === null ? "" : JSON.stringify(data));
    }
    function job(op, args, callback) {
        http("POST", "/jobs", {op:op,args:args}, function(reply) {
            if (!reply.job) { callback(reply); return; }
            jobs[reply.job] = {at:Date.now(), next:0, inflight:false, callback:callback};
        }, false);
    }
    function tick() {
        var now = Date.now(), keep = [];
        for (var i=0; i<requests.length; i++) {
            var r = requests[i];
            if (r.done) continue;
            if (now-r.at > 8000) {
                r.done = true; r.xhr.onreadystatechange = function() {}; r.xhr.abort();
                r.callback({ok:false,error:"LOCAL_TIMEOUT",code:-1});
            } else keep.push(r);
        }
        requests = keep;
        var keys = Object.keys(jobs);
        for (var n=0; n<keys.length; n++) {
            var key = keys[n], j = jobs[key];
            if (now-j.at > 55000) { delete jobs[key]; j.callback({ok:false,error:"HELPER_TIMEOUT",code:-1}); continue; }
            if (!j.inflight && now >= j.next) pollJob(key);
        }
    }
    function pollJob(key) {
        var j = jobs[key]; if (!j) return;
        j.inflight = true;
        http("GET", "/jobs/" + key, null, function(reply) {
            if (!jobs[key]) return;
            j.inflight = false;
            if (reply.pending) { j.next = Date.now()+300; return; }
            delete jobs[key]; j.callback(reply);
        }, false);
    }
    function boot() {
        if (endpoint !== "") { bootstrap(); return; }
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || disposed) return;
            try {
                var e = JSON.parse(xhr.responseText);
                if (!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(e.url)) throw "endpoint";
                endpoint = e.url; bootstrap();
            } catch(err) { message = "笔上服务尚未就绪，请退出后重新启动"; }
        };
        xhr.open("GET", endpointFile); xhr.send();
    }
    function bootstrap() {
        http("POST", "/bootstrap", {}, function(reply) {
            if (!reply.token) { message = "本地会话验证失败，请退出重试"; return; }
            token = reply.token; console.log("P011_BILI UI_READY");
            catalog("recommend"); refreshAccount(); refreshLibrary();
        }, true);
    }
    function refreshAccount() {
        var generation=accountGeneration;
        job("status", {}, function(reply) {
            if (generation===accountGeneration && reply.ok) { loggedIn = reply.data.logged_in; accountName = reply.data.name; }
        });
    }
    function leaveLogin() {
        qrGeneration++;
        if (screen === "login" && token !== "") job("qr_cancel", {}, function(reply) {});
        qrMatrix = []; qrPolling = false; qrUntil = 0; logoutConfirm = false;
    }
    function refreshLibrary(callback) {
        job("library",{},function(reply){if(reply.ok){localHistory=reply.data.history;searchHistory=reply.data.searches;libraryAvailable=reply.data.available===true;if(screen==="detail")updateResume();}if(callback)callback();});
    }
    function historyPage() {
        if(screen!=="detail"&&screen!=="history")historyOrigin=screen;
        leaveLogin();epoch++;screen="history";readError=false;busy=true;clearConfirm="";message="";
        refreshLibrary(function(){if(screen==="history")busy=false;});
    }
    function clearLibrary(section) {
        if(clearConfirm!==section){clearConfirm=section;message="再次点击清除，仅影响本机记录";return;}
        job("library_clear",{section:section},function(reply){clearConfirm="";if(reply.ok)refreshLibrary();else message=errText(reply);});
    }
    function stashCatalog() {
        if(!rows.length)return;
        catalogStates[tab]={rows:rows,page:pageNumber,offset:offset,more:more,x:catalogView.contentX,term:searchTerm,type:searchType};
    }
    function catalog(name,refresh) {
        console.log("P011_BILI PAGE catalog " + name);
        stashCatalog();
        leaveLogin(); epoch++; screen = "catalog"; tab = name;readError=false;
        appendError=false;clearConfirm="";
        var saved=catalogStates[name];
        if(!refresh&&saved){rows=saved.rows;pageNumber=saved.page;offset=saved.offset;more=saved.more;rowAt=0;if(name==="search"){searchTerm=saved.term;searchType=saved.type;}busy=false;drawCards();catalogView.forceLayout();catalogView.contentX=Math.max(0,Math.min(saved.x,catalogView.contentWidth-catalogView.width));queueCovers();return;}
        backPages = []; rows = []; rowAt = 0; pageNumber = 1; offset = ""; more = false; cards.clear();
        if (name === "following" && !loggedIn) { busy=false; message="请在“我的”扫码登录，查看关注 UP 的视频"; return; }
        fetchPage(1, "");
    }
    function fetchPage(number, cursor, append, advance) {
        busy = true;readError=false;appendError=false;retryPage=number;retryCursor=cursor;message = "正在加载…"; var mine = epoch,oldAt=rowAt;
        var args = {page:number, offset:cursor};
        if (tab === "search") { args.query=searchTerm; args.type=searchType; }
        job(tab, args, function(reply) {
            if (mine !== epoch || screen !== "catalog") return;
            busy = false;
            if (!reply.ok) { if(append){appendError=true;message="加载失败，点右侧重试";}else readFailure(reply); return; }
            if(append) {
                var combined=rows.slice(), added=0;
                for(var i=0;i<reply.data.items.length&&combined.length<120;i++) {
                    var item=reply.data.items[i],identity=Ux.identity(item);
                    var duplicate=false;
                    for(var j=0;j<combined.length;j++)if(Ux.identity(combined[j])===identity){duplicate=true;break;}
                    if(!duplicate){combined.push(item);added++;cards.append({title:item.title,up:item.up||"UP 主",duration:item.duration,coverKey:item.cover_key,imageSource:"",coverRequested:false,coverAttempts:0,coverRetryAt:0,rowIndex:combined.length-1});}
                }
                rows=combined;pageNumber=number;offset=reply.data.offset;more=reply.data.more&&added>0&&rows.length<120;
                message=added?"":"暂时没有更多内容";
                if(advance&&added){catalogView.forceLayout();catalogView.positionViewAtIndex(Math.min(oldAt+3,rows.length-1),ListView.Beginning);}
                queueCovers();return;
            }
            rows=reply.data.items; rowAt=0; pageNumber=number; offset=reply.data.offset; more=reply.data.more;
            console.log("P011_BILI LIST " + tab + " " + rows.length);
            drawCards();
        });
    }
    function drawCards() {
        coverEpoch++; pendingCovers=0;coverStarted=Date.now();
        coverQueue=[];
        cards.clear();
        for (var i=0; i<rows.length; i++) {
            var row=rows[i]; cards.append({title:row.title, up:row.up || (row.kind==="season"?"番剧":"UP 主"),
                duration:row.duration, coverKey:row.cover_key, imageSource:"", coverRequested:false,coverAttempts:0,coverRetryAt:0,rowIndex:i});
        }
        catalogView.positionViewAtIndex(rowAt,ListView.Beginning);
        catalogX=catalogView.contentX;
        message=rows.length ? "" : "暂无内容，试试刷新";
        queueCovers();
    }
    function queueCovers() {
        if(screen!=="catalog")return;
        // Only visible cards and a small look-ahead enter the two-slot queue.
        var first=Math.max(0,Math.floor(catalogView.contentX/237));
        rowAt=first;
        coverQueue=[];
        for(var i=first;i<Math.min(cards.count,first+5);i++)
            if(!cards.get(i).coverRequested&&cards.get(i).coverAttempts<2&&Date.now()>=cards.get(i).coverRetryAt)coverQueue.push(i);
        pumpCovers();
    }
    function pumpCovers() {
        while(screen==="catalog"&&pendingCovers<2&&coverQueue.length) {
            var index=coverQueue.shift();
            if(index>=cards.count||cards.get(index).coverRequested)continue;
            cards.setProperty(index,"coverRequested",true);
            cards.setProperty(index,"coverAttempts",cards.get(index).coverAttempts+1);
            loadCover(index,cards.get(index).coverKey,epoch,coverEpoch);
        }
    }
    function loadCover(index, key, mine, coverMine) {
        if (!key) return;
        pendingCovers++;
        job("thumbnail", {key:key}, function(reply) {
            if(coverMine===coverEpoch) pendingCovers=Math.max(0,pendingCovers-1);
            if (mine === epoch && screen === "catalog" && index<cards.count && cards.get(index).coverKey===key) {
                if(reply.ok)cards.setProperty(index,"imageSource",reply.data.source);
                else {cards.setProperty(index,"coverRequested",false);cards.setProperty(index,"coverRetryAt",Date.now()+2500);}
            }
            if(coverMine===coverEpoch)pumpCovers();
        });
    }
    function forward() {
        if (busy) return;
        if(appendError){fetchPage(retryPage,retryCursor,true,true);return;}
        // The final viewport can begin one pixel before the fourth card.
        // floor(contentX / stride) alone then stalls the Next button forever.
        if (!catalogView.atXEnd && rowAt+3 < rows.length) { rowAt+=3; catalogView.positionViewAtIndex(rowAt,ListView.Beginning);queueCovers(); }
        else if (more) {
            fetchPage(pageNumber+1, offset,true,true);
        }
    }
    function previous() {
        if (busy) return;
        if (rowAt>0) { rowAt=Math.max(0,rowAt-3);catalogView.positionViewAtIndex(rowAt,ListView.Beginning);queueCovers(); }
        else if (backPages.length) {
            var old=backPages.pop(); rows=old.rows; pageNumber=old.page; offset=old.offset; more=old.more;
            rowAt=Math.floor((Math.max(1,rows.length)-1)/3)*3; drawCards();
        }
    }
    function details(value, op) {
        detailMore=false;
        if(value.kind==="live"){extraPage("live",value);return;}
        console.log("P011_BILI PAGE detail");
        if(screen==="catalog"||screen==="history"||screen==="library"||screen==="extra")detailOrigin=screen;
        resumePosition=0;commentParent=null;descriptionScroll.contentY=0;
        leaveLogin(); epoch++; var mine=epoch; screen="detail";readError=false;detailRequest=value;detailOperation=op||"detail";selectedVideo={}; selectedPart=-1;selectedQuality=0;qualityLabel="自动";detailError="";detailErrorCode=0;parts.clear(); busy=true; message="正在读取详情…";
        job(op || "detail", value, function(reply) {
            if (mine!==epoch || screen!=="detail") return;
            if (!reply.ok) { busy=false;detailError=reply.error||"LOCAL_HTTP";detailErrorCode=reply.code||-1;readFailure(reply); return; }
            selectedVideo=reply.data;
            if(reply.data.kind==="live"){busy=false;extraPage("live",reply.data);return;}
            for(var i=0;i<reply.data.parts.length;i++) parts.append(reply.data.parts[i]);
            // ListModel updates can precede delegate creation by a render
            // turn (Qt 5.10). Do not report an actionable detail page before
            // its first real button exists, or retain a previous season's
            // scroll/flick state when opening a new single-part video.
            partsView.cancelFlick();partsView.forceLayout();
            partsView.currentIndex=parts.count?0:-1;
            partsView.positionViewAtBeginning();
            busy=false;
            message=parts.count ? "" : "暂无可播放选集";
            updateResume();
            if(reply.data.parts_truncated) message="该剧集过多，本机当前仅列出前 2000 集";
        });
    }
    function updateResume() {
        resumePosition=0;
        if(detailOrigin==="extra"&&detailRequest.position>=3&&!detailRequest.finished){
            for(var c=0;c<parts.count;c++){
                var cloud=parts.get(c);
                if((cloud.cid&&cloud.cid===detailRequest.cid)||(cloud.ep&&cloud.ep===detailRequest.ep)){
                    if(selectedPart<0||selectedPart===c){selectedPart=c;resumePosition=detailRequest.position;return;}
                }
            }
        }
        for(var h=0;h<localHistory.length;h++)for(var p=0;p<parts.count;p++) {
            if(selectedPart>=0&&selectedPart!==p)continue;
            var old=localHistory[h],part=parts.get(p);
            if(((part.bvid&&old.bvid===part.bvid&&old.cid===part.cid)||(part.ep&&old.ep===part.ep))&&old.position>=3&&old.position<old.duration-5){selectedPart=p;resumePosition=old.position;return;}
        }
    }
    function playPart(index,fromStart,listen) {
        if(busy || index<0 || index>=parts.count) return;
        selectedPart=index;busy=true; message="正在准备播放…"; lastPlayEnd="";
        console.log("P011_BILI PLAY_REQUEST");
        var args=partArgs(index);args.quality=selectedQuality;args.codec=selectedCodec;var mine=epoch;
        var allParts=[];for(var n=0;n<parts.count;n++){var item=partArgs(n);item.title=selectedVideo.title||"";item.up=selectedVideo.up||"";item.part_title=parts.get(n).title||"";allParts.push(item);}
        var queue=Ux.playlist(detailOrigin==="catalog"?rows:[],selectedVideo,allParts,index);
        args.queue=queue.rows;args.queue_index=queue.index;args.resume=fromStart!==true;
        if(parts.count>1){args.queue=[];args.queue_index=0;args.queue_source={category:"parts",kind:selectedVideo.kind,bvid:selectedVideo.bvid,season:selectedVideo.season,ep:selectedVideo.ep};}
        else if(parts.count===1&&detailOrigin==="library"&&catalogQueueSource.category)args.queue_source=catalogQueueSource;
        if(detailOrigin==="extra"&&args.resume&&resumePosition>0)args.start=resumePosition;
        args.listen=listen===true;
        args.title=selectedVideo.title||"";args.up=selectedVideo.up||"";args.part_title=parts.get(index).title||"";
        job("play", args, function(reply) {
            if(mine!==epoch || screen!=="detail")return;
            busy=false;
            message=reply.ok ? (reply.data.preview ? "正在试看" : "正在播放") : errText(reply);
        });
    }
    function partArgs(index) {
        var p=parts.get(index);
        return {kind:p.kind,bvid:p.bvid,cid:p.cid,ep:p.ep,aid:p.aid};
    }
    function startStory() {
        if(busy||playing)return;
        leaveLogin();epoch++;var mine=epoch;busy=true;lastPlayEnd="";message="正在打开官方短视频流…";
        job("play",{story:true,codec:0,quality:0},function(reply){
            if(mine!==epoch)return;busy=false;
            message=reply.ok?"官方短视频 · 竖持，上滑下一条，下滑上一条，轻点暂停":errText(reply);
        });
    }
    function qualityPage() {
        if(!parts.count || busy)return;
        epoch++;var mine=epoch;screen="quality";busy=true;readError=false;qualities.clear();qualityIds=[];qualityScroll.contentY=0;message="正在读取账号可用的编码与画质…";
        var args=partArgs(Math.max(0,selectedPart));args.codec=selectedCodec;
        job("qualities",args,function(reply){
            if(mine!==epoch || screen!=="quality")return;
            busy=false;if(!reply.ok){readFailure(reply);return;}
            for(var i=0;i<reply.data.items.length;i++)qualities.append({qualityId:reply.data.items[i].id,label:reply.data.items[i].label});
            qualityIds=reply.data.items.map(function(value){return value.id;});
            codecOptions=reply.data.codecs||[];
            message="";
        });
    }
    function chooseCodec(value) {if(busy)return;selectedCodec=value;selectedQuality=0;qualityLabel="自动";qualityPage();}
    function chooseQuality(index) {
        selectedQuality=qualities.get(index).qualityId;qualityLabel=selectedQuality?qualities.get(index).label.split(" ")[0]:"自动";
        screen="detail";message="已选 "+qualityLabel;
    }
    function descriptionPage() {epoch++;screen="description";busy=false;readError=false;message="";}
    function commentsPage(root) {
        if(!parts.count || busy)return;
        if(root&&screen==="comments"&&!commentRoot)commentParent={rows:commentRows,history:commentHistory.slice(),next:commentNext,more:commentMore,page:commentPage,mode:commentMode,cursor:commentCursor,y:commentList.contentY};
        var p=partArgs(Math.max(0,selectedPart));
        commentAid=p.aid||selectedVideo.aid||"";commentRoot=root||"";
        commentHistory=[];commentPage=1;loadComments(0);
    }
    function commentAction(page,parent,text) {
        if(busy||!parts.count)return;
        var p=partArgs(Math.max(0,selectedPart));
        extraPage(page,{bvid:p.bvid,root:parent?(commentRoot||parent):"0",parent:parent||"0",excerpt:text||"",title:selectedVideo.title});
    }
    function loadComments(cursor) {
        epoch++;var mine=epoch;screen="comments";busy=true;readError=false;commentCursor=cursor;message="正在读取评论…";comments.clear();
        var p=partArgs(Math.max(0,selectedPart));
        job("comments",{aid:commentAid,bvid:p.bvid,root:commentRoot,next:cursor,mode:commentMode},function(reply){
            if(mine!==epoch || screen!=="comments")return;
            busy=false;if(!reply.ok){readFailure(reply);return;}
            commentAid=reply.data.aid;commentRows=reply.data.items;commentNext=reply.data.next;
            commentMore=reply.data.more&&commentNext!==cursor&&commentRows.length>0;drawComments();
        });
    }
    function drawComments() {
        readError=false;comments.clear();
        for(var i=0;i<commentRows.length;i++) {
            var r=commentRows[i];comments.append({replyId:r.id,author:r.author,bodyText:r.text,likes:r.likes,replyCount:r.replies,pinned:r.pinned});
        }
        message=commentRows.length?"":"还没有评论";
        commentList.positionViewAtBeginning();
    }
    function moreComments() {
        if(busy||!commentMore)return;
        commentHistory.push({rows:commentRows,next:commentNext,more:commentMore,page:commentPage,y:commentList.contentY,cursor:commentCursor});
        commentPage++;loadComments(commentNext);
    }
    function previousComments() {
        if(busy||!commentHistory.length)return;
        var old=commentHistory.pop();commentRows=old.rows;commentNext=old.next;commentMore=old.more;commentPage=old.page;commentCursor=old.cursor;drawComments();restoreCommentY=old.y||0;commentRestore.restart();
    }
    function inputPage(mode) {
        console.log("P011_BILI PAGE " + mode);
        leaveLogin(); epoch++; busy=false;readError=false;screen=mode; inputValue=mode==="searchInput" ? searchTerm : "";
        message="";clearConfirm="";refreshLibrary();
    }
    function editInput(useNative) {
        inputBoard.open(inputValue,screen==="searchInput",useNative===true);
    }
    function submitInput() {
        if (screen==="openInput") { details({text:inputValue}, "open"); return; }
        searchTerm=inputValue; catalog("search",true);refreshLibrary();
    }
    function account() {
        console.log("P011_BILI PAGE account");
        leaveLogin(); epoch++; screen="login"; busy=false;readError=false;
        if(loggedIn) { message="账号仅保存在笔上，可在此退出本地登录"; return; }
        newQr();
    }
    function newQr() {
        accountGeneration++;qrGeneration++;
        qrMatrix=[]; qrPolling=false; message="正在生成二维码…"; var mine=epoch, generation=qrGeneration;
        job("qr_new",{},function(reply) {
            if(mine!==epoch || generation!==qrGeneration || screen!=="login") return;
            if(!reply.ok) { message=errText(reply); return; }
            qrMatrix=reply.data.matrix; qrUntil=Date.now()+reply.data.expires*1000;
            message="请用哔哩哔哩 App 扫码并确认"; qrCanvas.requestPaint();
        });
    }
    function pollQr() {
        if(screen!=="login" || !qrMatrix.length || qrPolling || loggedIn) return;
        if(Date.now()>=qrUntil) { qrMatrix=[]; message="二维码已过期，请重新生成"; return; }
        qrPolling=true; var mine=epoch, generation=qrGeneration;
        job("qr_poll",{},function(reply) {
            if(mine!==epoch || generation!==qrGeneration || screen!=="login") return;
            qrPolling=false;
            if(!reply.ok) { message=errText(reply); return; }
            if(reply.data.code===0) { accountGeneration++;loggedIn=true; qrMatrix=[]; message="登录成功，可查看关注视频";console.log("P011_BILI LOGIN_CONFIRMED"); refreshAccount(); }
            else if(reply.data.code===86090) message="已扫码，请在手机上确认登录";
            else if(reply.data.code===86038) { qrMatrix=[]; message="二维码已过期，请重新生成"; }
        });
    }
    function logout() {
        if(!logoutConfirm) { logoutConfirm=true; message="再次点击确认，只清除本机的登录凭据"; return; }
        accountGeneration++;qrGeneration++;
        job("logout",{},function(reply) {
            if(reply.ok) { loggedIn=false; accountName=""; logoutConfirm=false; message="已退出本机账号"; }
            else message=errText(reply);
        });
    }
    function goBack() {
        readError=false;
        if(screen==="library"){collectionLibrary.back();return;}
        if(screen==="detail"&&detailOrigin==="library"){epoch++;screen="library";busy=false;message="";return;}
        if(screen==="detail"&&detailOrigin==="extra"){epoch++;screen="extra";busy=false;message="";return;}
        if(screen==="extra"){extras.leave();return;}
        if(screen==="comments"&&commentRoot) {epoch++;commentRoot="";busy=false;var old=commentParent;commentParent=null;if(old){commentRows=old.rows;commentHistory=old.history;commentNext=old.next;commentMore=old.more;commentPage=old.page;commentMode=old.mode;commentCursor=old.cursor;drawComments();restoreCommentY=old.y;commentRestore.restart();}else {commentHistory=[];commentPage=1;loadComments(0);}return;}
        if(screen==="quality"||screen==="description"||screen==="comments") {epoch++;screen="detail";busy=false;message="";return;}
        if(screen==="detail"&&detailOrigin==="history"){historyPage();return;}
        if(screen==="history"&&historyOrigin==="login"){account();return;}
        if(screen!=="catalog") { leaveLogin(); epoch++; screen="catalog"; busy=false;message="左右滑动浏览";pendingCovers=0;coverEpoch++;for(var i=0;i<cards.count;i++)if(!cards.get(i).imageSource)cards.setProperty(i,"coverRequested",false);queueCovers(); }
        else catalog(tab,true);
    }
    function extraPage(page,value) {
        var from=screen==="extra"?extras.origin:screen;
        leaveLogin();epoch++;screen="extra";busy=false;readError=false;message="";
        extras.show(page,value||selectedVideo,from);
    }
    function libraryPage(category,value) {
        detailMore=false;
        var from=screen;leaveLogin();epoch++;screen="library";busy=false;readError=false;message="";
        collectionLibrary.show(category,value||{},from);
    }
    function readFailure(reply) {
        readError=true;readErrorKind=reply.error||"LOCAL_HTTP";
        readErrorCode=typeof reply.code==="number"&&isFinite(reply.code)&&Math.floor(reply.code)===reply.code&&Math.abs(reply.code)<100000000?reply.code:-1;
        message=errText(reply);
    }
    function retryRead() {
        if(busy)return;
        if(readErrorKind==="BAD_INPUT"||readErrorKind==="BAD_BVID") {inputPage("openInput");return;}
        if(screen==="catalog") {epoch++;fetchPage(retryPage,retryCursor);}
        else if(screen==="detail")details(detailRequest,detailOperation);
        else if(screen==="quality")qualityPage();
        else if(screen==="comments")loadComments(commentCursor);
    }
    function quitTrial() {
        leaveLogin(); message="正在退出并恢复原厂界面…";
        http("POST","/exit",{},function(reply){exitRequested();},false);
    }
    function returnToToolbox() {
        if(!toolboxShell){quitTrial();return;}
        leaveLogin();epoch++;busy=false;
        http("POST","/player/stop",{},function(reply){if(reply.ok)toolboxShell.showHome();else message=errText(reply);},false);
    }
    Connections {
        target: panel.keyboard
        ignoreUnknownSignals: true
        onCommitInput: {
            if (panel.waitingInput) { panel.inputValue=t1; panel.waitingInput=false; }
        }
    }
    ListModel { id: cards }
    ListModel { id: parts }
    ListModel { id: qualities }
    ListModel { id: comments }
    Timer { interval:100; running:true; repeat:true; onTriggered:panel.tick() }
    Timer {id:commentRestore;interval:0;onTriggered:{commentList.forceLayout();commentList.contentY=Math.max(0,Math.min(panel.restoreCommentY,commentList.contentHeight-commentList.height));}}
    Timer {interval:1500;running:panel.screen==="catalog";repeat:true;onTriggered:panel.queueCovers()}
    Timer {id:noticeTimer;interval:3200}
    onMessageChanged:if(message)noticeTimer.restart()
    Timer { interval:3500; running:panel.token!==""; repeat:true; onTriggered:panel.pollQr() }
    Timer {
        interval:1500; running:panel.token!==""; repeat:true
        onTriggered: panel.http("GET","/state",null,function(reply){
            panel.playing=reply.playing===true; panel.secondsLeft=reply.remaining || 0;
            if(reply.play_end && reply.play_end!==panel.lastPlayEnd) {
                panel.lastPlayEnd=reply.play_end;
                panel.refreshLibrary();
                if(reply.play_end==="failed") panel.message=reply.play_exit_code===32?"图形资源暂不可用，请退出本次运行后重试":"播放中断，请返回重试（"+reply.play_exit_code+"）";
                else if(panel.screen==="detail") panel.message="播放已结束，可选择其他分 P / 剧集";
            }
        },false)
    }
    BiliButton {objectName:"biliBack";x:8;y:4;width:68;flat:true;label:panel.screen==="catalog"?"刷新":"‹ 返回";textSize:20;onClicked:panel.goBack()}
    Row {x:84;y:4;spacing:4;visible:panel.screen==="catalog"
        BiliButton {objectName:"biliRecommend";width:70;flat:true;label:"推荐";selected:panel.tab==="recommend";onClicked:panel.catalog("recommend",panel.tab==="recommend")}
        BiliButton {objectName:"biliStory";width:88;flat:true;label:"短视频";available:!panel.busy&&!panel.playing;onClicked:panel.startStory()}
        BiliButton {objectName:"biliFollowing";width:70;flat:true;label:"关注";selected:panel.tab==="following";onClicked:panel.catalog("following",panel.tab==="following")}
        BiliButton {objectName:"biliBangumi";width:70;flat:true;label:"番剧";selected:panel.tab==="bangumi";onClicked:panel.catalog("bangumi",panel.tab==="bangumi")}
        BiliButton {objectName:"biliLive";width:70;flat:true;label:"直播";selected:panel.tab==="live_catalog";onClicked:panel.catalog("live_catalog",panel.tab==="live_catalog")}
        BiliButton {objectName:"biliSearch";width:70;flat:true;label:"搜索";selected:panel.tab==="search";onClicked:panel.inputPage("searchInput")}
        BiliButton {objectName:"biliAccount";width:70;flat:true;label:"我的";onClicked:panel.account()}
    }
    BiliButton {objectName:"biliLibraryOpen";x:622;y:4;width:58;flat:true;label:"发现";textSize:18;visible:panel.screen==="catalog";onClicked:panel.libraryPage("popular",{})}
    BiliButton {objectName:"biliDetailMore";x:576;y:4;width:100;flat:true;label:"更多";visible:panel.screen==="detail";onClicked:panel.detailMore=!panel.detailMore}
    BiliButton {objectName:"biliWriteComment";x:576;y:4;width:100;flat:true;label:"写评论";textSize:19;available:!panel.busy;visible:panel.screen==="comments";onClicked:panel.commentAction("compose-comment","","")}
    BiliLabel {x:94;y:4;width:476;height:46;visible:panel.screen!=="catalog";font.pixelSize:24;
        text:panel.screen==="library"?collectionLibrary.title:panel.screen==="extra"?(extras.mediaTitle||extras.title):panel.screen==="detail"?(panel.selectedVideo.kind==="season"?"番剧详情":"视频详情"):panel.screen==="comments"?(panel.commentRoot?"评论回复":panel.commentMode===3?"热门评论":"最新评论"):panel.screen==="description"?"简介":panel.screen==="quality"?"画质与编码":panel.screen==="login"?"我的":panel.screen==="history"?"观看历史":panel.screen==="openInput"?"打开链接":"搜索"}
    BiliButton {objectName:"biliExit";x:684;y:4;width:108;flat:true;label:panel.toolboxShell?"工具箱":"退出";onClicked:panel.returnToToolbox()}
    Rectangle {x:14;y:54;width:772;height:1;color:"#262830"}
    Rectangle {x:14;y:54;width:772;height:2;visible:panel.busy;color:Ux.accent}
    BiliLabel {x:16;y:58;width:640;height:30;visible:panel.screen==="catalog"&&panel.tab==="search";text:"“"+panel.searchTerm+"” · "+(panel.searchType==="video"?"视频":"番剧");font.pixelSize:21;color:Ux.accent}
    Item {
        x:10; y:panel.tab==="search"?92:62; width:cards.count===0?780:702; height:262-y; visible:panel.screen==="catalog"
        ListView {
            id:catalogView;objectName:"biliCatalog";anchors.fill:parent;clip:true
            orientation:ListView.Horizontal;spacing:10;model:cards;cacheBuffer:474
            boundsBehavior:Flickable.StopAtBounds;maximumFlickVelocity:1600;flickDeceleration:2400
            onContentXChanged: {panel.catalogX=contentX;panel.queueCovers();}
            onMovementEnded: if(atXEnd&&panel.more&&!panel.busy)panel.fetchPage(panel.pageNumber+1,panel.offset,true)
            delegate:Rectangle {
                    objectName:"biliCard"+index
                    width:227; height:catalogView.height; radius:10; color:cardTouch.pressed?"#342832":Ux.surface
                    Rectangle { x:0;y:0;width:227;height:parent.height-76;radius:10;color:Ux.raised;clip:true
                        BiliLabel {anchors.centerIn:parent;text:coverAttempts>=2&&!imageSource?"封面暂不可用":"bilibili";font.pixelSize:18;color:Ux.muted}
                        Image { objectName:"biliCover"+index;anchors.fill:parent; source:imageSource; fillMode:Image.PreserveAspectCrop; sourceSize.width:320;sourceSize.height:180;asynchronous:true;cache:false }
                        Rectangle { visible:duration!==""; anchors.right:parent.right;anchors.bottom:parent.bottom; width:durationLabel.width+12;height:25;color:"#b3101115"
                            BiliLabel {id:durationLabel;anchors.centerIn:parent;text:duration;font.pixelSize:16} }
                    }
                    BiliLabel {x:9;y:parent.height-73;width:209;height:49;text:title;wrapMode:Text.Wrap;font.pixelSize:18;lineHeightMode:Text.FixedHeight;lineHeight:23;maximumLineCount:2;verticalAlignment:Text.AlignTop}
                    BiliLabel {x:9;y:parent.height-24;width:209;height:22;text:up;font.pixelSize:16;color:Ux.secondary}
                    MouseArea {id:cardTouch;anchors.fill:parent;preventStealing:false;onClicked:panel.details(panel.rows[rowIndex],"detail")}
            }
        }
        BiliLabel { anchors.fill:parent;anchors.margins:18;visible:cards.count===0;text:panel.busy?"正在获取内容…":panel.message;wrapMode:Text.Wrap;horizontalAlignment:Text.AlignHCenter;color:Ux.secondary;font.pixelSize:24 }
    }
    Column {x:722;y:panel.tab==="search"?92:62;spacing:10;visible:panel.screen==="catalog"&&cards.count>0&&!panel.readError
        BiliButton {objectName:"biliPrevious";width:68;height:(252-parent.y)/2;label:"‹";textSize:40;available:!panel.busy&&!panel.readError&&panel.rowAt>0;onClicked:panel.previous()}
        BiliButton {objectName:"biliNext";width:68;height:(252-parent.y)/2;label:panel.appendError?"重试":"›";textSize:panel.appendError?20:40;available:!panel.busy&&!panel.readError&&((!catalogView.atXEnd&&panel.rowAt+3<panel.rows.length)||panel.more);onClicked:panel.forward()}
    }
    Item {x:14;y:62;width:772;height:174;visible:panel.screen==="searchInput"||panel.screen==="openInput"
        Rectangle {x:0;y:0;width:616;height:59;radius:12;color:"#21232b";border.color:"#55434d"
            BiliLabel {x:14;y:8;width:588;height:44;visible:!panel.inputValue;text:panel.screen==="searchInput"?"搜索视频或番剧":"输入 BV 号、视频或直播链接";color:"#8b8e9b";font.pixelSize:23}
            TextInput {id:input;objectName:"biliInput";x:14;y:8;width:588;height:44;text:panel.inputValue;color:"white";font.family:typeof nativeFontFamily!=="undefined"?nativeFontFamily:"Source Han Sans SC";font.pixelSize:25;readOnly:true;clip:true;onTextChanged:if(text!==panel.inputValue)panel.inputValue=text}
            MouseArea {objectName:"biliEditInput";anchors.fill:parent;onClicked:panel.editInput()}
        }
        BiliButton {objectName:"biliInputSubmit";x:630;y:0;width:142;height:59;label:panel.screen==="openInput"?"打开视频":"搜索";selected:true;onClicked:panel.submitInput()}
        Row {y:80;spacing:12;visible:panel.screen==="searchInput"
            BiliButton {width:130;height:48;label:"视频";selected:panel.searchType==="video";onClicked:panel.searchType="video"}
            BiliButton {width:130;height:48;label:"番剧";selected:panel.searchType==="media_bangumi";onClicked:panel.searchType="media_bangumi"}
            BiliButton {objectName:"biliOpen";width:150;height:48;label:"打开链接";onClicked:panel.inputPage("openInput")}
        }
        BiliLabel {y:84;width:580;height:64;visible:panel.screen==="openInput"&&!panel.qaMode;text:"输入 BV 号、视频或直播链接、番剧编号\n在这里直接打开想看的内容";color:"#9b9da9";font.pixelSize:20;wrapMode:Text.Wrap}
        BiliButton {objectName:"biliSample";y:80;width:300;height:60;label:"自动验收样例";visible:panel.qaMode&&panel.screen==="openInput";onClicked:panel.details({kind:"video",bvid:"BV1Da411Y7U4"},"detail")}
        BiliButton {objectName:"biliNativeInput";x:610;y:80;width:162;height:48;label:"英文 / 数字";onClicked:panel.editInput(true)}
        Row {x:0;y:142;spacing:8;visible:panel.screen==="searchInput"
            Repeater {model:panel.searchHistory.slice(0,3)
                BiliButton {width:190;height:46;textSize:18;label:modelData;onClicked:{panel.inputValue=modelData;panel.submitInput();}}
            }
            BiliButton {objectName:"biliSearchClear";width:172;height:46;visible:panel.searchHistory.length>0;label:panel.clearConfirm==="searches"?"确认清除":"清除搜索记录";textSize:17;onClicked:panel.clearLibrary("searches")}
        }
    }
    Item {x:14;y:61;width:772;height:201;visible:panel.screen==="detail"
        BiliLabel {x:0;y:0;width:337;height:56;text:panel.selectedVideo.title||"视频详情";wrapMode:Text.Wrap;font.pixelSize:22;lineHeightMode:Text.FixedHeight;lineHeight:27;maximumLineCount:2;verticalAlignment:Text.AlignTop}
        BiliLabel {x:0;y:59;width:337;height:26;text:panel.selectedVideo.up||"";font.pixelSize:17;color:"#b6b5c1"}
        BiliButton {objectName:"biliPlayPrimary";x:0;y:89;width:panel.resumePosition>0?226:336;height:50;textSize:22;selected:true;visible:parts.count>0;available:!panel.busy;label:panel.resumePosition>0?"继续 · "+Ux.stamp(panel.resumePosition):"立即播放";onClicked:panel.playPart(Math.max(0,panel.selectedPart))}
        BiliButton {objectName:"biliPlayRestart";x:236;y:89;width:100;height:50;textSize:19;visible:parts.count>0&&panel.resumePosition>0;available:!panel.busy;label:"从头播放";onClicked:panel.playPart(Math.max(0,panel.selectedPart),true)}
        Row {x:0;y:148;spacing:7;visible:parts.count>0
            BiliButton {objectName:"biliDescription";width:96;height:50;textSize:20;label:"简介";available:!panel.busy;onClicked:panel.descriptionPage()}
            BiliButton {objectName:"biliComments";width:96;height:50;textSize:20;label:"评论";available:!panel.busy;onClicked:panel.commentsPage("")}
            BiliButton {objectName:"biliQuality";width:130;height:50;textSize:18;label:"画质 · "+panel.qualityLabel;available:!panel.busy;onClicked:panel.qualityPage()}
        }
        BiliLabel {objectName:"biliPartsHeader";x:352;y:0;width:420;height:29; font.pixelSize:21;color:Ux.secondary;text:panel.busy&&parts.count===0?"正在读取选集…":panel.selectedVideo.kind==="season"?"选集 · 共 "+parts.count+" 集":"分 P · 共 "+parts.count+" P"}
        ListView {id:partsView;objectName:"biliParts";x:352;y:32;width:420;height:111;model:parts;clip:true;spacing:8
            delegate:BiliButton {objectName:"biliPart"+index;width:411;height:50;textSize:20;selected:panel.selectedPart===index;label:(kind==="episode"?"第 "+(index+1)+" 集":"P"+(index+1))+" · "+(badge?"["+badge+"] ":"")+(title||"播放");available:!panel.busy;onClicked:panel.playPart(index)}
            BiliScrollHint {x:417;view:partsView}
        }
        BiliButton {objectName:"biliInteract";x:352;y:148;width:203;height:50;textSize:19;label:"点赞 / 收藏 / 投币";available:!panel.busy&&!!panel.selectedVideo.bvid;onClicked:panel.extraPage("interaction",panel.selectedVideo)}
        BiliButton {objectName:"biliListen";x:566;y:148;width:203;height:50;textSize:20;label:"听视频";available:!panel.busy&&parts.count>0;onClicked:panel.playPart(Math.max(0,panel.selectedPart),false,true)}
        Rectangle {anchors.fill:parent;visible:!panel.busy&&parts.count===0;color:panel.color;radius:12
            BiliLabel {x:12;y:8;width:748;height:42;text:"暂时无法打开";font.pixelSize:27;color:"#ff91b3"}
            BiliLabel {x:12;y:58;width:748;height:102;text:panel.message;wrapMode:Text.Wrap;font.pixelSize:23;maximumLineCount:3;verticalAlignment:Text.AlignTop}
        }
    }
    Item {x:14;y:60;width:772;height:202;visible:panel.screen==="quality"
        BiliLabel {width:212;height:42;text:panel.busy?"正在读取…":panel.codecOptions.length?"视频编码":"自动 · AVC 优先";font.pixelSize:21;color:Ux.secondary}
        Row {x:218;y:0;spacing:6
            Repeater {model:panel.codecOptions
                BiliButton {objectName:"biliCodecOption"+index;width:132;height:44;label:modelData.id===0?"自动":modelData.id===7?"AVC 优先":modelData.id===12?"HEVC 软解":"AV1 软解";selected:panel.selectedCodec===modelData.id;available:!panel.busy;textSize:18;onClicked:panel.chooseCodec(modelData.id)}
            }
        }
        Flickable {id:qualityScroll;objectName:"biliQualityScroll";x:0;y:50;width:772;height:152;contentWidth:772;contentHeight:qualityGrid.height;clip:true
          Grid {id:qualityGrid;columns:3;spacing:9
            Repeater {model:qualities
                BiliButton {objectName:"biliQualityOption"+index;width:250;height:62;label:model.label;textSize:23;selected:qualityId===panel.selectedQuality;onClicked:panel.chooseQuality(index)}
            }
          }
          BiliScrollHint {x:768;view:qualityScroll}
        }
        BiliLabel {x:4;y:55;width:755;height:112;visible:!panel.busy&&qualities.count===0;text:panel.message;wrapMode:Text.Wrap;font.pixelSize:24}
    }
    Flickable {id:descriptionScroll;objectName:"biliDescriptionScroll";x:14;y:61;width:772;height:201;visible:panel.screen==="description";clip:true;contentWidth:width;contentHeight:descriptionText.height+20
        BiliLabel {id:descriptionText;x:5;y:4;width:752;height:implicitHeight;wrapMode:Text.Wrap;font.pixelSize:22;verticalAlignment:Text.AlignTop;text:(panel.selectedVideo.title||"")+"\n\n"+(panel.selectedVideo.description||"暂无简介")}
        BiliScrollHint {x:768;view:descriptionScroll}
    }
    Item {x:14;y:60;width:772;height:202;visible:panel.screen==="comments"
        ListView {id:commentList;objectName:"biliCommentList";x:0;y:0;width:642;height:202;model:comments;spacing:10;clip:true
            delegate:Rectangle {width:636;height:Math.max(94,commentBody.implicitHeight+94);radius:10;color:Ux.surface
                BiliLabel {x:12;y:8;width:505;height:26;text:(pinned?"置顶 · ":"")+author;font.pixelSize:18;color:"#d5bac8"}
                BiliLabel {x:520;y:8;width:112;height:26;text:"赞 "+likes;font.pixelSize:17;color:"#989aa8";horizontalAlignment:Text.AlignRight}
                BiliLabel {id:commentBody;x:12;y:38;width:614;height:implicitHeight;text:bodyText;wrapMode:Text.Wrap;font.pixelSize:21;verticalAlignment:Text.AlignTop}
                BiliButton {objectName:"biliCommentReply"+index;x:12;y:parent.height-50;width:164;height:44;label:"回复";textSize:18;available:!panel.busy;onClicked:panel.commentAction("compose-comment",replyId,bodyText)}
                BiliButton {objectName:"biliCommentLike"+index;x:188;y:parent.height-50;width:164;height:44;label:"评论点赞";textSize:18;available:!panel.busy;onClicked:panel.commentAction("comment-actions",replyId,bodyText)}
                BiliButton {objectName:"biliReplies"+index;x:454;y:parent.height-50;width:171;height:44;visible:!panel.commentRoot;label:replyCount?"查看 "+replyCount+" 条回复":"暂无回复";textSize:18;available:replyCount>0&&!panel.busy&&!panel.commentRoot;onClicked:panel.commentsPage(replyId)}
            }
            BiliScrollHint {x:639;view:commentList}
        }
        Column {x:654;y:0;spacing:5
            BiliButton {objectName:"biliCommentSort";width:118;height:53;textSize:20;label:panel.commentMode===3?"最新":"最热";visible:!panel.commentRoot;available:!panel.busy&&!panel.commentRoot;onClicked:{panel.commentMode=panel.commentMode===3?2:3;panel.commentsPage("");}}
            BiliButton {objectName:"biliCommentPrevious";width:118;height:53;textSize:20;label:"上一页";available:!panel.busy&&panel.commentHistory.length>0;onClicked:panel.previousComments()}
            BiliButton {objectName:"biliCommentNext";width:118;height:53;textSize:20;label:"下一页";available:!panel.busy&&panel.commentMore;onClicked:panel.moreComments()}
            BiliLabel {width:118;height:25;text:"第 "+panel.commentPage+" 页";horizontalAlignment:Text.AlignHCenter;font.pixelSize:17;color:Ux.muted}
        }
        BiliLabel {x:0;y:45;width:638;height:120;visible:comments.count===0;text:panel.busy?"正在读取评论…":panel.message;wrapMode:Text.Wrap;font.pixelSize:23;color:"#a0a2af"}
    }
    Item {x:14;y:57;width:772;height:182;visible:panel.screen==="login"
        Rectangle {x:0;y:0;width:182;height:182;color:"white";visible:panel.qrMatrix.length>0&&!panel.loggedIn
            Canvas {id:qrCanvas;anchors.fill:parent
                onPaint:{var ctx=getContext("2d");ctx.fillStyle="white";ctx.fillRect(0,0,width,height);var n=panel.qrMatrix.length;if(!n)return;var size=Math.floor(width/(n+8)),left=Math.floor((width-n*size)/2);ctx.fillStyle="black";for(var y=0;y<n;y++)for(var x=0;x<n;x++)if(panel.qrMatrix[y].charAt(x)==="1")ctx.fillRect(left+x*size,left+y*size,size,size);}
            }
        }
        BiliLabel {x:203;y:5;width:373;height:55;font.pixelSize:25;wrapMode:Text.Wrap;maximumLineCount:2;text:panel.loggedIn?(panel.accountName||"B 站账号"):"扫码登录，发现更多精彩"}
        BiliLabel {x:203;y:65;width:373;height:38;font.pixelSize:18;color:"#9b9da9";text:"登录信息仅保存在本机"}
        BiliButton {objectName:"biliQrRefresh";x:203;y:117;width:210;height:57;visible:!panel.loggedIn;label:"重新生成二维码";onClicked:panel.newQr()}
        BiliButton {objectName:"biliLogout";x:203;y:117;width:210;height:57;visible:panel.loggedIn;label:panel.logoutConfirm?"确认退出本机":"退出本机登录";onClicked:panel.logout()}
        BiliButton {x:430;y:117;width:210;height:57;visible:panel.loggedIn;label:"查看关注视频";selected:true;onClicked:panel.catalog("following")}
        BiliButton {objectName:"biliPasswordOpen";x:430;y:117;width:210;height:57;visible:!panel.loggedIn;label:"账号密码登录";onClicked:panel.extraPage("password",{})}
        BiliButton {objectName:"biliHistory";x:590;y:60;width:175;height:44;textSize:19;visible:panel.libraryAvailable;label:"本机历史";onClicked:panel.historyPage()}
        BiliButton {objectName:"biliCloudHistoryOpen";x:590;y:7;width:175;height:44;textSize:19;label:"账号历史";available:panel.loggedIn;onClicked:panel.extraPage("cloud",{})}
        BiliButton {objectName:"biliLoginCapability";x:653;y:117;width:112;height:57;textSize:17;label:"我的内容";onClicked:panel.libraryPage("watchlater",{})}
    }
    Item {x:14;y:60;width:772;height:202;visible:panel.screen==="history"
        BiliButton {objectName:"biliHistoryClear";x:602;y:0;width:170;height:44;textSize:19;label:panel.clearConfirm==="history"?"确认清除":"清除本机记录";available:panel.localHistory.length>0;onClicked:panel.clearLibrary("history")}
        BiliLabel {x:4;y:0;width:580;height:44;text:panel.libraryAvailable?"仅保存在本机 · 点击继续观看":"本机记录暂不可用";font.pixelSize:20;color:Ux.secondary}
        ListView {id:historyView;objectName:"biliHistoryList";x:0;y:51;width:772;height:151;model:panel.localHistory;clip:true;spacing:8
            delegate:Rectangle {objectName:"biliHistoryRow"+index;width:762;height:68;radius:10;color:Ux.surface
                BiliLabel {x:12;y:4;width:575;height:31;text:modelData.title||modelData.part_title||"视频";font.pixelSize:22}
                BiliLabel {x:12;y:37;width:575;height:25;text:(modelData.up||"UP 主")+" · "+(modelData.part_title||"");font.pixelSize:17;color:Ux.secondary}
                BiliLabel {x:599;y:16;width:150;height:38;text:Ux.stamp(modelData.position)+" / "+Ux.stamp(modelData.duration);font.pixelSize:18;color:Ux.accent;horizontalAlignment:Text.AlignRight}
                MouseArea {anchors.fill:parent;preventStealing:false;onClicked:panel.details(modelData,"detail")}
            }
            BiliScrollHint {x:768;view:historyView}
        }
        BiliLabel {x:8;y:86;width:755;height:62;visible:panel.localHistory.length===0&&!panel.busy;text:"还没有观看记录，去发现喜欢的视频吧";font.pixelSize:23;horizontalAlignment:Text.AlignHCenter;color:Ux.secondary}
    }
    BiliExtras {id:extras;objectName:"biliExtras";x:14;y:60;width:772;height:202;host:panel;visible:panel.screen==="extra"}
    BiliLibrary {id:collectionLibrary;objectName:"biliLibrary";x:14;y:60;width:772;height:202;host:panel;visible:panel.screen==="library"}
    Rectangle {x:14;y:60;width:772;height:202;radius:10;color:Ux.surface;visible:panel.screen==="detail"&&panel.detailMore
        BiliLabel {x:20;y:8;width:720;height:37;text:"探索更多内容";font.pixelSize:23;color:Ux.accent}
        Row {x:16;y:60;spacing:12
            BiliButton {width:235;height:66;label:"UP 主投稿";available:!!panel.selectedVideo.mid;onClicked:panel.libraryPage("up",{id:panel.selectedVideo.mid})}
            BiliButton {width:235;height:66;label:"视频合集";available:panel.selectedVideo.collection_available===true;onClicked:panel.libraryPage("collection",{bvid:panel.selectedVideo.bvid})}
            BiliButton {width:235;height:66;label:"相关推荐";available:!!panel.selectedVideo.bvid;onClicked:panel.libraryPage("related",{bvid:panel.selectedVideo.bvid})}}
        BiliButton {objectName:"biliSeasonFollow";x:16;y:140;width:235;height:50;visible:!!panel.selectedVideo.season;label:"追番管理";onClicked:{panel.detailMore=false;panel.extraPage("season-follow",panel.selectedVideo);}}
        BiliButton {objectName:"biliDanmakuCompose";x:263;y:140;width:235;height:50;label:"发送弹幕";available:parts.count>0&&!panel.busy;onClicked:{var p=panel.partArgs(Math.max(0,panel.selectedPart));p.position=panel.resumePosition||0;p.title=panel.selectedVideo.title;panel.detailMore=false;panel.extraPage("compose-danmaku",p);}}
        BiliButton {objectName:"biliCloudSyncOpen";x:510;y:140;width:235;height:50;label:"云端记录设置";onClicked:{panel.detailMore=false;panel.extraPage("cloud-sync",{});}}}
    Rectangle {objectName:"biliReadError";x:0;y:56;width:800;height:212;visible:panel.readError&&!panel.busy;color:panel.color;z:3
        MouseArea {anchors.fill:parent}
        BiliLabel {x:26;y:5;width:748;height:37;text:"暂时无法打开";font.pixelSize:27;color:"#ff91b3"}
        BiliLabel {x:26;y:44;width:748;height:64;text:panel.message;wrapMode:Text.Wrap;maximumLineCount:2;font.pixelSize:23;verticalAlignment:Text.AlignTop}
        BiliButton {objectName:"biliRetry";x:26;y:122;width:224;height:52;selected:true;label:panel.readErrorKind==="BAD_INPUT"||panel.readErrorKind==="BAD_BVID"?"修改输入":"重试当前页面";onClicked:panel.retryRead()}
        BiliButton {objectName:"biliErrorBack";x:262;y:122;width:160;height:52;label:"返回";onClicked:panel.goBack()}
    }
    Rectangle {x:8;y:237;width:784;height:29;radius:7;color:"#ef242630";z:4;visible:noticeTimer.running&&!panel.busy&&!panel.readError&&panel.message!==""&&!(panel.screen==="catalog"&&cards.count===0)&&!(panel.screen==="comments"&&comments.count===0)
        BiliLabel {objectName:"biliMessage";x:10;width:764;height:29;text:panel.message;font.pixelSize:17;color:Ux.secondary}
    }
    BiliInput {id:inputBoard;objectName:"biliKeyboard";anchors.fill:parent;z:10;visible:false
        lookup:function(code,callback){panel.http("POST","/pinyin",{code:code},callback,false);}
        onAccepted:panel.inputValue=value
    }
    Component.onCompleted: boot()
    Component.onDestruction: {
        console.log("P011_BILI UI_DESTROYED");
        disposed=true;qrMatrix=[];token="";
        for(var i=0;i<requests.length;i++){requests[i].xhr.onreadystatechange=function(){};requests[i].xhr.abort();}
        jobs=({});requests=[];
    }
}
