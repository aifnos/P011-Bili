"""Check ZIP privacy without any real credentials or device access."""
import json,pathlib,tempfile,unittest,zipfile
from client_results import archive_client,CAPTURES,capture_rect
from review_gallery import LABELS

class Results(unittest.TestCase):
    def test_legacy_capture_keeps_original_crop(self):
        self.assertEqual(capture_rect('player-paused',800,480),[0,106,800,268])
    def test_strip_capture_needs_matching_runtime_evidence(self):
        surface={'content_only':True,'buffer_width':800,'buffer_height':268,'panel_origin_y':106,'configure_bound_ms':500}
        self.assertEqual(capture_rect('player-paused',800,268,surface),[0,0,800,268])
        self.assertEqual(capture_rect('01-recommendations',800,480,surface),[0,106,800,268])
        for name,w,h,s in [('player-paused',800,268,None),('player-paused',800,480,surface),
                           ('01-recommendations',800,268,surface),('player-paused',268,800,surface),
                           ('player-paused',800,268,dict(surface,configure_bound_ms=0))]:
            with self.assertRaises(ValueError):capture_rect(name,w,h,s)
    def test_every_safe_capture_has_gallery_label(self):
        self.assertTrue(set(CAPTURES).issubset(LABELS))
    def test_raw_factory_and_account_never_archived(self):
        with tempfile.TemporaryDirectory(prefix='p011-safe-results-') as temp:
            root=pathlib.Path(temp)/'run';(root/'device').mkdir(parents=True)
            (root/'device/candidate.stderr.raw').write_text('token=FAKE_SECRET\nP011_BILI UI_READY\nP011_BILI PAGE catalog recommend\nP011_BILI LIST recommend 12\nP011_BILI UI_READY FAKE_SECRET\n',encoding='utf-8')
            (root/'device/Z03.awake-candidate').write_bytes(b'FAKE_BINARY_SECRET')
            (root/'device/cookies.txt').write_text('FAKE_SECRET')
            (root/'device/qr.png').write_bytes(b'FAKE_QR')
            (root/'result.json').write_text('{"passed":false}')
            target=archive_client(root)
            with zipfile.ZipFile(target) as z:
                self.assertEqual(set(z.namelist()),{'result.json','ui-events.safe.txt','PRIVACY.txt'})
                self.assertFalse(any(b'FAKE_SECRET' in z.read(n) for n in z.namelist()))
                self.assertIn(b'P011_BILI LIST recommend 12',z.read('ui-events.safe.txt'))
            self.assertTrue((root/'device/candidate.stderr.raw').exists(),'Raw evidence must be retained locally')
    def test_only_stable_passed_scanouts_shared(self):
        with tempfile.TemporaryDirectory(prefix='p011-screen-results-') as temp:
            root=pathlib.Path(temp)/'run';(root/'scanout').mkdir(parents=True)
            samples=[dict(state_stable=True,passed=True),dict(state_stable=False,passed=True),dict(state_stable=True,passed=False)]
            (root/'result.json').write_text(json.dumps({'screen_alignment':{'samples':samples}}))
            for i in range(3):
                for ext in ('png','json'):(root/'scanout'/('%02d.%s'%(i,ext))).write_bytes(b'fixture')
            with zipfile.ZipFile(archive_client(root)) as z:
                self.assertIn('scanout/00.png',z.namelist())
                self.assertIn('scanout/00.json',z.namelist())
                self.assertNotIn('scanout/01.png',z.namelist())
                self.assertNotIn('scanout/02.png',z.namelist())

if __name__=='__main__':unittest.main(verbosity=2)
