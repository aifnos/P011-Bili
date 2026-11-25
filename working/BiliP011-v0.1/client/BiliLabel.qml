import QtQuick 2.0
Text {
    color: "#edf5fa"
    font.family: typeof nativeFontFamily !== "undefined" ? nativeFontFamily : "Source Han Sans SC"
    font.pixelSize: 20
    textFormat: Text.PlainText
    renderType: Text.NativeRendering
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
}
