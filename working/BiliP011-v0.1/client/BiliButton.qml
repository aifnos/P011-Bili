import QtQuick 2.0
import "BiliUx.js" as Ux
Rectangle {
    id: button
    property string label: ""
    property bool selected: false
    property bool available: true
    property bool flat: false
    property int textSize: 22
    signal clicked()
    signal held()
    property bool holdEnabled: false
    property bool didHold: false
    width: 88; height: 46; radius: 10
    color: area.pressed ? "#44303d" : selected ? (flat ? "#291c25" : Ux.selected) : flat ? "transparent" : Ux.raised
    opacity: available ? 1 : 0.38
    Behavior on color { ColorAnimation { duration: 90 } }
    BiliLabel { anchors.fill: parent; anchors.margins: 6; text: button.label; color: button.selected&&button.flat ? "#ff91b3" : "#f5f5f7"; font.pixelSize: button.textSize; horizontalAlignment: Text.AlignHCenter }
    Rectangle { visible:button.flat&&button.selected; anchors.horizontalCenter:parent.horizontalCenter;anchors.bottom:parent.bottom;width:24;height:3;radius:1.5;color:"#fb7299" }
    MouseArea { id: area; anchors.fill: parent; enabled: button.available; preventStealing:false;
        onPressed:button.didHold=false
        onPressAndHold:if(button.holdEnabled){button.didHold=true;button.held();}
        onClicked:if(!button.didHold)button.clicked()
    }
}
