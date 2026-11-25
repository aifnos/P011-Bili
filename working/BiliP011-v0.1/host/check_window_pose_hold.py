"""Offscreen Qt test of the real automation component; no device/network."""
import json
import os
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_QUICK_BACKEND']='software'
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQml import QQmlComponent,QQmlEngine


def main():
    app=QGuiApplication([]);engine=QQmlEngine()
    component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'client/PlayerAutomation.qml')))
    if component.isError():raise ValueError([e.toString() for e in component.errors()])
    probe=component.create()
    if probe is None:raise ValueError('Automation component not created')
    engine.globalObject().setProperty('probe',engine.newQObject(probe))
    checks=[]
    def evaluate(source):
        result=engine.evaluate(source)
        if result.isError():raise ValueError(result.toString())
        return result.toVariant()
    assert evaluate('probe.screenReady(false)') is True;checks.append('ordinary-mode-no-hold')
    probe.setProperty('screenHoldMs',12000)
    assert evaluate('probe.screenReady(false)') is False;checks.append('wrong-pose-not-ready')
    assert evaluate('probe.screenReady(true)') is False;checks.append('first-pose-starts-hold')
    assert probe.property('screenStableAt')>0;checks.append('clock-recorded')
    probe.setProperty('stage',48)
    at=evaluate('Date.now()')-13000
    probe.setProperty('screenStableAt',at)
    # EOS/replay is not a new window/orientation and must not restart the hold.
    evaluate('probe.run({player:{generation:2,story:true,portrait:true,active:false,position:0}})')
    assert probe.property('stage')==48;checks.append('inactive-clip-not-advanced')
    assert probe.property('screenStableAt')==at;checks.append('eos-keeps-window-hold')
    evaluate('probe.run({player:{generation:2,story:true,portrait:true,active:true,position:3,muted:true,danmaku_visible:false,dm_area:50,dm_opacity:75,dm_size:120,dm_speed:125,aspect:0}})')
    assert probe.property('stage')==59;checks.append('loop-resume-advances')
    probe.setProperty('screenStableAt',at)
    assert evaluate('probe.screenReady(false)') is False and probe.property('screenStableAt')==0
    checks.append('orientation-change-resets-hold')
    print(json.dumps(dict(passed=True,device_tested=False,layer='host actual QML component',checks=checks)))
    probe.deleteLater();app.processEvents()


if __name__=='__main__':main()
