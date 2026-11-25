"""PC-only CAPTCHA layout QA using synthetic geometry, never a real challenge.

Loads the actual BiliCaptcha.qml with two ephemeral inspection methods. The
source file is not modified, begin()/proof are never invoked, and no device or
login endpoint is contacted. This is Qt 5.15 host evidence, not P011 acceptance.
Optional WebEngine dependencies may live in ../.host-qa-webengine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "client" / "BiliCaptcha.qml"
BUTTON_NAMES = ("captchaFit", "captchaZoom", "captchaUp", "captchaDown")
CORNER_IDS = ("qa-tl", "qa-tr", "qa-bl", "qa-br")


def fixture_html(height: int, *, fixed: bool = True) -> str:
    """Deliberately oversized, non-account fixture with four click targets."""
    if not isinstance(height, int) or not 350 <= height <= 600:
        raise ValueError("Synthetic height must be an integer from 350 to 600")
    position = "fixed" if fixed else "absolute"
    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{margin:0;background:#e8eef3;font:16px sans-serif;overflow:auto}
body{min-height:%dpx}
#qa-panel{position:%s;top:8px;left:50%%;margin-left:-170px;width:340px;
height:%dpx;box-sizing:border-box;border:3px solid #14293b;border-radius:8px;
background:linear-gradient(135deg,#abdceb,#a4bdf1 48%%,#f7c8d8);color:#14293b}
.qa-corner{position:absolute;width:64px;height:44px;border:0;border-radius:4px;
background:#164d7a;color:white;font-weight:bold}
#qa-tl{top:8px;left:8px}#qa-tr{top:8px;right:8px}
#qa-bl{bottom:8px;left:8px}#qa-br{bottom:8px;right:8px}
#qa-label{position:absolute;top:70px;left:15px;right:15px;text-align:center;
font-weight:bold;line-height:2}
#qa-position{position:absolute;top:46%%;left:0;right:0;text-align:center}
</style></head><body>
<div class="geetest_popup_wrap" style="position:fixed;inset:0;pointer-events:none"></div>
<div id="qa-panel" class="geetest_panel_box">
<div id="qa-label">SYNTHETIC GEOMETRY ONLY<br>NOT A CAPTCHA<br>340 x %d CSS px</div>
<div id="qa-position">NO ACCOUNT / NO PROOF</div>
<button id="qa-tl" class="qa-corner">TOP L</button>
<button id="qa-tr" class="qa-corner">TOP R</button>
<button id="qa-bl" class="qa-corner">BOTTOM L</button>
<button id="qa-br" class="qa-corner">BOTTOM R</button></div>
<script>window.qaClicks=[];document.querySelectorAll('.qa-corner').forEach(function(b){
b.addEventListener('click',function(){window.qaClicks.push(this.id);this.style.background='#00834b';});
});</script></body></html>""" % (height + 16, position, height, height)


def instrument_component(source: str) -> str:
    """Add host-only hooks in memory, retaining the real component geometry."""
    if "id: view" not in source and "id:view" not in source:
        raise ValueError("Expected actual WebEngineView id is missing")
    end = source.rfind("}")
    if end < 0:
        raise ValueError("Missing QML root closing brace")
    methods = """
    // Added in memory by host/captcha_layout_qa.py, never shipped.
    function qaLoadSynthetic(html) {
        // Base URL only, identical to production; HTML has no network URLs.
        view.loadHtml(html, "https://passport.bilibili.com/");
    }
    function qaEvaluateSynthetic(script) {
        view.runJavaScript(script, function(value) {
            qaBridge.receive(JSON.stringify(value));
        });
    }
    function qaMapSynthetic(x, y) {
        var p = view.mapToItem(null, x, y);
        return {x:p.x, y:p.y};
    }
"""
    return source[:end] + methods + source[end:]


def rect_inside(rect: dict, bounds: dict, tolerance: float = 1.5) -> bool:
    return (rect["left"] >= bounds["left"] - tolerance
            and rect["top"] >= bounds["top"] - tolerance
            and rect["right"] <= bounds["right"] + tolerance
            and rect["bottom"] <= bounds["bottom"] + tolerance)


def click_point(rect: dict, zoom: float, origin: tuple[float, float]) -> tuple[int, int]:
    """CSS client rectangles -> QQuick scene pixels for a WebEngine viewport."""
    if not 0 < zoom <= 5:
        raise ValueError("Invalid zoom factor")
    return (round(origin[0] + (rect["left"] + rect["right"]) * zoom / 2),
            round(origin[1] + (rect["top"] + rect["bottom"]) * zoom / 2))


def _prepare_dependencies(path: Path | None) -> None:
    candidate = path or ROOT / ".host-qa-webengine"
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--disable-gpu --host-resolver-rules=MAP * 0.0.0.0, EXCLUDE localhost")


def run(source_path: Path, output: Path, dependency_path: Path | None) -> dict:
    _prepare_dependencies(dependency_path)
    from PyQt5.QtCore import QObject, QUrl, Qt, QMetaObject, Q_ARG, QPoint, QPointF, pyqtSlot, QT_VERSION_STR
    from PyQt5.QtGui import QGuiApplication
    from PyQt5.QtQml import QQmlComponent, QQmlEngine
    from PyQt5.QtQuick import QQuickItem, QQuickView
    from PyQt5.QtTest import QTest, QSignalSpy
    from PyQt5.QtWebEngine import QtWebEngine

    QGuiApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QtWebEngine.initialize()
    app = QGuiApplication.instance() or QGuiApplication(["captcha-layout-host-qa"])
    output.mkdir(parents=True, exist_ok=False)
    source = source_path.read_text(encoding="utf-8-sig")
    engine = QQmlEngine()

    class Bridge(QObject):
        received = False
        value = None

        @pyqtSlot(str)
        def receive(self, value):
            self.value = json.loads(value) if value else None
            self.received = True


    bridge = Bridge()
    engine.rootContext().setContextProperty("qaBridge", bridge)
    background_component = QQmlComponent(engine)
    background_component.setData(b'''import QtQuick 2.7
Rectangle {width:800;height:268;color:"#101820"
 Text{x:14;y:9;color:"#f0f6fa";font.pixelSize:18;text:"PC SYNTHETIC LAYOUT QA - NOT A CAPTCHA"}
 Text{x:14;y:37;color:"#b7d3e3";font.pixelSize:13;text:"800 x 268 small-screen fixture; no account, challenge or device"}
}''', QUrl())
    background = background_component.create()
    if background is None:
        raise RuntimeError("Background QML: " + str(background_component.errors()))
    view = QQuickView(engine, None)
    view.setContent(QUrl(), background_component, background)
    view.setTitle("P011 CAPTCHA layout - HOST SYNTHETIC ONLY")
    view.setGeometry(20, 20, 800, 268)
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    component = QQmlComponent(engine)
    component.setData(instrument_component(source).encode("utf-8"), QUrl.fromLocalFile(str(source_path)))
    captcha = component.create()
    if captcha is None:
        raise RuntimeError("Actual CAPTCHA QML: " + str(component.errors()))
    captcha.setParentItem(background)
    captcha.setWidth(772)
    captcha.setHeight(202)
    captcha.setX(14)
    captcha.setY(60)
    view.show()
    QTest.qWait(600)
    completed_signals = QSignalSpy(captcha.completed)
    web = captcha.findChild(QQuickItem, "captchaWebView")
    if web is None:
        raise RuntimeError("Actual component must expose captchaWebView objectName")

    def invoke(name, value):
        QMetaObject.invokeMethod(captcha, name, Qt.DirectConnection, Q_ARG("QVariant", value))

    def evaluate(script, timeout=5000):
        bridge.received = False
        bridge.value = None
        invoke("qaEvaluateSynthetic", script)
        end = time.monotonic() + timeout / 1000
        while not bridge.received and time.monotonic() < end:
            QTest.qWait(20)
        if not bridge.received:
            raise RuntimeError("Synthetic JavaScript callback timeout")
        return bridge.value

    def tap(item):
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        position = QPoint(round(point.x()), round(point.y()))
        spy = QSignalSpy(item.clicked)
        QTest.mouseMove(view, position)
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, position)
        QTest.qWait(70)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, position)
        QTest.qWait(500)
        view.requestUpdate()
        view.grabWindow()
        QTest.qWait(250)
        if len(spy) != 1:
            viewport = captcha.findChild(QQuickItem, "captchaViewport")
            raise AssertionError("Actual toolbar input failed: %s at %s available=%s zoom=%s canvas=%s height=%s contentY=%s" %
                                 (item.objectName(), position, item.property("available"), web.property("zoomFactor"),
                                  captcha.property("canvasHeight"), web.height(), viewport.property("contentY")))

    def grab(name):
        view.requestUpdate()
        QTest.qWait(200)
        picture = view.grabWindow()
        if picture.isNull():
            request = background.grabToImage()
            spy = QSignalSpy(request.ready)
            if request.image().isNull():
                spy.wait(2000)
            picture = request.image()
        if picture.isNull() or picture.width() != 800 or picture.height() != 268:
            raise RuntimeError("Synthetic screenshot missing or incorrectly sized")
        path = output / name
        if not picture.save(str(path), "PNG"):
            raise RuntimeError("Cannot save synthetic screenshot")
        return str(path)

    report = {"host_only": True, "synthetic_geometry_only": True,
              "device_accessed": False, "real_challenge_loaded": False,
              "proof_called": False, "qt_version": QT_VERSION_STR,
              "source": str(source_path), "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
              "screen": {"width": 800, "height": 268}, "container": {"x": 14, "y": 60, "width": 772, "height": 202},
              "controls": [], "cases": []}
    buttons = {}
    for name in BUTTON_NAMES:
        button = captcha.findChild(QQuickItem, name)
        if button is None:
            raise RuntimeError("Missing actual component control: " + name)
        point = button.mapToScene(QPointF(0, 0))
        geometry = {"left": point.x(), "top": point.y(),
                    "right": point.x() + button.width(), "bottom": point.y() + button.height()}
        if not rect_inside(geometry, {"left": 14, "top": 60, "right": 786, "bottom": 262}):
            raise AssertionError("Actual component toolbar outside visible area: " + name)
        report["controls"].append({"name": name, "geometry": geometry})
        buttons[name] = button
    bounds = {"left": 0, "top": 0, "right": float(web.property("width")),
              "bottom": float(web.property("height"))}

    for height, fixed in ((350, False), (500, True), (600, True)):
        invoke("qaLoadSynthetic", fixture_html(height, fixed=fixed))
        for _ in range(80):
            if evaluate("!!document.getElementById('qa-br')"):
                break
            QTest.qWait(50)
        else:
            raise AssertionError("Synthetic fixture did not load")
        QTest.qWait(1200)
        tap(buttons["captchaFit"])
        QTest.qWait(700)
        geometry = evaluate("JSON.parse(JSON.stringify(Array.from(document.querySelectorAll('.qa-corner')).map(function(b){var r=b.getBoundingClientRect();return {id:b.id,left:r.left,right:r.right,top:r.top,bottom:r.bottom};})))")
        zoom = float(web.property("zoomFactor"))
        origin_point = web.mapToScene(QPointF(0, 0))
        origin = (origin_point.x(), origin_point.y())
        clicked = []
        for rect in geometry:
            scaled = {key: rect[key] * zoom for key in ("left", "right", "top", "bottom")}
            if not rect_inside(scaled, bounds):
                raise AssertionError("Synthetic corner clipped after Fit: " + json.dumps(rect))
            x, y = click_point(rect, zoom, origin)
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
            QTest.qWait(100)
            clicked.append(rect["id"])
        observed = evaluate("window.qaClicks")
        if observed != clicked:
            raise AssertionError("Synthetic click mapping mismatch: " + repr(observed))
        screenshot = grab("synthetic-%d-%s-fit.png" % (height, "fixed" if fixed else "flow"))
        before_zoom = zoom
        tap(buttons["captchaZoom"])
        after_zoom = float(web.property("zoomFactor"))
        grab("synthetic-%d-%s-after-zoom.png" % (height, "fixed" if fixed else "flow"))
        # Components may zoom the DOM container rather than WebEngine itself;
        # retain DOM metrics as well, and compare either representation.
        after_geometry = evaluate("(function(){var r=document.getElementById('qa-panel').getBoundingClientRect();return {top:r.top,bottom:r.bottom,width:r.width,height:r.height};})()")
        before_pan_origin = web.mapToScene(QPointF(0, 0))
        tap(buttons["captchaDown"])
        down_geometry = evaluate("(function(){var r=document.getElementById('qa-panel').getBoundingClientRect();return {top:r.top,bottom:r.bottom};})()")
        down_origin = web.mapToScene(QPointF(0, 0))
        bottom_rect = evaluate("(function(){var r=document.getElementById('qa-br').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})()")
        bottom_point = click_point(bottom_rect, after_zoom, (down_origin.x(), down_origin.y()))
        if not (14 <= bottom_point[0] < 678 and 60 <= bottom_point[1] < 262):
            raise AssertionError("Lower synthetic target is not reachable after native Down")
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(*bottom_point))
        QTest.qWait(100)
        tap(buttons["captchaUp"])
        up_geometry = evaluate("(function(){var r=document.getElementById('qa-panel').getBoundingClientRect();return {top:r.top,bottom:r.bottom};})()")
        up_origin = web.mapToScene(QPointF(0, 0))
        if not after_zoom > before_zoom:
            raise AssertionError("Actual Zoom button did not enlarge synthetic geometry: %s -> %s" % (before_zoom, after_zoom))
        if not down_origin.y() < before_pan_origin.y():
            raise AssertionError("Actual Down button did not reveal lower synthetic geometry")
        if not up_origin.y() > down_origin.y():
            raise AssertionError("Actual Up button did not reveal upper synthetic geometry")
        top_rect = evaluate("(function(){var r=document.getElementById('qa-tr').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})()")
        top_point = click_point(top_rect, after_zoom, (up_origin.x(), up_origin.y()))
        if not (14 <= top_point[0] < 678 and 60 <= top_point[1] < 262):
            raise AssertionError("Upper synthetic target is not reachable after native Up")
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(*top_point))
        QTest.qWait(100)
        pan_clicks = evaluate("window.qaClicks")
        if pan_clicks != clicked + ["qa-br", "qa-tr"]:
            raise AssertionError("Zoomed/panned synthetic input mapping mismatch: " + repr(pan_clicks))
        detail_screenshot = grab("synthetic-%d-%s-detail.png" % (height, "fixed" if fixed else "flow"))
        report["cases"].append({"height": height, "fixed": fixed, "fit_zoom": before_zoom,
                                "zoomed_zoom": after_zoom, "corner_rects_css": geometry,
                                "clicks": observed, "after_zoom": after_geometry,
                                "after_down": down_geometry, "after_up": up_geometry,
                                "pan_origin_y": {"before": before_pan_origin.y(), "down": down_origin.y(), "up": up_origin.y()},
                                "zoomed_panned_clicks": pan_clicks,
                                "fit_image": screenshot, "detail_image": detail_screenshot})
    # Deferred third-party panel growth, active pointer protection, and manual
    # zoom persistence. These are DOM geometry changes, not CAPTCHA actions.
    invoke("qaLoadSynthetic", fixture_html(350, fixed=True))
    QTest.qWait(1000)
    tap(buttons["captchaFit"])
    QTest.qWait(700)
    initial_canvas = float(captcha.property("canvasHeight"))
    evaluate("document.getElementById('qa-panel').style.height='500px';true")
    QTest.qWait(1300)
    grown_canvas = float(captcha.property("canvasHeight"))
    if not grown_canvas > initial_canvas:
        raise AssertionError("Late fixed panel growth was not automatically fitted")
    protected_zoom = float(web.property("zoomFactor"))
    evaluate("window._p011TouchActive=true;document.getElementById('qa-panel').style.height='600px';true")
    QTest.qWait(1200)
    if float(captcha.property("canvasHeight")) != grown_canvas or abs(float(web.property("zoomFactor")) - protected_zoom) > 0.001:
        raise AssertionError("Automatic fit moved synthetic geometry during active pointer input")
    evaluate("window._p011TouchActive=false;window._p011TouchUntil=Date.now()+1000;true")
    QTest.qWait(550)
    if float(captcha.property("canvasHeight")) != grown_canvas:
        raise AssertionError("Automatic fit ignored synthetic post-input grace period")
    QTest.qWait(1100)
    released_canvas = float(captcha.property("canvasHeight"))
    if not released_canvas > grown_canvas:
        raise AssertionError("Automatic fit did not resume after synthetic pointer grace expired")
    tap(buttons["captchaZoom"])
    manual_zoom = float(web.property("zoomFactor"))
    evaluate("document.getElementById('qa-panel').style.height='450px';true")
    QTest.qWait(1300)
    if float(captcha.property("canvasHeight")) != released_canvas or abs(float(web.property("zoomFactor")) - manual_zoom) > 0.001:
        raise AssertionError("Automatic fit overrode explicit manual enlargement")
    tap(buttons["captchaFit"])
    QTest.qWait(700)
    final_canvas = float(captcha.property("canvasHeight"))
    if not final_canvas < released_canvas or not captcha.property("autoFit"):
        raise AssertionError("Fit button did not resume automatic geometry sizing")
    report["dynamic_geometry"] = {"initial_canvas": initial_canvas, "late_growth_canvas": grown_canvas,
                                  "active_input_preserved": True, "grace_period_preserved": True,
                                  "released_canvas": released_canvas, "manual_zoom_preserved": True,
                                  "manual_zoom": manual_zoom, "fit_resumed_canvas": final_canvas,
                                  "image": grab("synthetic-dynamic-geometry.png")}
    if len(completed_signals) or captcha.property("sent"):
        raise AssertionError("Synthetic layout QA unexpectedly emitted a completed proof")
    report["zoom_runtime_note"] = {
        "host_qt": QT_VERSION_STR,
        "known_host_setter_difference": "Qt 5.15.2 may defer the first zoom assignment; the production component performs bounded confirmation and retry.",
        "source": "https://raw.githubusercontent.com/qt/qtwebengine/v5.15.2/src/webengine/api/qquickwebengineview.cpp#L1056-L1064",
        "device_not_verified_by_this_script": True}
    report["passed"] = True
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    view.close()
    app.processEvents()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dependency-path", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "formal" / "evidence" / ("captcha-host-layout-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        report = run(args.source.resolve(), output.resolve(), args.dependency_path)
    except Exception as error:
        if output.is_dir():
            failure = {"passed": False, "host_only": True, "synthetic_geometry_only": True,
                       "device_accessed": False, "real_challenge_loaded": False,
                       "proof_called": False, "error_type": type(error).__name__, "error": str(error),
                       "source": str(args.source.resolve()),
                       "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest()}
            (output / "failure.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    print(json.dumps({"passed": report["passed"], "host_only": True, "output": str(output),
                      "cases": len(report["cases"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
