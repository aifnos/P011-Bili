// Private, finite bridge loaded only by the copied v2.4.0 UI.
// No input simulation, settings writes, arbitrary commands, or radio methods.
import QtQuick 2.0

Item {
    id: bridge
    property string sessionId: "@SESSION@"
    property string stateUrl: "file://@REMOTE@/lease.json"
    property bool held: false
    property bool disposed: false
    property var request: null
    property double lastSequence: -2
    property double lastFresh: 0
    property double requestAt: 0
    property int ticks: 0

    function release(force) {
        if (held || force) {
            engineSocket.sendEnableSysAutoOffScreen(true);
            held = false;
            console.log("P011_AWAKE RELEASE");
        }
    }
    function accept(text) {
        var value;
        try { value = JSON.parse(text); } catch (e) { release(false); return; }
        if (!value || value.session !== sessionId || typeof value.seq !== "number" ||
                typeof value.active !== "boolean") { release(false); return; }
        if (!value.active) { release(false); return; }
        if (value.seq !== lastSequence) {
            lastSequence = value.seq;
            lastFresh = Date.now();
            if (!held) {
                engineSocket.sendEnableSysAutoOffScreen(false);
                held = true;
                console.log("P011_AWAKE ACQUIRE");
            }
        }
    }
    function poll() {
        ticks++;
        // Independent 10 minute cap, even if the player leaves a fresh file.
        if (ticks >= 1200) { release(false); heartbeat.stop(); return; }
        if (held && (Date.now() - lastFresh > 2500 || Date.now() < lastFresh)) release(false);
        if (request) {
            if (Date.now() - requestAt > 1500) {
                var old = request; request = null;
                old.onreadystatechange = function() {}; old.abort(); release(false);
            }
            return;
        }
        // Initial repeats cover the vendor socket connecting asynchronously.
        if (ticks <= 12 && ticks % 2 === 0) release(true);
        var xhr = new XMLHttpRequest(); request = xhr; requestAt = Date.now();
        xhr.onreadystatechange = function() {
            if (disposed || xhr.readyState !== XMLHttpRequest.DONE) return;
            if (request !== xhr) return;
            request = null;
            if (xhr.status === 0 || xhr.status === 200) accept(xhr.responseText);
            else release(false);
        };
        // Qt's local-file backend reads the atomic file on each new request.
        xhr.open("GET", stateUrl); xhr.send();
    }
    Timer { id: heartbeat; interval: 500; repeat: true; running: true; onTriggered: bridge.poll() }
    Component.onCompleted: { release(true); console.log("P011_AWAKE READY"); }
    Component.onDestruction: {
        disposed = true; heartbeat.stop();
        if (request) { request.onreadystatechange = function() {}; request.abort(); request = null; }
        release(false);
    }
}
