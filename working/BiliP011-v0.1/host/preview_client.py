"""PC-only real Qt/QML UI QA against the private service with synthetic data."""
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading

os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_QUICK_BACKEND']='software'
from test_client import service, fixture, BASE
from PyQt5.QtCore import QUrl, QTimer, QObject, QPoint, QPointF, QMetaObject, Q_ARG, Qt
from PyQt5.QtGui import QGuiApplication, QFont, QFontDatabase
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest, QSignalSpy


def main():
    embedded='--embedded' in sys.argv
    out=BASE.parents[1]/'logs'/('BiliP011-Client-QtQA-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    print('LOG_DIR='+str(out),flush=True)
    temp=tempfile.TemporaryDirectory(prefix='p011-bili-qt-')
    root=pathlib.Path(temp.name);(root/'account').mkdir()
    backend=service.Backend(str(root),'','',str(root/'account'),{},helper=fixture)
    backend.library=service.Library(str(root/'library'))
    backend.library.record(dict(kind='video',bvid='BV1Da411Y7U4',cid='1',title='合成续播测试',up='测试 UP',part_title='第一 P'),32,120)
    server=service.HTTPServer(('127.0.0.1',0),service.Handler);server.backend=backend
    server.expected_host='127.0.0.1:'+str(server.server_address[1])
    t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    app=QGuiApplication(sys.argv[:1])
    if os.name=='nt':
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc');app.setFont(QFont('Microsoft YaHei',12))
    from visual_fixture import make_fixture
    visual_fixture=make_fixture(fixture);backend.helper_override=visual_fixture
    view=QQuickView();view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.rootContext().setContextProperty('biliPreviewEndpoint','http://'+server.expected_host)
    view.rootContext().setContextProperty('nativeFontFamily','Microsoft YaHei' if os.name=='nt' else 'sans-serif')
    warnings=[];view.engine().warnings.connect(lambda rows:warnings.extend(x.toString() for x in rows))
    source=BASE/'client/BiliPanel.qml'
    if embedded:
        from build_awake_trial import client_bridge
        # Test the EXACT stock scene-change handler, extracted offline from the
        # pinned v2.4.0 binary, with harmless stand-ins for its sibling Items.
        stock=(BASE/'out/v240-layout-cb8d6a78617d50f6/main.qml').read_text(encoding='utf-8')
        begin=stock.index('onSceneSourceChanged: {')+len('onSceneSourceChanged: ')
        at=begin;depth=0
        while at<len(stock):
            if stock[at]=='{':depth+=1
            if stock[at]=='}':
                depth-=1
                if not depth:break
            at+=1
        handler=stock[begin:at+1]
        for qml in (BASE/'client').iterdir():
            if qml.suffix in ('.qml','.js'):shutil.copyfile(qml,root/qml.name)
        remote='/'+root.as_posix() if os.name=='nt' else root.as_posix()
        bridge=(BASE/'bridge/Bridge.qml').read_text(encoding='utf-8').replace('@SESSION@','a'*24).replace('@REMOTE@',remote)
        (root/'Bridge.qml').write_text(client_bridge(bridge,remote),encoding='utf-8')
        (root/'lease.json').write_text(json.dumps({'session':'a'*24,'seq':-1,'active':False}),encoding='utf-8')
        harness='''import QtQuick 2.10
Rectangle { width:800;height:480;color:"#000000"
 QtObject {id:engineSocket;property bool allowed:true;function sendEnableSysAutoOffScreen(value){allowed=value;}}
 Rectangle {id:main;objectName:"stockMain";x:0;y:106;width:800;height:268;color:"black"
  property bool bEnterPicFormKey:false
  property bool bEnterSpeechFormKey:false
  property bool bEnterCameraFormKey:false
  Loader {id:sceneLoader}
  Rectangle {id:inner;objectName:"stockDesktop";anchors.fill:parent;color:"#763030"
   Rectangle {id:topdrawer;objectName:"stockDrawer";property bool interactive:true;z:200;width:400;height:90;color:"#e04040"}
   Rectangle {z:10;width:190;height:60;color:"#ff8800"}
   Item {id:navi;anchors.fill:parent;property string sceneSource:""
    Loader {source:"Bridge.qml";onLoaded:item.navigator=navi}
    onSceneSourceChanged: @HANDLER@
   }
  }
 }
}'''.replace('@HANDLER@',handler)
        source=root/'Integration.qml';source.write_text(harness,encoding='utf-8')
    view.setSource(QUrl.fromLocalFile(str(source)));view.resize(800,480 if embedded else 268);view.show()
    result={'layer':'PC Qt + synthetic API only','embedded_stock_handler':embedded,'device_tested':False,'passed':False,'checks':[]}
    if view.status()==QQuickView.Error:
        result['warnings']=warnings;print(json.dumps(result));return 1
    panel=None if embedded else view.rootObject()
    def capture(name):
        QTest.qWait(200);grab=view.contentItem().grabToImage();spy=QSignalSpy(grab.ready)
        if grab.image().isNull():spy.wait(3000)
        picture=grab.image();assert not picture.isNull(),'Window content capture unavailable'
        if embedded:
            assert picture.save(str(out/(name+'-window.png')))
            picture=picture.copy(0,106,800,268)
        assert picture.save(str(out/(name+'.png')))
    def find_item(name):
        item=panel.findChild(QObject,name)
        if item is not None:return item
        # ListView delegates are parented through its visual contentItem, not
        # necessarily through the panel's QObject ownership tree.
        pending=list(panel.childItems())
        while pending:
            item=pending.pop()
            if item.objectName()==name:return item
            pending.extend(item.childItems())
        raise AssertionError('Missing visual item: '+name)
    def click(name):
        if name=='biliOpen' and panel.property('screen')!='searchInput':click('biliSearch')
        if name in ('biliRecommend','biliFollowing','biliBangumi','biliSearch','biliAccount','biliStory'):
            for _ in range(4):
                if panel.property('screen')=='catalog':break
                click('biliBack')
        item=find_item(name)
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
        QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,QPoint(int(point.x()),int(point.y())));QTest.qWait(700)
    def invoke(name,value=None):
        if value is None: QMetaObject.invokeMethod(panel,name)
        else: QMetaObject.invokeMethod(panel,name,Q_ARG('QVariant',value))
        QTest.qWait(700)
    def check(name,condition):
        if not condition and panel is not None:
            result['failure_state']={key:panel.property(key) for key in ('screen','tab','rowAt','pageNumber','appendError','readError','more','busy')}
            result['failure_state']['cards']=find_item('biliCatalog').property('count')
        assert condition,name
        result['checks'].append(name)
    def qa():
        nonlocal panel
        try:
            QTest.qWait(3000 if embedded else 2200)
            if embedded:
                main=view.rootObject().findChild(QObject,'stockMain')
                panel=next((x for x in main.childItems() if x.objectName()=='biliPanel'),None)
                check('stock scene owns client',panel is not None and panel.parentItem() is main)
                check('stock desktop hidden',not view.rootObject().findChild(QObject,'stockDesktop').property('visible'))
                check('stock drawer disabled',not view.rootObject().findChild(QObject,'stockDrawer').property('interactive'))
                check('no duplicate physical offset',panel.x()==0 and panel.y()==0 and panel.width()==800 and panel.height()==268)
            panel.setProperty('qaMode',True)
            check('bootstrap',bool(panel.property('token')))
            check('recommendations',find_item('biliCatalog').property('count')==7 and not panel.property('busy'));check('synthetic cover decoded',find_item('biliCover0').property('status')==1);capture('01-recommendations')
            catalog=find_item('biliCatalog');point=catalog.mapToScene(QPointF(620,72))
            QTest.mousePress(view,Qt.LeftButton,Qt.NoModifier,QPoint(int(point.x()),int(point.y())))
            for delta in range(20,341,20):QTest.mouseMove(view,QPoint(int(point.x()-delta),int(point.y())),20)
            QTest.mouseRelease(view,Qt.LeftButton,Qt.NoModifier,QPoint(int(point.x()-340),int(point.y())))
            QTest.qWait(700)
            check('home drag scrolls without opening card',panel.property('screen')=='catalog' and catalog.property('contentX')>50)
            capture('01b-home-swipe');click('biliRecommend')
            fail_append=[True]
            def paged(op,args):
                data=visual_fixture(op,args)
                if op=='recommend':
                    page=args.get('page',1)
                    if page==2 and fail_append[0]:raise service.Failure('NETWORK_ERROR')
                    for n,row in enumerate(data['items']):row['bvid']='BV%010d'%(page*100+n)
                    data['more']=page<3
                return data
            backend.helper_override=paged;click('biliRecommend');click('biliNext');click('biliNext');click('biliNext')
            check('append failure retains visible cards',panel.property('appendError') and not panel.property('readError') and find_item('biliCatalog').property('count')==7)
            fail_append[0]=False;click('biliNext')
            check('arrow retry appends instead of replacing',not panel.property('appendError') and find_item('biliCatalog').property('count')==14 and panel.property('rowAt')>3)
            backend.helper_override=visual_fixture;click('biliRecommend')
            click('biliNext');check('large pagination button',panel.property('rowAt')==3)
            click('biliFollowing');check('following login gate','登录' in panel.property('message') and 'UP' in panel.property('message'));capture('02-following-login-gate')
            click('biliBangumi');check('bangumi listing',panel.property('tab')=='bangumi');capture('03-bangumi')
            click('biliSearch');click('biliEditInput')
            keyboard=panel.findChild(QObject,'biliKeyboard')
            check('offline keyboard opens',keyboard.property('visible'))
            # BiliInput owns the reusable vendor/offline adapter. Exercise its
            # visible child keys, not the obsolete keyboard implementation API.
            for letter in 'dianying':click('biliKey_'+letter)
            QTest.qWait(1500);capture('04-offline-pinyin')
            click('biliKeyboardDone')
            check('offline Chinese input',panel.property('inputValue')=='电影')
            panel.setProperty('inputValue','开源硬件');capture('04-search-input')
            click('biliInputSubmit');check('search results',panel.property('tab')=='search' and not panel.property('busy'));capture('05-search-results')
            check('search keyword retained',panel.property('searchTerm')=='开源硬件')
            # Restore an independent feed's scroll and selected keyword.
            click('biliRecommend');click('biliNext');QTest.qWait(300)
            before_x=find_item('biliCatalog').property('contentX')
            click('biliBangumi');click('biliRecommend')
            check('tab restores scroll position',abs(find_item('biliCatalog').property('contentX')-before_x)<3)
            check('other tabs do not overwrite search keyword',panel.property('searchTerm')=='开源硬件')
            click('biliOpen');panel.setProperty('qaMode',False);QTest.qWait(100)
            check('normal page hides test content',not find_item('biliSample').property('visible'));capture('05b-open-ready')
            panel.setProperty('qaMode',True);click('biliSample');check('video details',panel.property('screen')=='detail' and not panel.property('busy'));capture('06-video-details')
            check('explicit part count','共 4 P' in panel.findChild(QObject,'biliPartsHeader').property('text'))
            check('explicit part number',find_item('biliPart0').property('label').startswith('P1 ·'))
            check('resume and restart are distinct touch targets',panel.property('resumePosition')==32 and find_item('biliPlayRestart').property('visible') and '0:32' in find_item('biliPlayPrimary').property('label'))
            click('biliDescription');check('description scroll',panel.property('screen')=='description');capture('07-description');click('biliBack')
            click('biliQuality');check('qualities loaded',find_item('biliQualityOption4').property('visible'));check('soft codecs clearly labelled','软解' in find_item('biliCodecOption2').property('label') and '软解' in find_item('biliCodecOption3').property('label'));capture('08-qualities')
            click('biliQualityOption2');check('quality selection',panel.property('selectedQuality')==32 and panel.property('screen')=='detail')
            click('biliComments');check('comments loaded',find_item('biliCommentList').property('count')==8);capture('09-comments')
            click('biliCommentNext');check('comment pagination',panel.property('commentPage')==2 and not panel.property('busy'));capture('10-comments-next')
            comment_list=find_item('biliCommentList');comment_list.setProperty('contentY',50);QTest.qWait(100)
            click('biliReplies0');check('reply context',bool(panel.property('commentRoot')) and not panel.property('busy'));capture('10b-replies')
            click('biliBack');check('reply back retains parent page and scroll',panel.property('commentPage')==2 and not panel.property('commentRoot') and abs(comment_list.property('contentY')-50)<3)
            click('biliCommentPrevious');check('comment back page',panel.property('commentPage')==1)
            click('biliCommentSort');check('comment sort',panel.property('commentMode')==2 and not panel.property('busy'))
            click('biliBack');check('comment back to details',panel.property('screen')=='detail')
            click('biliBack');check('return to list',panel.property('screen')=='catalog')
            click('biliAccount');check('QR matrix memory only',panel.property('screen')=='login' and panel.property('qrUntil')>0)
            # Deliberately do not screenshot a login page, even in fixture mode.
            click('biliHistory');check('local history opens without account',panel.property('screen')=='history' and find_item('biliHistoryList').property('count')==1);capture('10c-history')
            click('biliHistoryRow0')
            check('history detail resumes the recorded part',panel.property('screen')=='detail' and panel.property('resumePosition')==32)
            click('biliBack');check('history detail returns to history',panel.property('screen')=='history')
            click('biliBack');check('history returns to account context',panel.property('screen')=='login')
            click('biliHistory');click('biliHistoryClear');check('history clear first tap only confirms',find_item('biliHistoryList').property('count')==1)
            click('biliHistoryClear');check('history clear second tap is scoped',find_item('biliHistoryList').property('count')==0 and bool(backend.library.load()['searches']))
            click('biliSearch');click('biliSearchClear');check('search clear first tap only confirms',bool(backend.library.load()['searches']))
            click('biliSearchClear');check('search clear second tap succeeds',not backend.library.load()['searches'])
            click('biliRecommend');check('login canceled',panel.property('screen')=='catalog')
            def failing(op,args):
                if op=='recommend':raise service.Failure('NETWORK_ERROR')
                return fixture(op,args)
            backend.helper_override=failing;click('biliRecommend')
            check('network error readable',panel.property('readError') and '网络' in panel.property('message'))
            check('error owns the complete content area',find_item('biliReadError').height()==212 and not find_item('biliNext').property('visible'))
            capture('11-network-error')
            backend.helper_override=fixture;click('biliRetry')
            check('network retry restores cards',not panel.property('readError') and find_item('biliCard0').property('visible'))
            backend.helper_override=lambda op,args: {'items':[],'more':False,'offset':''} if op=='recommend' else fixture(op,args)
            click('biliRecommend');check('empty state readable',not panel.property('readError') and '暂无内容' in panel.property('message'))
            check('empty state hides unused navigation',not find_item('biliNext').property('visible') and find_item('biliCatalog').width()==780);capture('12-empty-state')
            def permission(op,args):
                if op=='detail':raise service.Failure('API_ERROR',-10403)
                return fixture(op,args)
            backend.helper_override=permission;click('biliOpen');click('biliSample')
            check('permission is not network failure',panel.property('readError') and '权限' in panel.property('message'));capture('13-permission-error')
            backend.helper_override=fixture;click('biliRetry');check('detail retry',panel.property('partCount')==4 and not panel.property('readError'))
            def comments_offline(op,args):
                if op=='comments':raise service.Failure('HELPER_TIMEOUT')
                return fixture(op,args)
            backend.helper_override=comments_offline;click('biliComments')
            check('comments error has retry',panel.property('readError') and find_item('biliRetry').property('visible'));capture('14-comments-error')
            backend.helper_override=fixture;click('biliRetry');check('comments retry',not panel.property('readError') and find_item('biliCommentList').property('count')==8)
            click('biliBack')
            def qualities_offline(op,args):
                if op=='qualities':raise service.Failure('QUALITY_UNAVAILABLE')
                return fixture(op,args)
            backend.helper_override=qualities_offline;click('biliQuality')
            check('quality failure readable',panel.property('readError') and '画质' in panel.property('message'))
            backend.helper_override=fixture;click('biliRetry');check('quality retry',not panel.property('readError') and find_item('biliQualityOption4').property('visible'))
            click('biliOpen');panel.setProperty('inputValue','not-a-valid-bv');click('biliInputSubmit')
            check('invalid input actionable',panel.property('readError') and find_item('biliRetry').property('label')=='修改输入');capture('15-input-error')
            click('biliRetry');check('invalid input edit route',panel.property('screen')=='openInput' and not panel.property('readError'))
            check('no QML runtime warnings',not warnings)
            result['passed']=True
        except Exception as exc:result['error']=str(exc)
        finally:app.quit()
    QTimer.singleShot(200,qa)
    app.exec_();view.close();server.shutdown();server.server_close();backend.close();temp.cleanup()
    result['warnings']=warnings
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
