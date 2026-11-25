import QtQuick 2.7
Rectangle {
    property var view: null
    parent:view
    width:3;radius:1.5;color:"#c0a2b0";opacity:view&&view.moving?0.85:0.35
    visible:view&&view.contentHeight>view.height+2
    height:view?Math.max(22,view.height*view.visibleArea.heightRatio):0
    y:view?Math.max(0,Math.min(view.height-height,view.height*view.visibleArea.yPosition)):0
}
