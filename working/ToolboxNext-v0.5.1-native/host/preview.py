"""Windows/Linux desktop-only Qt preview. Does not invoke ADB or touch the pen."""
import argparse
import os
import pathlib
import sys
import tempfile
import threading
import time

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'runtime'))
from server import State, BoundedServer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots',type=pathlib.Path)
    parser.add_argument('--root',type=pathlib.Path)
    parser.add_argument('--web-test',action='store_true')
    args=parser.parse_args()
    if args.screenshots:
        os.environ['QT_QPA_PLATFORM']='offscreen'
        os.environ['QT_QUICK_BACKEND']='software'
    from PyQt5.QtCore import QUrl, QTimer, Qt, QMetaObject, Q_ARG, QObject, QPointF
    from PyQt5.QtGui import QGuiApplication, QFont, QFontDatabase
    from PyQt5.QtQuick import QQuickView
    from PyQt5.QtTest import QTest, QSignalSpy
    # Preload Qt multimedia dependencies on Windows; QML plugin lookup alone
    # does not always resolve their DLL search directories under Python 3.12.
    from PyQt5 import QtMultimedia, QtMultimediaWidgets
    app=QGuiApplication(sys.argv[:1])
    if os.name=='nt' and args.screenshots:
        # Offscreen plugin has no Windows font discovery. Reference an existing
        # OS font for PC QA only; never copy or bundle a font with the candidate.
        fontpath=pathlib.Path('C:/Windows/Fonts/msyh.ttc')
        if fontpath.is_file(): QFontDatabase.addApplicationFont(str(fontpath))
        app.setFont(QFont('Microsoft YaHei',12))
    userdir=args.root or pathlib.Path(tempfile.mkdtemp(prefix='p011-preview-'))
    state=State(str(userdir),True)
    if args.root is None:
        import io
        sample='P011 文件预览测试\n支持 UTF-8 中文与逐行阅读。\n仅为电脑测试内容，不是笔上的文件。'.encode('utf-8')
        state.store.write_new('Text/预览示例.txt',io.BytesIO(sample),len(sample))
        from PyQt5.QtGui import QImage, QColor, QPainter
        demo=QImage(480,180,QImage.Format_RGB32);demo.fill(QColor('#204050'))
        painter=QPainter(demo);painter.fillRect(30,30,100,120,QColor('#5bd9ae'));painter.fillRect(150,30,140,120,QColor('#69a5e7'));painter.fillRect(310,30,140,120,QColor('#e5b569'));painter.end()
        demo.save(str(userdir/'Pictures'/'preview.png'))
    server=BoundedServer(('127.0.0.1',0),state)
    thread=threading.Thread(target=server.serve_forever);thread.daemon=True;thread.start()
    view=QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.rootContext().setContextProperty('nextEndpoint','http://'+server.expected_host)
    view.rootContext().setContextProperty('nextToken',state.token)
    if os.name=='nt':view.rootContext().setContextProperty('nativeFontFamily','Microsoft YaHei')
    view.setSource(QUrl.fromLocalFile(str(BASE/'device/ExtensionPage.qml')))
    view.resize(800,268)
    view.setTitle('P011 Native Toolbox v0.5.1 — PC PREVIEW')
    if view.status()==QQuickView.Error:
        server.shutdown();server.server_close();state.close();return 1
    view.rootObject().exitRequested.connect(app.quit)
    view.show()
    if args.screenshots:
        args.screenshots.mkdir(parents=True,exist_ok=True)
        root=view.rootObject()
        errors=[]
        view.engine().warnings.connect(lambda rows:errors.extend(str(x.toString()) for x in rows))
        def open_page(name):
            QMetaObject.invokeMethod(root,'open',Q_ARG('QVariant',name))
            QTest.qWait(800)
            loader=root.findChild(QObject,'featureLoader')
            print('PAGE '+name+' loader='+str(loader.property('status'))+' source='+loader.property('source').toString(),flush=True)
        def capture(name):
            QTest.qWait(250)
            grab=root.grabToImage()
            if grab:
                spy=QSignalSpy(grab.ready)
                if grab.image().isNull(): spy.wait(3000)
            assert grab and grab.saveToFile(str(args.screenshots/(name+'.png'))), 'QML capture failed: '+name
        def qa():
            try:
                QTest.qWait(500);capture('home')
                open_page('Files');capture('files')
                assert root.findChild(QObject,'featureLoader').property('item') is not None
                files=root.findChild(QObject,'featureLoader').property('item')
                generation=1770000000123
                files.setProperty('audioGeneration',generation)
                assert files.property('audioGeneration')==generation,'Audio generation truncated to 32 bits'
                files.setProperty('audioGeneration',-1)
                QMetaObject.invokeMethod(files,'openFile',Q_ARG('QVariant',{'path':'Text/预览示例.txt','kind':'text'}));QTest.qWait(500);capture('text-preview')
                assert 'UTF-8 中文' in files.findChild(QObject,'textPreview').property('text'),'Text preview did not load'
                QMetaObject.invokeMethod(files,'openFile',Q_ARG('QVariant',{'path':'Pictures/preview.png','kind':'image'}));QTest.qWait(500);capture('image-preview')
                assert files.findChild(QObject,'imagePreview').property('status')==1,'Image did not decode'
                open_page('Games');capture('snake')
                games=root.findChild(QObject,'featureLoader').property('item')
                for name in ('2048','bricks'):
                    QMetaObject.invokeMethod(games,'start',Q_ARG('QVariant',name));capture(name)
                QMetaObject.invokeMethod(games,'start',Q_ARG('QVariant','snake'))
                def game_state():
                    value=games.property('state');return value.toVariant() if hasattr(value,'toVariant') else value
                button=root.findChild(QObject,'gamePauseButton')
                point=button.mapToScene(QPointF(button.width()/2,button.height()/2)).toPoint()
                initial=game_state()
                QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(380)
                assert not games.property('paused') and initial!=game_state(),'Start button did not advance game'
                before=games.property('state').toVariant() if hasattr(games.property('state'),'toVariant') else games.property('state')
                QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(300)
                assert games.property('paused'),'Pause button did not pause'
                after=games.property('state').toVariant() if hasattr(games.property('state'),'toVariant') else games.property('state')
                assert before==after,'Paused game moved'
                for control in ('gameUpButton','gameDownButton','gameLeftButton','gameRightButton'):
                    item=root.findChild(QObject,control)
                    assert item.width()>=130 and item.height()>=90,'Long-screen control too small'
                canvas=root.findChild(QObject,'gameCanvas')
                assert canvas.width()==480 and canvas.height()>=190,'Central play area too small'
                open_page('Dashboard');capture('dashboard')
                assert root.findChild(QObject,'featureLoader').property('item') is not None
                dashboard=root.findChild(QObject,'featureLoader').property('item')
                dashboard.setProperty('mode','chart')
                # Explicitly synthetic points exercise plot rendering on Windows,
                # whose missing /proc values correctly remain blank above.
                import math
                timer=root.findChild(QObject,'telemetryTimer');timer.setProperty('running',False)
                points=[{'cpu_percent':None if 55<i<62 else 40+25*math.sin(i/9),
                         'memory':{'used':(50+i/4)*1048576,'total':128*1048576}} for i in range(120)]
                root.setProperty('telemetry',{'metrics':dict(points[-1],uptime=7200,storage={'available':1024**3},networks=[{'name':'fixture','rx_per_second':12345,'tx_per_second':6789}]),
                                             'history':points,'scores':{},'transfer':{},'addresses':[]})
                root.setProperty('message','主机合成数据：仅验证图表绘制，不代表学习笔数值')
                capture('dashboard-synthetic')
                timer.setProperty('running',True);root.setProperty('message','')
                open_page('');capture('returned-home')
                if errors: raise RuntimeError('\n'.join(errors))
                print('HOST_QML_QA_PASS pages=Files,Games,Dashboard pause=PASS return=PASS',flush=True)
                app.exit(0)
            except Exception as exc:
                import traceback
                print('QML_WARNINGS '+repr(errors),flush=True)
                from PyQt5.QtQml import QQmlComponent
                for file in ('FilesPage.qml','GamesPage.qml','DashboardPage.qml'):
                    component=QQmlComponent(view.engine(),QUrl.fromLocalFile(str(BASE/'device'/file)))
                    print(file+' '+repr([e.toString() for e in component.errors()]),flush=True)
                traceback.print_exc()
                print('HOST_QML_QA_FAIL '+str(exc),flush=True);app.exit(1)
        QTimer.singleShot(100,qa)
    try: return app.exec_()
    finally: server.shutdown();server.server_close();state.close()


if __name__=='__main__':sys.exit(main())
