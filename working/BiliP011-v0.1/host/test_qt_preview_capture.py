import pathlib,tempfile,unittest
from qt_preview_capture import PreviewCapture


class FakePanel:
    def __init__(self,screen='catalog',playing=False):self.screen=screen;self.playing=playing
    def property(self,name):return getattr(self,name)


class FakeRoot:
    def __init__(self,panel):self.panel=panel
    def findChild(self,*args):return self.panel


class FakeView:
    def __init__(self,panel):self.panel=panel
    def rootObject(self):return FakeRoot(self.panel)
    def contentItem(self):raise AssertionError('Rejected request reached capture')


class PreviewCaptureTests(unittest.TestCase):
    def test_account_and_player_are_blocked_before_grab(self):
        with tempfile.TemporaryDirectory() as tmp:
            for panel in (FakePanel('login'),FakePanel(playing=True)):
                bridge=PreviewCapture(FakeView(panel),pathlib.Path(tmp),['home'])
                self.assertFalse(bridge.capture('home'))
                self.assertEqual(bridge.last_error,'CAPTURE_ACCOUNT_OR_PLAYER_BLOCKED')
                self.assertEqual(list(pathlib.Path(tmp).iterdir()),[])

    def test_fixed_names_and_missing_panel(self):
        bridge=PreviewCapture(FakeView(None),pathlib.Path('unused'),['home'])
        for name in ('../cookie','account','home.png','C:/private'):
            self.assertFalse(bridge.capture(name));self.assertEqual(bridge.last_error,'CAPTURE_NAME_REJECTED')
        self.assertFalse(bridge.capture('home'));self.assertEqual(bridge.last_error,'CAPTURE_PANEL_MISSING')

    def test_existing_file_never_overwritten_and_nested_capture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=pathlib.Path(tmp);file=directory/'home.png';file.write_bytes(b'original')
            bridge=PreviewCapture(FakeView(FakePanel()),directory,['home'])
            self.assertFalse(bridge.capture('home'));self.assertEqual(file.read_bytes(),b'original')
            self.assertEqual(bridge.last_error,'CAPTURE_PATH_REJECTED')
            bridge.busy=True;self.assertFalse(bridge.capture('home'));self.assertEqual(bridge.last_error,'CAPTURE_REENTRANT')


if __name__=='__main__':unittest.main()
