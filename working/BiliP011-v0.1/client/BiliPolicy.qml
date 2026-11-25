// SPDX-License-Identifier: GPL-3.0-or-later
// Exact policy links used by the official passport website, read-only.
import QtQuick 2.7
import QtWebEngine 1.4
Item {
    signal unavailable()
    property string address: ""
    function open(which) {
        address=which==="privacy"?"https://www.bilibili.com/blackboard/privacy-pc.html":"https://www.bilibili.com/protocal/licence.html";
        view.url=address;
    }
    WebEngineProfile {id:privateProfile;offTheRecord:true}
    WebEngineView {
        id:view;anchors.fill:parent;profile:privateProfile;zoomFactor:0.85
        settings.localStorageEnabled:false
        settings.pluginsEnabled:false
        settings.javascriptCanOpenWindows:false
        settings.javascriptCanAccessClipboard:false
        onJavaScriptConsoleMessage: {}
        onCertificateError:error.rejectCertificate()
        onNewViewRequested: {}
        onNavigationRequested:if(request.isMainFrame&&request.url.toString()!==address&&request.url.toString()!=="about:blank")request.action=WebEngineView.IgnoreRequest
        onLoadingChanged:if(loadRequest.status===WebEngineView.LoadFailedStatus)unavailable()
    }
}
