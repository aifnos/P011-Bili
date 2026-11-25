"""PC Qt only: real detail/model replacement, no playback, ADB or live API."""
import datetime,json,os,pathlib,sys,tempfile,threading,time
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_QUICK_BACKEND']='software'
from test_client import service,fixture,BASE
from PyQt5.QtCore import QUrl,QObject,QPointF,QMetaObject,Q_ARG
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest

def main():
    out=BASE.parents[1]/'logs'/('BiliP011-PartList-Qt-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    count=[4]
    def helper(op,args):
        value=fixture(op,args)
        if op=='detail':value['parts']=value['parts'][:count[0]]
        return value
    with tempfile.TemporaryDirectory(prefix='p011-parts-') as temp:
        backend=service.Backend(temp,'','',str(pathlib.Path(temp)/'unused-account'),{},helper=helper)
        server=service.HTTPServer(('127.0.0.1',0),service.Handler);server.backend=backend
        server.expected_host='127.0.0.1:'+str(server.server_address[1])
        threading.Thread(target=server.serve_forever,daemon=True).start()
        app=QGuiApplication(sys.argv[:1]);view=QQuickView();warnings=[]
        view.engine().warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
        view.rootContext().setContextProperty('biliPreviewEndpoint','http://'+server.expected_host)
        view.rootContext().setContextProperty('nativeFontFamily','sans-serif')
        view.setSource(QUrl.fromLocalFile(str(BASE/'client/BiliPanel.qml')));view.resize(800,268);view.show()
        panel=view.rootObject();checks=[];observations=[];report={'device_tested':False,'network':'loopback fixture only'}
        def check(name,value):
            if not value:raise AssertionError(name)
            checks.append(name)
        def wait(condition):
            until=time.monotonic()+6
            while time.monotonic()<until:
                QTest.qWait(20)
                if condition():return
            raise AssertionError('Bounded Qt readiness wait expired')
        def visible_part():
            pending=list(panel.childItems())
            while pending:
                item=pending.pop()
                if item.objectName()=='biliPart0':return item
                pending.extend(item.childItems())
            return None
        try:
            check('panel loaded',panel is not None)
            wait(lambda:bool(panel.property('token')) and not panel.property('busy'))
            parts=panel.findChild(QObject,'biliParts')
            for cycle in range(3):
                for size in (4,1):
                    count[0]=size
                    QMetaObject.invokeMethod(panel,'details',Q_ARG('QVariant',{'kind':'video','bvid':'BV1Da411Y7U4'}),Q_ARG('QVariant','detail'))
                    wait(lambda:not panel.property('busy') and panel.property('partCount')==size)
                    # Capture the first event turn where data reports ready;
                    # no arbitrary extra settling delay hides a missing item.
                    item=visible_part()
                    point=item.mapToItem(parts,QPointF(0,0)) if item is not None else None
                    observations.append(dict(cycle=cycle,count=size,content_y=parts.property('contentY'),first_present=item is not None,first_y=point.y() if point is not None else None))
                    check('first delegate ready %d/%d'%(cycle,size),item is not None)
                    check('first part in viewport %d/%d'%(cycle,size),0<=point.y()<=parts.height()-item.height())
                    if size==4:
                        QMetaObject.invokeMethod(parts,'positionViewAtEnd');QTest.qWait(40)
                        check('scrolled season %d'%cycle,parts.property('contentY')>10)
            check('no QML warnings',not warnings);report['passed']=True
        except Exception as error:report.update(passed=False,error=str(error))
        finally:view.close();server.shutdown();server.server_close();backend.close()
        report.update(checks=checks,observations=observations,warnings=warnings)
        (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
