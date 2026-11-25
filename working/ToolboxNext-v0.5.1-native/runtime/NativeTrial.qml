import QtQuick 2.10
import QtQuick.Window 2.10
import QtTest 1.2
import "@@DEVICE_URL@@" as Toolbox

Rectangle {
    id: surface
    width:800;height:480;color:"#0f0f0f"
    property bool done:false
    property bool automated:@@AUTOMATED@@
    property int seconds:@@SECONDS@@
    property string captureDirectory:"@@CAPTURE_DIR@@"
    Toolbox.ExtensionPage {
        id:app;x:0;y:106;width:800;height:268
        endpoint:"@@ENDPOINT@@";bootstrapAllowed:true
        onExitRequested:surface.done=true
    }
    TestCase {
        id:trial;name:"P011NativeTrial";when:windowShown
        function capture(name) {
            // Qt 5.10 software Item.grabToImage renders a vertically inverted
            // offscreen layer. QtTest's window-backed item capture avoids that
            // path without rotating/mirroring the actual device UI.
            // Invalidate the complete item, not only the software backend's
            // damage rectangles, before reading its window-backed buffer.
            app.opacity=0.99;wait(120);app.opacity=1;wait(180);
            var picture=grabImage(app);
            compare(picture.width,800);compare(picture.height,268);
            picture.save(surface.captureDirectory+"/"+name+".png");
        }
        function page(name) {
            app.open(name);wait(450);
            var loader=findChild(app,"featureLoader");
            compare(loader.status,Loader.Ready);verify(loader.item!==null);
            return loader.item;
        }
        function test_session() {
            if(surface.Window.window) {
                surface.Window.window.flags=Qt.FramelessWindowHint;
                surface.Window.window.visibility=Window.FullScreen;
                surface.Window.window.requestActivate();
            }
            tryCompare(app,"connected",true,10000);
            wait(500);
            console.log("NATIVE_UI_READY content=800x268 offset=106 automated="+surface.automated);
            capture("home");
            if(surface.automated) {
                var files=page("Files");capture("files");
                files.openFile({path:"Text/native-ui-test.txt",kind:"text"});wait(350);
                verify(findChild(files,"textPreview").text.indexOf("中文 TXT")>=0,"Target text decoded");capture("text-preview");
                files.openFile({path:"Pictures/native-ui-test.png",kind:"image"});
                tryCompare(findChild(files,"imagePreview"),"status",Image.Ready,5000);capture("image-preview");
                var game=page("Games");capture("snake");
                var button=findChild(app,"gamePauseButton");
                var up=findChild(app,"gameUpButton");verify(up.width>=130&&up.height>=90,"Large side controls");
                mouseClick(button,button.width/2,button.height/2);wait(380);verify(!game.paused,"Start control");
                mouseClick(button,button.width/2,button.height/2);wait(300);verify(game.paused,"Pause control");
                game.start("2048");capture("2048");game.start("bricks");capture("bricks");
                mouseClick(button,button.width/2,button.height/2);
                var left=findChild(app,"brickLeftButton"),paddle=game.state.paddle;
                mousePress(left,left.width/2,left.height/2);wait(140);mouseRelease(left,left.width/2,left.height/2);
                verify(game.state.paddle<paddle,"Large side hold moves paddle");
                mouseClick(button,button.width/2,button.height/2);verify(game.paused);
                var dashboard=page("Dashboard");wait(2200);capture("dashboard");
                dashboard.mode="chart";wait(250);capture("dashboard-chart");
                app.open("");wait(250);capture("returned-home");
                console.log("NATIVE_UI_AUTOMATED_PASS pages=3 games=3 start_pause=PASS side_hold=PASS");
            } else {
                var deadline=Date.now()+surface.seconds*1000;
                while(!surface.done && Date.now()<deadline)wait(100);
            }
            // Leaving a page stops our media and saves its score before teardown.
            app.open("");wait(300);
            console.log("NATIVE_UI_SESSION_END");
        }
    }
}
