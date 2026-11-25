"""Synthetic coordinate tests; never device-display acceptance."""
import unittest
from PIL import Image
from scanout_alignment import analyze,Observer

class ScanoutTests(unittest.TestCase):
    def image(self, y=106, height=268):
        image = Image.new('RGB', (480,800))
        image.paste((16,17,21), (y,0,y+height,800))
        return image
    def test_exact_center(self):
        self.assertTrue(analyze(self.image())['passed'])
    def test_reported_81px_offset_rejected(self):
        report=analyze(self.image(25))
        self.assertFalse(report['passed']);self.assertEqual(report['observed_y'],25)
    def test_visible_background_rejected(self):
        image=self.image();image.putpixel((400,100),(255,255,255))
        self.assertFalse(analyze(image)['passed'])
    def test_blank_rejected(self):
        self.assertFalse(analyze(Image.new('RGB',(480,800)))['passed'])
    def test_app_capture_not_screen_evidence(self):
        self.assertFalse(analyze(Image.new('RGB',(800,268)))['passed'])
    def test_enlarged_or_clipped_buffer_rejected(self):
        self.assertFalse(analyze(self.image(0,480))['passed'])
        self.assertFalse(analyze(self.image(107,267))['passed'])
    def test_sparse_band_not_a_complete_window(self):
        image=Image.new('RGB',(480,800));image.paste((255,255,255),(106,0,374,10))
        self.assertFalse(analyze(image)['passed'])
    def test_observer_requires_explicit_muted_automation(self):
        for meta in ({},{'ui_automation':False,'player_protocol':2},{'ui_automation':True,'player_protocol':1}):
            with self.assertRaises(ValueError):Observer(None,meta,None)
    def test_both_orientations_and_repeated_players_required(self):
        observer=Observer(None,{'ui_automation':True,'player_protocol':2},None)
        self.assertFalse(observer.result()['passed'])
        def sample(generation,portrait,stable=True,passed=True):
            return dict(state_stable=stable,passed=passed,context=dict(generation=generation,portrait=portrait))
        observer.samples=[sample(1,False),sample(1,True)]
        self.assertFalse(observer.result()['passed'])
        observer.samples.append(sample(2,True,False))
        self.assertFalse(observer.result()['passed'])
        observer.samples.append(sample(2,True))
        self.assertTrue(observer.result()['passed'])
        observer.samples.append(sample(2,False,True,False))
        self.assertFalse(observer.result()['passed'])

    def test_single_pose_does_not_claim_repeated_players(self):
        observer=Observer(None,dict(ui_automation=True,player_protocol=2,window_pose='portrait',benchmark_quality=32,benchmark_bvid='BV1Da411Y7U4'),None)
        observer.samples=[dict(state_stable=True,passed=True,context=dict(generation=1,portrait=True))]
        self.assertTrue(observer.result()['passed'])
        self.assertEqual(observer.result()['profile'],'portrait')
        self.assertEqual(observer.result()['generations_covered'],1)
        observer.samples[0]['context']['portrait']=False
        self.assertFalse(observer.result()['passed'])
    def test_single_pose_requires_fixed_source_gate(self):
        for extra in ({'window_pose':'portrait'},{'window_pose':'other','benchmark_quality':32,'benchmark_bvid':'BV1Da411Y7U4'}):
            with self.assertRaises(ValueError):Observer(None,dict(ui_automation=True,player_protocol=2,**extra),None)
    def test_fixed_pose_stops_reading_after_stable_capture(self):
        observer=Observer(None,dict(ui_automation=True,player_protocol=2,window_pose='landscape',benchmark_quality=32,benchmark_bvid='BV1Da411Y7U4'),None)
        observer.samples=[dict(state_stable=True,passed=True,context=dict(generation=1,portrait=False))]
        observer.poll()  # No ADB access is possible in this fixture.
        self.assertTrue(observer.result()['passed'])

if __name__=='__main__':unittest.main()
