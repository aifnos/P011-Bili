// Offline Pinyin/ASCII board, entirely inside the 800 x 268 content region.
import QtQuick 2.7
Rectangle {
    id: board
    color:"#101115"
    property string value:""
    property bool secret:false
    property string composing:""
    property bool chinese:true
    property bool capitals:false
    property bool symbols:false
    property int symbolPage:0
    property bool needsCandidate:false
    property var candidates:[]
    property int candidateAt:0
    property int generation:0
    property var lookup:null
    signal accepted(string value)
    signal canceled()
    signal nativeRequested(string value)
    function open(text, useChinese) {value=text;chinese=useChinese;composing="";candidates=[];candidateAt=0;symbols=false;symbolPage=0;capitals=false;needsCandidate=false;generation++;visible=true;}
    function changed() {
        generation++;candidates=[];candidateAt=0;debounce.restart();
    }
    Timer {id:debounce;interval:180;onTriggered:{
        if(!board.composing || !board.lookup || !board.visible)return;
        var mine=board.generation;
        board.lookup(board.composing,function(reply){if(mine===board.generation&&board.visible&&reply.ok)board.candidates=reply.data.candidates;});
    }}
    function pick(index) {
        if(index>=candidates.length)return;
        value+=candidates[index].text;composing=composing.slice(candidates[index].consume);changed();
    }
    function key(text) {
        needsCandidate=false;
        if(text==="删除") {if(composing)composing=composing.slice(0,-1);else value=value.slice(0,-1);changed();return;}
        if(text==="大写"||text==="小写") {capitals=!capitals;return;}
        if(text==="123"||text==="ABC"||text==="#+=") {symbols=text!=="ABC";symbolPage=text==="#+="?1:0;return;}
        if(text==="空格") {if(composing&&candidates.length)pick(0);else {value+=composing||" ";composing="";changed();}return;}
        if(value.length+composing.length>=(secret?256:160))return;
        if(chinese&&!symbols&&/^[a-z]$/.test(text)) {if(composing.length<48)composing+=text;changed();}
        else {value+=text;}
    }
    function finish() {
        if(composing&&chinese){if(candidates.length)pick(0);else {needsCandidate=true;changed();return;}if(composing)return;}
        if(composing)value+=composing;composing="";generation++;visible=false;accepted(value);
    }
    Rectangle {x:6;y:4;width:535;height:38;radius:8;color:"#242630"
        BiliLabel {x:9;width:517;height:38;text:board.secret?Array(board.value.length+1).join("•"):board.value+(board.composing?"  ["+board.composing+"]":"");font.pixelSize:23;elide:Text.ElideLeft}
    }
    BiliButton {x:547;y:4;width:79;height:38;textSize:19;available:!board.secret;label:board.chinese?"英文":"中文";onClicked:{board.value+=board.composing;board.composing="";board.changed();if(board.chinese)board.nativeRequested(board.value);else board.chinese=true;}}
    BiliButton {x:632;y:4;width:78;height:38;textSize:19;label:"取消";onClicked:{board.generation++;board.visible=false;board.canceled();}}
    BiliButton {objectName:"biliKeyboardDone";x:716;y:4;width:78;height:38;textSize:19;label:"完成";selected:true;onClicked:board.finish()}
    Row {x:6;y:46;spacing:4
        Repeater {model:5
            BiliButton {objectName:"biliCandidate"+index;width:128;height:38;textSize:22;label:index+board.candidateAt<board.candidates.length?board.candidates[index+board.candidateAt].text:"";available:label!=="";onClicked:board.pick(index+board.candidateAt)}
        }
        BiliButton {width:62;height:38;label:"‹";available:board.candidateAt>0;onClicked:board.candidateAt=Math.max(0,board.candidateAt-5)}
        BiliButton {width:62;height:38;label:"›";available:board.candidateAt+5<board.candidates.length;onClicked:board.candidateAt+=5}
    }
    BiliLabel {x:12;y:46;width:642;height:38;visible:board.needsCandidate&&!board.candidates.length;text:"请选择候选字，或切换英文保留拼音";font.pixelSize:19;color:"#ff91b3"}
    Repeater {model:3
        Row {x:6;y:90+index*58;spacing:5
            property int rowIndex:index
            property var letters:board.symbols&&board.secret?(board.symbolPage===0?[
                ["1","2","3","4","5","6","7","8","9","0"],
                ["!","@","#","$","%","^","&","*","?","删除"],
                ["#+=","-","_","+","=",".",",",":","空格","ABC"]
            ]:[
                ["~","`","(",")","[","]","{","}","<",">"],
                ["/","\\","|","'","\"",";",":","?","!","删除"],
                ["123","-","_","+","=",".",",","@","空格","ABC"]
            ])[rowIndex]:board.symbols?[
                ["1","2","3","4","5","6","7","8","9","0"],
                [":","/",".","?","=","&","_","-","%","删除"],
                ["小写","@","#","+","(",")","'",",","空格","ABC"]
            ][rowIndex]:[
                ["q","w","e","r","t","y","u","i","o","p"],
                ["a","s","d","f","g","h","j","k","l","删除"],
                [board.capitals?"小写":"大写","z","x","c","v","b","n","m","空格","123"]
            ][rowIndex]
            Repeater {model:parent.letters
                BiliButton {objectName:"biliKey_"+modelData;width:74;height:53;textSize:modelData.length===1?26:20;label:board.capitals&&modelData.length===1?modelData.toUpperCase():modelData;onClicked:board.key(label)}
            }
        }
    }
}
