// SPDX-License-Identifier: GPL-3.0-or-later
// One input adapter for search/BV/links. Vendor assets stay in the firmware's
// own qrc. Chinese composition remains our offline component.
import QtQuick 2.7
Item {
    id: control
    property var lookup: null
    property var candidates: offline.candidates
    property bool nativeActive: false
    property var nativeBoard: null
    property var nativeEditor: null
    property bool secret: false
    signal accepted(string value)
    signal canceled()
    function findNative(predicate) {
        var pending=nativeBoard?[nativeBoard]:[],count=0;
        while(pending.length&&count++<1500){var v=pending.pop();if(predicate(v))return v;if(v.children)for(var i=0;i<v.children.length;i++)pending.push(v.children[i]);}
        return null;
    }
    function nativeKey(text) {return findNative(function(v){return typeof v.text!=="undefined"&&v.text===text&&typeof v.clicked==="function";});}
    function open(text,useChinese,preferNative) {
        visible=true;nativeActive=false;offline.visible=false;
        if(!secret&&(preferNative||!useChinese)){
            if(!nativeBoard){
                var component=Qt.createComponent("qrc:/ZybQmlFiles/ZybVirturlKeyBoard/ZybKeyBoard.qml");
                if(component.status===Component.Ready)nativeBoard=component.createObject(nativeLayer,{width:800,height:268,x:0,y:268});
                if(nativeBoard)nativeEditor=findNative(function(v){return typeof v.tipText!=="undefined"&&typeof v.insert==="function"&&typeof v.cursorPosition!=="undefined";});
            }
            if(nativeBoard&&nativeEditor){
                // Reset the vendor show/hide toggle first. Its original commit
                // button logs entered text; our opaque header intercepts that
                // entire row and commits privately, without invoking it.
                nativeBoard.hideKeyboard();nativeBoard.showKeyboard();nativeEditor.maximumLength=512;
                nativeEditor.text=text;nativeEditor.cursorPosition=text.length;nativeEditor.tipText="输入关键词或 BV / 链接";
                nativeActive=true;return;
            }
        }
        offline.secret=secret;offline.open(text,secret?false:useChinese);
    }
    function clearSecret(){if(!secret)return;if(nativeEditor)nativeEditor.text="";offline.value="";offline.composing="";offline.candidates=[];}
    function done(){var value=nativeEditor?nativeEditor.text:"";nativeActive=false;visible=false;accepted(value);}
    Item {id:nativeLayer;anchors.fill:parent;visible:control.nativeActive;clip:true}
    Rectangle {visible:control.nativeActive;z:20;x:0;y:0;width:800;height:76;color:"#101115"
        MouseArea {anchors.fill:parent;onClicked:{}}
        BiliLabel {x:10;y:5;width:434;height:44;text:control.nativeEditor?control.nativeEditor.text:"";elide:Text.ElideLeft;font.pixelSize:24}
        BiliLabel {x:10;y:50;width:434;height:24;text:"英文 / 数字 · 上下滑动切换键区";font.pixelSize:16;color:"#9698a7"}
        BiliButton {objectName:"biliNativeChinese";x:456;y:10;width:106;height:56;label:"中文";onClicked:control.open(control.nativeEditor.text,true,false)}
        BiliButton {objectName:"biliNativeCancel";x:574;y:10;width:106;height:56;label:"取消";onClicked:{control.nativeActive=false;control.visible=false;control.canceled();}}
        BiliButton {objectName:"biliNativeDone";x:692;y:10;width:102;height:56;label:"完成";selected:true;onClicked:control.done()}
    }
    BiliKeyboard {id:offline;anchors.fill:parent;visible:false;lookup:control.lookup
        onAccepted:{control.visible=false;control.accepted(value);control.clearSecret();}
        onCanceled:{control.visible=false;control.clearSecret();control.canceled();}
        onNativeRequested:control.open(value,false,true)
    }
}
