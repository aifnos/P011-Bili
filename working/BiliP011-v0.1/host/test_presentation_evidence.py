import copy
import unittest
from presentation_evidence import analyze

def fixture():
    rows=[]
    # 600 commits in ten seconds, with every second commit a UI redraw.
    for i in range(600):
        now=1000000000+i*16666667
        video=i//2+1
        rows.append([1,i+1,video,video,6000000+(video-1)*33333,now-1000000,now,16666667,i+1,7,1])
    return dict(schema=1,protocol_version=1,clock_id=1,commits=600,video_frames=300,
                capacity_skips=0,invalid_timestamps=0,clock_errors=0,global_removed=False,
                pending_limit=256,row_limit=32768,physical_optical_measurement=False,rows=rows)

class PresentationTests(unittest.TestCase):
    def test_redraw_not_video_fps(self):
        result=analyze(fixture())
        self.assertTrue(result['evidence_complete'])
        self.assertAlmostEqual(result['compositor_presented_video_fps'],30,places=4)
        self.assertAlmostEqual(result['compositor_refresh_hz'],60,places=4)
        self.assertEqual(result['redraw_presentations'],300)
        self.assertTrue(result['display_ceiling_established'])
        self.assertFalse(result['physical_optical_measurement'])

    def test_software_feedback_not_hardware_proof(self):
        value=fixture()
        for row in value['rows']:row[9]=0
        result=analyze(value)
        self.assertTrue(result['evidence_complete'])
        self.assertFalse(result['display_ceiling_established'])

    def test_no_sequence_not_refresh_proof(self):
        value=fixture()
        for row in value['rows']:row[8]=0
        result=analyze(value)
        self.assertTrue(result['evidence_complete'])
        self.assertIsNone(result['compositor_refresh_hz'])
        self.assertFalse(result['display_ceiling_established'])

    def test_discarded_not_presented(self):
        value=fixture()
        for row in value['rows'][1::2]:row[0]=2;row[6:10]=[0,0,0,0]
        result=analyze(value)
        self.assertTrue(result['evidence_complete'])
        self.assertEqual(result['discarded_commits'],300)
        self.assertEqual(result['redraw_presentations'],0)

    def test_invalid_and_missing_records_rejected(self):
        for key,bad in [('schema',2),('clock_id',0),('capacity_skips',1),('clock_errors',True),('commits',601),('global_removed',True)]:
            value=fixture();value[key]=bad
            self.assertFalse(analyze(value)['evidence_complete'],key)
        for row in ([True]*11,[1]*10):
            value=fixture();value['rows'][0]=row
            self.assertFalse(analyze(value)['evidence_complete'])
        value=fixture();value['rows'][1][1]=1
        self.assertFalse(analyze(value)['evidence_complete'])
        value=fixture();value['rows'][1][4]+=1
        self.assertFalse(analyze(value)['evidence_complete'])

    def test_pause_cannot_join_two_short_windows(self):
        value=fixture();value['rows'][300][10]=0
        self.assertFalse(analyze(value)['evidence_complete'])

    def test_no_private_or_extra_payload(self):
        value=fixture();value['url']='private'
        self.assertFalse(analyze(value)['evidence_complete'])
        value=fixture();value['rows'][0][4]='private'
        self.assertFalse(analyze(value)['evidence_complete'])

if __name__=='__main__':unittest.main()
