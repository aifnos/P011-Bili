"""Real Qt widgets, synthetic accounts only. No ADB or network account writes."""
import datetime,json,os,pathlib,tempfile,threading
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_QUICK_BACKEND']='software'
from test_client import service,fixture,BASE
from visual_fixture import make_fixture
from PyQt5.QtCore import QUrl,QTimer,QObject,QPoint,QPointF,QMetaObject,Q_ARG,Qt
from PyQt5.QtGui import QGuiApplication,QFont,QFontDatabase
from PyQt5.QtQuick import QQuickView
from PyQt5.QtQml import QQmlComponent
from PyQt5.QtTest import QTest,QSignalSpy

def main():
    out=BASE.parents[1]/'logs'/('BiliP011-Features-QtQA-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir();print('LOG_DIR='+str(out),flush=True)
    tmp=tempfile.TemporaryDirectory(prefix='p011-features-');root=pathlib.Path(tmp.name);(root/'account').mkdir();writes=[];relation={'like':False,'coin':0,'favorite':False}
    app=QGuiApplication([]);QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');app.setFont(QFont('Microsoft YaHei',12))
    visual=make_fixture(fixture)
    def fake(op,a):
        if op=='media_context':return {'aid':'123','cid':a['cid'],'duration':120,'ordinary':True}
        if op=='danmaku_send':writes.append(dict(a));return {'confirmed':True,'visible':False}
        if op=='catalog_library':
            category=a['category'];page=a.get('page',1)
            if category in ('folders','followings','weekly'):
                kind={'folders':'folder','followings':'up','weekly':'week'}[category]
                return {'items':[dict(kind=kind,id=str(i+1),title='合成'+category+' · '+str(i+1),subtitle='分类导航与长标题触控测试') for i in range(6)],'more':False}
            return {'items':[dict(kind='video',bvid='BV'+str((page-1)*20+i).zfill(10),mid='42',title='合成发现视频 '+str((page-1)*20+i+1)+' · 长标题验证',up='测试 UP',duration='02:30') for i in range(20)],'more':page<3}
        if op=='relation':return dict(relation)
        if op=='season_relation':return {'following':False,'title':'合成番剧'}
        if op=='season_follow':writes.append(dict(a));return {'confirmed':True,'state_available':False}
        if op=='interaction':
            writes.append(dict(a));relation['like']=True
            return {'confirmed':True,'state_available':True,'relation':dict(relation)}
        if op=='favorites':return {'items':[{'id':str(i+1),'title':'合成收藏夹 '+str(i+1),'selected':i==0} for i in range(5)]}
        if op=='account_history':return {'items':[dict(kind='video',bvid='BV1Da411Y7U4',cid='1',title='合成账号历史 · 第 '+str(i+1)+' 条',up='合成 UP',duration='01:00',position=12,finished=False,playable=True) for i in range(6)],'cursor':{'max':'2','view_at':'1','business':'archive'},'more':a.get('max','0')=='0'}
        if op=='live_catalog':return {'items':[dict(kind='live',room=str(i+1),title='合成直播间 · '+str(i+1),up='测试主播',duration='直播') for i in range(7)]}
        if op=='live_detail':return dict(kind='live',room=a['room'],title='合成直播间 · 长标题与触摸布局测试',live_status=1,description='只验证界面，不是在线直播')
        return visual(op,a)
    backend=service.Backend(str(root),'','',str(root/'account'),{},helper=fake)
    plays=[]
    def play_fixture(args,generation):plays.append(args);return {'started':True}
    backend.play=play_fixture
    server=service.HTTPServer(('127.0.0.1',0),service.Handler);server.backend=backend
    server.expected_host='127.0.0.1:'+str(server.server_address[1])
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    view=QQuickView();view.rootContext().setContextProperty('biliPreviewEndpoint','http://'+server.expected_host);view.rootContext().setContextProperty('nativeFontFamily','Microsoft YaHei')
    warnings=[];view.engine().warnings.connect(lambda rows:warnings.extend(x.toString() for x in rows));view.setSource(QUrl.fromLocalFile(str(BASE/'client/BiliPanel.qml')));view.resize(800,268);view.show();panel=view.rootObject()
    result={'layer':'PC Qt synthetic fixtures only','device_tested':False,'account_writes':False,'passed':False,'checks':[],'captures':[]}
    def find(name):
        todo=[panel]
        while todo:
            node=todo.pop()
            if node.objectName()==name:return node
            todo.extend(node.childItems())
        raise AssertionError('Missing '+name)
    def invoke(obj,name,*args):QMetaObject.invokeMethod(obj,name,*[Q_ARG('QVariant',v) for v in args]);QTest.qWait(800)
    def click(name):
        obj=find(name);p=obj.mapToScene(QPointF(obj.width()/2,obj.height()/2));QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,QPoint(int(p.x()),int(p.y())));QTest.qWait(800)
    def check(name,value):assert value,name;result['checks'].append(name)
    def capture(name):
        view.rootObject().setVisible(False);QTest.qWait(60);view.rootObject().setVisible(True);QTest.qWait(150)
        grab=view.rootObject().grabToImage();spy=QSignalSpy(grab.ready)
        if grab.image().isNull():spy.wait(2000)
        assert not grab.image().isNull();assert grab.image().save(str(out/(name+'.png')));result['captures'].append(name)
    def qa():
        try:
            QTest.qWait(1700);extra=find('biliExtras')
            automation=QQmlComponent(view.engine(),QUrl.fromLocalFile(str(BASE/'client/BiliFeatureAutomation.qml')))
            check('device automation native helper types',automation.status()==QQmlComponent.Ready)
            dry=automation.create();check('device automation can instantiate',dry is not None);dry.deleteLater()
            catalogAutomation=QQmlComponent(view.engine(),QUrl.fromLocalFile(str(BASE/'client/BiliCatalogAutomation.qml')))
            check('catalog device automation types',catalogAutomation.status()==QQmlComponent.Ready)
            dry=catalogAutomation.create();check('catalog automation instantiates',dry is not None);dry.deleteLater()
            click('biliLive');check('live catalog',panel.property('tab')=='live_catalog');capture('01-live-catalog')
            click('biliCard0');check('live detail',extra.property('page')=='live');check('live button',find('biliLivePlay').property('available'));capture('02-live-detail');click('biliBack')
            invoke(panel,'extraPage','interaction',{'bvid':'BV1Da411Y7U4','title':'合成视频 · 互动操作验收'})
            check('relation loads intent',bool(extra.property('intent')));capture('03-interactions')
            click('biliCoin1');check('coin requires confirmation',not writes and bool(extra.property('confirm')));capture('04-coin-confirm')
            click('biliCoin1');check('one coin fixture submitted once',len(writes)==1 and writes[0]['count']==1);check('intent consumed',not extra.property('intent'))
            click('biliRelationRefresh');obj=find('biliLike');point=obj.mapToScene(QPointF(obj.width()/2,obj.height()/2));p=QPoint(int(point.x()),int(point.y()))
            QTest.mousePress(view,Qt.LeftButton,Qt.NoModifier,p);QTest.qWait(1100);QTest.mouseRelease(view,Qt.LeftButton,Qt.NoModifier,p);QTest.qWait(900)
            check('long hold sends only triple',len(writes)==2 and writes[-1]['action']=='triple')
            click('biliRelationRefresh');click('biliFavorites');check('folders list',extra.property('page')=='favorites');capture('05-favorites');click('biliFolder0');check('favorite confirmation',len(writes)==2);click('biliFolder0');check('favorite exact folder',len(writes)==3 and writes[-1]['folder']=='1' and writes[-1]['value'] is False)
            invoke(panel,'extraPage','cloud',{});check('cloud history visible',find('biliCloudHistory').property('count')==6);capture('06-cloud-history');click('biliCloudNext');check('cloud cursor exhaustion',not extra.property('more'));click('biliCloudPrevious');check('cloud back page',extra.property('more'))
            invoke(panel,'extraPage','password',{});check('empty login blocked',not find('biliPasswordSubmit').property('available'));capture('07-password-empty')
            extra.setProperty('password','SYNTHETIC_ONLY');click('biliPassword');board=find('biliLoginInput');check('password input own keyboard',board.property('secret') and not board.property('nativeActive'));capture('08-password-masked')
            # The password board covers every printable ASCII punctuation,
            # including characters absent from the ordinary search keyboard.
            secretBoard=next(n for n in board.childItems() if n.property('symbolPage') is not None)
            invoke(secretBoard,'key','123');invoke(secretBoard,'key','!');invoke(secretBoard,'key','#+=');invoke(secretBoard,'key','\\')
            check('password symbols second page',secretBoard.property('symbolPage')==1 and secretBoard.property('value').endswith('!\\'))
            click('biliKeyboardDone');click('biliBack');check('password cleared on leave',extra.property('password')=='')
            invoke(panel,'libraryPage','popular',{});library=find('biliLibrary')
            check('library public rows',find('biliLibraryList').property('count')==20);capture('09-library-popular')
            invoke(library,'load',2,True);check('library append without replacement',find('biliLibraryList').property('count')==40)
            invoke(library,'open','folders',{},False);check('folder navigation rows',find('biliLibraryList').property('count')==6);capture('10-library-folders')
            invoke(library,'select',{'kind':'folder','id':'42','title':'合成收藏夹'});check('folder content',library.property('category')=='folder');capture('11-library-videos')
            invoke(library,'back');check('folder back restores parent',library.property('category')=='folders' and find('biliLibraryList').property('count')==6)
            invoke(library,'open','followings',{},False);capture('12-library-followings')
            invoke(library,'select',{'kind':'up','id':'42','title':'合成 UP'});check('up uploads',library.property('category')=='up');capture('13-library-up')
            invoke(library,'open','weekly',{},False);capture('14-library-weekly')
            invoke(library,'select',{'kind':'week','id':'1','title':'合成每周必看'});check('weekly detail',library.property('category')=='week')
            invoke(library,'select',{'kind':'video','bvid':'BV1Da411Y7U4','playable':True,'source_page':1})
            check('library to detail',panel.property('screen')=='detail' and panel.property('detailOrigin')=='library');click('biliBack');check('detail back to library',panel.property('screen')=='library')
            invoke(panel,'extraPage','cloud',{});invoke(panel,'details',{'kind':'video','bvid':'BV1Da411Y7U4','cid':'1','position':12,'finished':False},'detail')
            check('cloud part resume retained',panel.property('resumePosition')==12);capture('15-cloud-resume-fixture')
            invoke(panel,'playPart',0,False,False);check('cloud actual play start transmitted',plays[-1].get('start')==12)
            check('multi part body compact and server owned',plays[-1]['queue_source']['category']=='parts' and not plays[-1]['queue'] and len(json.dumps(plays[-1]).encode())<4096)
            panel.setProperty('detailOrigin','library');panel.setProperty('catalogQueueSource',{})
            detail=fixture('detail',{});detail['parts']=detail['parts'][:1]
            backend.helper_override=lambda op,a: detail if op=='detail' else fake(op,a)
            invoke(panel,'details',{'kind':'video','bvid':'BV1Da411Y7U4'},'detail');invoke(panel,'playPart',0,True,False)
            check('single video rejects no empty catalog source',len(plays)==2 and 'queue_source' not in plays[-1])
            invoke(panel,'extraPage','compose-comment',{'bvid':'BV1Da411Y7U4','root':'0','parent':'0'})
            check('comment empty blocked',not find('biliCommentSend').property('available'))
            extra.setProperty('draft','这是一条合成测试评论，不会提交到真实账号。');capture('16-comment-compose')
            before=len(writes);click('biliCommentSend');check('comment double confirmation',len(writes)==before);capture('17-comment-confirm')
            click('biliCommentSend');check('comment exact fixture once',len(writes)==before+1 and writes[-1]['message'].startswith('这是一条') and not extra.property('intent'))
            backend.features.note_comments('BV1Da411Y7U4','',[{'id':'123'}],backend.qr_generation)
            invoke(panel,'extraPage','comment-actions',{'bvid':'BV1Da411Y7U4','root':'123','parent':'123','excerpt':'合成评论原文 · 回复上下文绑定'})
            capture('18-comment-actions');click('biliExtraPositive');click('biliExtraPositive');check('comment like scope bound',writes[-1]['parent']=='123' and writes[-1]['action']=='comment_like')
            invoke(panel,'extraPage','season-follow',{'season':'42','title':'合成番剧 · 追番操作验证'});capture('19-season-follow')
            before=len(writes);click('biliExtraPositive');check('follow double confirmation',len(writes)==before);click('biliExtraPositive');check('follow exact season fixture',len(writes)==before+1 and writes[-1]['season']=='42')
            invoke(panel,'extraPage','compose-danmaku',{'bvid':'BV1Da411Y7U4','cid':'1','position':30,'title':'合成视频 · P1'})
            check('danmaku empty blocked',not find('biliDanmakuSend').property('available'))
            extra.setProperty('draft','这是一条合成弹幕，仅验证界面。');capture('20-danmaku-compose')
            before=len(writes);click('biliDanmakuSend');check('danmaku explicit confirmation',len(writes)==before)
            click('biliDanmakuSend');check('danmaku exact part and time',len(writes)==before+1 and writes[-1]['cid']=='1' and writes[-1]['position']==30 and not extra.property('intent'))
            check('danmaku visibility not fabricated','未确认' in extra.property('note'))
            backend.helper_override=lambda op,a: {'logged_in':True,'name':'合成账号'} if op=='status' else fake(op,a)
            invoke(panel,'extraPage','cloud-sync',{});check('cloud initially off',not backend.media_actions.enabled);capture('21-cloud-sync-off')
            click('biliCloudSyncToggle');check('cloud double confirmation',not backend.media_actions.enabled)
            click('biliCloudSyncToggle');check('cloud opted in for session',backend.media_actions.enabled);capture('22-cloud-sync-enabled')
            click('biliCloudSyncRefresh');click('biliCloudSyncToggle');check('cloud can disable',not backend.media_actions.enabled)
            check('no QML warnings',not warnings);result['passed']=True
        except Exception as exc:result['error']=str(exc)
        finally:app.quit()
    QTimer.singleShot(200,qa);app.exec_();view.close();server.shutdown();server.server_close();backend.close();tmp.cleanup()
    result['warnings']=warnings;(out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
