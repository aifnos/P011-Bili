"""Host-only regression of the exact settings-resource boundary and adapters."""
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1]/'host/build_formal.py'
spec = importlib.util.spec_from_file_location('formal_build', MODULE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class FormalBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = builder.ORIGINAL.read_bytes()
        cls.before = builder.resource_map(cls.original)

    def test_only_feedback_record_and_all_other_399_resources_unchanged(self):
        candidate, result = builder.patch_z03(self.original, '0123456789abcdef01234567')
        after = builder.resource_map(candidate)
        self.assertEqual(len(candidate), len(self.original))
        changes = [key for key in self.before if self.before[key]['body'] != after[key]['body']]
        self.assertEqual(changes, [builder.RESOURCE])
        for key in self.before:
            if key != builder.RESOURCE:
                self.assertEqual(self.before[key], after[key], key)
        offset, length = result['record_offset'], result['slot_bytes']+4
        self.assertEqual(candidate[:offset], self.original[:offset])
        self.assertEqual(candidate[offset+length:], self.original[offset+length:])
        settings = after[builder.SET_MAIN]['body'].decode('utf-8')
        self.assertIn('name: qsTr("用户反馈")', settings)
        self.assertIn('icon: "qrc:/images/icon_user_report.png"', settings)
        self.assertIn('source: "qrc:/ZybQmlFiles/ZybSet/SetUserReport.qml"', settings)

    def test_wrong_firmware_refused_before_resource_parsing(self):
        with self.assertRaisesRegex(ValueError, 'pinned v2.4.0'):
            builder.patch_z03(self.original[:-1]+bytes([self.original[-1] ^ 1]), '0'*24)

    def test_path_injection_refused(self):
        for value in ('../bad', '0'*23, 'G'*24, '0'*24+'/evil'):
            with self.assertRaises(ValueError):
                builder.feedback_wrapper(value)

    def test_existing_payload_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='p011-formal-immutable-') as temporary:
            target = pathlib.Path(temporary)
            marker = target/'preserve.txt'
            marker.write_bytes(b'preserve existing output')
            with self.assertRaisesRegex(ValueError, 'new directory'):
                builder.build(target/'missing-native', target)
            self.assertEqual(marker.read_bytes(), b'preserve existing output')

    def test_legacy_native_has_no_formal_fallback(self):
        with tempfile.TemporaryDirectory(prefix='p011-formal-old-native-') as temporary:
            native = pathlib.Path(temporary)
            (native/'build-result.json').write_text(json.dumps(dict(
                formal_runtime=False, playback_limit_seconds=480,
                device_tested=False, source_files={'old.cpp': '0'*64})))
            with self.assertRaisesRegex(ValueError, 'formal-runtime/source provenance'):
                builder.source_inputs(native)

    def test_fixed_release_url_missing_asset_return_is_qrc(self):
        qml = builder.feedback_wrapper('a'*24).decode()
        self.assertIn('/bili-formal/releases/'+'a'*24+'/app/FeedbackEntry.qml', qml)
        self.assertIn('content.status === Loader.Error', qml)
        self.assertIn('onClicked:UILogic.backToSetPage()', qml)
        self.assertNotIn('y:106', qml)
        self.assertNotIn('rotation:', qml)

    def test_formal_bridge_keeps_freshness_and_destroy_release(self):
        qml = builder.patch_bridge((builder.BASE/'bridge/Bridge.qml').read_bytes()).decode()
        self.assertNotIn('ticks >= 1200', qml)
        self.assertNotIn('release(true)', qml)
        self.assertIn('Date.now() - lastFresh > 2500', qml)
        self.assertIn('Component.onDestruction:', qml)
        self.assertIn('release(false);', qml)

    def test_panel_can_exit_reenter_without_trial_stop_label(self):
        qml = builder.patch_panel((builder.BASE/'client/BiliPanel.qml').read_bytes()).decode()
        self.assertIn('/formal/heartbeat', qml)
        self.assertIn('if (formalExitSent) {', qml)
        self.assertIn('closeFormal(true);', qml)
        self.assertIn('xhr.readyState === XMLHttpRequest.DONE && notify && !disposed', qml)
        self.assertIn('interval:1500; onTriggered:panel.notifyFormalExit()', qml)
        self.assertIn('closeFormal();\n        console.log("P011_BILI UI_DESTROYED");', qml)
        self.assertIn('requests[i].xhr.abort()', qml)
        self.assertNotIn('正在退出并恢复原厂界面', qml)

    def test_source_drift_does_not_silently_patch(self):
        with self.assertRaisesRegex(ValueError, 'exit source changed'):
            builder.patch_panel(b'import QtQuick 2.0\nItem {}')
        with self.assertRaisesRegex(ValueError, 'bridge source changed'):
            builder.patch_bridge(b'import QtQuick 2.0\nItem {}')

    def test_adapted_real_qml_compiles_in_host_qt(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ.setdefault('QT_QUICK_BACKEND', 'software')
        try:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QGuiApplication
            from PyQt5.QtQml import QQmlComponent, QQmlEngine
        except ImportError:
            self.skipTest('PyQt5 host runtime unavailable; no device claim')
        app = QGuiApplication.instance() or QGuiApplication([])
        engine = QQmlEngine()
        with tempfile.TemporaryDirectory(prefix='p011-formal-qml-') as temporary:
            directory = pathlib.Path(temporary)
            for source in (builder.BASE/'client').iterdir():
                if source.suffix in ('.qml', '.js'):
                    content = source.read_bytes()
                    if source.name == 'BiliPanel.qml':
                        content = builder.patch_panel(content)
                    (directory/source.name).write_bytes(content)
            (directory/'UILogics.js').write_text('function backToSetPage() {}\n', encoding='utf-8')
            entry = (builder.FORMAL/'runtime/FeedbackEntry.qml').read_bytes().replace(
                b'qrc:/ZybQmlFiles/Funcs/UILogics.js', b'UILogics.js')
            wrapper = builder.feedback_wrapper('a'*24).replace(
                b'qrc:/ZybQmlFiles/Funcs/UILogics.js', b'UILogics.js')
            (directory/'FeedbackEntry.qml').write_bytes(entry)
            (directory/'Bridge.qml').write_bytes(builder.patch_bridge(
                (builder.BASE/'bridge/Bridge.qml').read_bytes()))
            (directory/'StockFeedback.qml').write_bytes(wrapper)
            for name in ('BiliPanel.qml', 'Bridge.qml', 'FeedbackEntry.qml', 'StockFeedback.qml'):
                component = QQmlComponent(engine, QUrl.fromLocalFile(str(directory/name)))
                while component.isLoading():
                    app.processEvents()
                self.assertTrue(component.isReady(), name+': '+
                                '\n'.join(error.toString() for error in component.errors()))


if __name__ == '__main__':
    unittest.main()
