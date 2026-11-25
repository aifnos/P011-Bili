"""Small labelled synthetic thumbnails for host UI QA only, never bundled.

Prepared in memory on the GUI thread. No downloads, personal images or files.
"""
from PyQt5.QtCore import QBuffer,QByteArray,QIODevice,Qt,QPoint
from PyQt5.QtGui import QImage,QColor,QPainter,QFont,QPolygon

def make_fixture(base):
    images=[]
    for color,tag in (('#765577','VIDEO 01'),('#28676e','VIDEO 02'),('#586299','VIDEO 03')):
        picture=QImage(320,180,QImage.Format_RGB32);picture.fill(QColor(color))
        p=QPainter(picture);p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen);p.setBrush(QColor('#30ffffff'));p.drawEllipse(204,-50,200,200)
        p.setBrush(QColor('#f5f5f7'));p.drawPolygon(QPolygon([QPoint(33,42),QPoint(33,78),QPoint(63,60)]))
        p.setPen(QColor('#f5f5f7'));p.setFont(QFont('Microsoft YaHei',12));p.drawText(24,121,tag)
        p.setFont(QFont('Microsoft YaHei',10));p.drawText(24,150,'合成测试封面');p.end()
        data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly);assert picture.save(buffer,'PNG');images.append(bytes(data))
    def fixture(op,args):
        if op=='image':
            import re
            found=re.search(r'layout-([0-2])\.png(?:@|$)',args.get('url',''))
            return images[int(found.group(1)) if found else 0]
        value=base(op,args)
        if op in ('recommend','search','bangumi','following'):
            for n,row in enumerate(value['items']):row['cover']='https://i0.hdslb.com/bfs/archive/layout-%d.png'%(n%3)
        return value
    return fixture
