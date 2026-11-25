"""PC fixture capture only: QtTest's window grab is empty on offscreen/Windows.

Never used by a P011 bundle. Keep the device's window-backed capture unchanged.
"""
from PyQt5.QtCore import QObject,pyqtSlot,QMetaObject,Qt
from PyQt5.QtTest import QSignalSpy,QTest


class PreviewCapture(QObject):
    def __init__(self,view,directory,allowed_names):
        super().__init__()
        self.view=view;self.directory=directory;self.allowed=frozenset(allowed_names)
        self.last_error='';self.records=[];self.busy=False

    def reject(self,reason):
        self.last_error=reason;return False

    @pyqtSlot(str,result=bool)
    def capture(self,name):
        if self.busy:return self.reject('CAPTURE_REENTRANT')
        if name not in self.allowed:return self.reject('CAPTURE_NAME_REJECTED')
        root=self.view.rootObject()
        panel=root.findChild(QObject,'biliPanel') if root is not None else None
        if panel is None:return self.reject('CAPTURE_PANEL_MISSING')
        if panel.property('screen') in ('login','extra') or panel.property('playing'):
            return self.reject('CAPTURE_ACCOUNT_OR_PLAYER_BLOCKED')
        path=self.directory/(name+'.png')
        if not self.directory.is_dir() or self.directory.is_symlink() or path.exists() or path.is_symlink():
            return self.reject('CAPTURE_PATH_REJECTED')
        self.busy=True
        try:
            # A layer grab of the window's non-visual contentItem can omit
            # unchanged child nodes on Qt 5.15's Windows software backend.
            # Detach/reveal the host root to rebuild all render nodes. A mere
            # translation still leaves stale regions during Flickable motion.
            # Grab its real painted Rectangle; never modify device captures.
            root.setVisible(False);self.view.requestUpdate();QTest.qWait(80)
            root.setVisible(True);self.view.requestUpdate();QTest.qWait(150)
            # The tiny stock-style back arrow is a Canvas without an
            # onVisibleChanged repaint; rebuilding the host scene can discard
            # that texture. Request its real paint, not a pixel substitution.
            for child in root.findChildren(QObject):
                if 'Canvas' in child.metaObject().className() and child.property('visible') and 0<float(child.property('width') or 0)<60 and 0<float(child.property('height') or 0)<60:
                    QMetaObject.invokeMethod(child,'requestPaint',Qt.DirectConnection)
            self.view.requestUpdate();QTest.qWait(80)
            grab=root.grabToImage()
            spy=QSignalSpy(grab.ready)
            if grab.image().isNull():spy.wait(1000)
            picture=grab.image()
            if picture.isNull():return self.reject('CAPTURE_EMPTY')
            if picture.width()!=800 or picture.height()!=480:return self.reject('CAPTURE_SIZE')
            regions=[]
            if name.startswith('toolbox-') and name not in ('toolbox-snake','toolbox-2048','toolbox-bricks'):
                regions.append((20,120,30,42))
            if name=='toolbox-2048':regions.extend(((30,190,100,55),(666,190,100,55),(666,287,100,55)))
            if not name.startswith('toolbox-') and name not in ('04-offline-keyboard','16-input-component'):
                regions.append((686,111,105,47))
            for x,y,w,h in regions:
                light=sum(1 for px in range(x,x+w) for py in range(y,y+h)
                          if min(picture.pixelColor(px,py).red(),picture.pixelColor(px,py).green(),picture.pixelColor(px,py).blue())>175)
                if light<12:return self.reject('CAPTURE_CONTROL_INCOMPLETE')
            if not picture.save(str(path),'PNG'):return self.reject('CAPTURE_SAVE_FAILED')
            self.records.append(dict(name=name,width=picture.width(),height=picture.height()))
            self.last_error='';return True
        finally:self.busy=False
