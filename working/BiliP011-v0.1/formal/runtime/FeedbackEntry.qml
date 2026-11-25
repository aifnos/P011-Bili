// SPDX-License-Identifier: GPL-3.0-or-later
// The stock SetMainPage supplies this page's 800 x 268 content rectangle.
import QtQuick 2.7
import "qrc:/ZybQmlFiles/Funcs/UILogics.js" as UILogic

Item {
    id: entry
    anchors.fill: parent
    property string pageType: "p011BiliPage"
    property bool leaving: false
    function leave() {
        if (leaving) return;
        leaving = true;
        if (panelLoader.item) panelLoader.item.closeFormal();
        UILogic.backToSetPage();
    }
    Loader {
        id: bridgeLoader
        source: "Bridge.qml"
    }
    Loader {
        id: panelLoader
        anchors.fill: parent
        source: "BiliPanel.qml"
        onLoaded: {
            item.exitRequested.connect(entry.leave);
        }
    }
    Rectangle {
        anchors.fill: parent
        color: "#16171b"
        visible: panelLoader.status === Loader.Error
        Text {
            anchors.centerIn: parent
            text: "B 站页面加载失败，请返回设置后重试"
            color: "white"
            font.pixelSize: 24
        }
        Rectangle {
            x: 12; y: 8; width: 120; height: 48
            color: "#36383e"
            Text { anchors.centerIn: parent; text: "返回设置"; color: "white"; font.pixelSize: 22 }
            MouseArea { anchors.fill: parent; onClicked: entry.leave() }
        }
    }
    Component.onDestruction: {
        if (panelLoader.item) panelLoader.item.closeFormal();
    }
}
