"""Host Qt validation of the same QML driver used on P011; fixture data only."""
import datetime,importlib.util,json,os,pathlib,sys,threading,time
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_QUICK_BACKEND']='software'
from test_client import service,fixture,BASE,NATIVE
from PyQt5.QtCore import QUrl,QTimer,QObject
from PyQt5.QtGui import QGuiApplication,QFontDatabase
from PyQt5.QtQuick import QQuickView
from PyQt5.QtQml import QQmlComponent
from qt_preview_capture import PreviewCapture

def main():
    out=BASE.parents[1]/'logs'/('BiliP011-AutoQtQA-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir();print('LOG_DIR='+str(out),flush=True)
    ui=out/'ui';ui.mkdir()
    toolbox='--toolbox' in sys.argv
    for path in (BASE/'client').iterdir():
        if path.suffix not in ('.qml','.js'):continue
        source=path.read_text(encoding='utf-8').replace('@REMOTE@',out.as_posix())
        source=source.replace('file://'+out.as_posix(),QUrl.fromLocalFile(str(out)).toString())
        if path.name=='BiliPanel.qml':
            at=source.rfind('}')
            source=source[:at]+'\nLoader {source:"BiliAutomation.qml";onLoaded:item.target=panel}\n'+source[at:]
        if path.name=='ToolboxAutomation.qml':
            source=source.replace('id:qa','id:qa;objectName:"hostToolboxAutomation";property string hostFailure:""',1)
            source=source.replace('}catch(e){running=false;completed(false);}',
                                  '}catch(e){hostFailure=String(e);running=false;completed(false);}',1)
        if path.name=='BiliAutomation.qml':
            begin=source.index('        var picture=captureHelper.grabImage(')
            end=source.index('        captures.push(name);',begin)
            # This host renderer has no window framebuffer. Use a real Item
            # capture of the same full 800x480 window; retain all page/privacy
            # gates and backend PNG validation. Never patch the device source.
            source=source[:begin]+'        if(!hostPreviewCapture.capture(name)) throw "CAPTURE_FAILED";\n'+source[end:]
        (ui/path.name).write_text(source,encoding='utf-8')
    backend=service.Backend(str(out),'','',str(out/'unused-account'),{},helper=fixture,automation=True)
    if toolbox:
        for path in (NATIVE/'device').iterdir():
            if path.suffix in ('.qml','.js'):(ui/path.name).write_bytes(path.read_bytes())
        spec=importlib.util.spec_from_file_location('toolbox_server',NATIVE/'runtime/server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules['toolbox_server']=module
        sys.path.insert(0,str(BASE/'client'))
        from toolbox_runtime import Toolbox
        backend.toolbox=Toolbox(str(out),automated=True,preview=True)
        # Windows has no /proc. Deliberate labelled fixture, never device data.
        state=backend.toolbox.state
        sample=dict(cpu_percent=24.5,memory=dict(total=1024**3,used=280*1024**2,available=744*1024**2),
                    storage=dict(total=8*1024**3,available=3*1024**3),uptime=3661,
                    networks=[dict(name='fixture0',rx_per_second=2048,tx_per_second=512)])
        with state.lock:
            state.latest=sample;state.sampler.sample=lambda:dict(sample)
            state.sampler.history=[dict(sample) for _ in range(12)]
            state.sampler.processes=lambda:[dict(pid=123,name='fixture-process',rss_bytes=1024**2,state='S')]
    server=service.HTTPServer(('127.0.0.1',0),service.Handler);server.backend=backend
    server.expected_host='127.0.0.1:'+str(server.server_address[1])
    if toolbox:(out/'bili-endpoint.json').write_text(json.dumps({'url':'http://'+server.expected_host,'toolbox_url':backend.toolbox.endpoint}))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    app=QGuiApplication(sys.argv[:1]);view=QQuickView()
    from visual_fixture import make_fixture
    backend.helper_override=make_fixture(fixture)
    capture=PreviewCapture(view,out/'screenshots',service.UI_QA_CAPTURES+service.TOOLBOX_QA_CAPTURES)
    view.rootContext().setContextProperty('hostPreviewCapture',capture)
    if os.name=='nt':QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    view.rootContext().setContextProperty('nativeFontFamily','Microsoft YaHei' if os.name=='nt' else 'sans-serif')
    view.rootContext().setContextProperty('biliPreviewEndpoint','http://'+server.expected_host)
    warnings=[];compatibility=[]
    def record_warnings(rows):
        for row in rows:
            text=row.toString()
            # Keep Qt 5.10's required Connections syntax. Host Qt 5.15 marks
            # only this legacy spelling deprecated; retain the notice openly.
            (compatibility if 'Implicitly defined onFoo properties in Connections are deprecated' in text else warnings).append(text)
    view.engine().warnings.connect(record_warnings)
    player_component=QQmlComponent(view.engine(),QUrl.fromLocalFile(str(ui/'PlayerAutomation.qml')))
    if player_component.status()==QQmlComponent.Error:warnings.extend(x.toString() for x in player_component.errors())
    harness='''import QtQuick 2.7
Rectangle { width:800;height:480;color:"black"
 BiliPanel {objectName:"biliPanel";x:0;y:106;width:800;height:268}
}'''
    if toolbox:harness=harness.replace('BiliPanel {objectName:"biliPanel"','ToolboxShell {objectName:"toolboxShell"')
    (ui/'HostWindow.qml').write_text(harness,encoding='utf-8')
    view.setSource(QUrl.fromLocalFile(str(ui/'HostWindow.qml')));view.resize(800,480);view.show()
    if view.errors():warnings.extend(error.toString() for error in view.errors())
    deadline=time.monotonic()+200
    def observe():
        if backend.qa_finished or warnings or time.monotonic()>deadline:app.quit()
    timer=QTimer();timer.timeout.connect(observe);timer.start(500)
    app.exec_()
    panel=view.rootObject().findChild(QObject,'biliPanel') if view.rootObject() else None
    host_state={key:panel.property(key) for key in ('screen','tab','message','busy','inputValue')} if panel else {}
    driver=panel.findChild(QObject,'biliAutomation') if panel else None
    if driver:
        host_state['before_exit_message']=driver.property('lastUiMessage')
        host_state['driver_step']=driver.property('step')
        host_state['driver_finished']=driver.property('finished')
        host_state['driver_stepping']=driver.property('stepping')
    host_state['exit_reason']='report' if backend.qa_finished else 'warnings' if warnings else 'deadline' if time.monotonic()>deadline else 'event-loop-ended'
    if driver:
        toolbox_driver=driver.findChild(QObject,'hostToolboxAutomation')
        if toolbox_driver:host_state['toolbox_failure']=toolbox_driver.property('hostFailure')
    view.close();server.shutdown();server.server_close();backend.close()
    path=out/'ui-qa-result.json'
    result=json.loads(path.read_text()) if path.is_file() else {'passed':False,'error':'NO_REPORT'}
    result.update(layer='PC Qt with synthetic API only',device_tested=False,warnings=warnings,qt515_compatibility_notices=compatibility,host_fixture_state=host_state)
    result.update(host_capture_backend='QQuickItem.grabToImage',device_capture_backend_tested=False,
                  host_capture_error=capture.last_error,host_capture_records=capture.records)
    result['passed']=result['passed'] and not warnings
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if result['passed'] and '--archive' in sys.argv:
        from host_ui_results import archive
        archive(out)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
