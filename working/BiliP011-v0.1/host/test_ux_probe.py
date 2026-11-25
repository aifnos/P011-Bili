"""PC fixtures for the explicit device-only state probe's evidence gates."""
import ast,json,os,pathlib,tempfile,types,unittest
from test_client import service,BASE
from library import Library
from ux_probe import handle,CHECKS

VIDEO=dict(kind='video',bvid='BV1Da411Y7U4',cid='1')

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.b=types.SimpleNamespace(root=str(self.root),ux_probe=True,automation=True,qa_claimed=True,qa_finished=False,
            protocol=2,hardware_required=True,library=Library(str(self.root/'library')),ux_rounds=[],
            play_generation=1,play_exit_code=0,player=types.SimpleNamespace(poll=lambda:0),play_item=None,ux_faults=1,ux_fault_pending=False)
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,n,position):
        self.b.play_generation=n
        audit=dict(starts=1,normal_exits=1,abnormal_exits=0,forced_kills=0,last_exit=0)
        files={'player-result.json':dict(generation=n,reason='back',loaded=True,muted=True,pulse=True,gl_errors={},hardware=audit),
               'watch-state.json':dict(generation=n,loaded=True,switch_pending=False,position=position),
               'media-state.json':dict(generation=n,hardware_verified=True,switch_failures=1 if n==1 else 0,switch_recoveries=1 if n==1 else 0),
               'performance-result.json':dict(submitted_frames=40)}
        for name,value in files.items():(self.root/name).write_text(json.dumps(value))
        self.b.library.record(VIDEO,position,180)
    def observe(self):return handle(self.b,{'phase':'observe'},service.hardware_cleanup_ok)
    def test_three_real_rounds_and_clear_required(self):
        for n,position in ((1,20),(2,21),(3,3.5)):
            self.fixture(n,position);self.assertEqual(self.observe()['position'],position)
        self.b.library.clear('history')
        self.assertTrue(handle(self.b,dict(phase='finish',passed=True,error='',stage=14,checks=list(CHECKS)),service.hardware_cleanup_ok)['passed'])
        report=json.loads((self.root/'ui-qa-result.json').read_text())
        self.assertEqual(len(report['rounds']),3);self.assertNotIn('BV1',json.dumps(report));self.assertTrue(report['history_clear_verified'])
    def test_isolation_and_mode_are_mandatory(self):
        self.fixture(1,20);self.b.ux_probe=False
        with self.assertRaises(ValueError):self.observe()
        self.b.ux_probe=True;self.b.library=Library(str(self.root/'not-isolated'))
        with self.assertRaises(ValueError):self.observe()
    def test_stale_evidence_cannot_pass(self):
        self.fixture(2,20)
        with self.assertRaises(ValueError):self.observe()
        self.fixture(1,20)
        value=json.loads((self.root/'watch-state.json').read_text());value['switch_pending']=True
        (self.root/'watch-state.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.observe()
    def test_restart_that_resumes_is_failure(self):
        for n,position in ((1,20),(2,21)):
            self.fixture(n,position);self.observe()
        self.fixture(3,23)
        with self.assertRaises(ValueError):self.observe()
    def test_missing_actual_recovery_is_failure(self):
        self.fixture(1,20)
        value=json.loads((self.root/'media-state.json').read_text());value['switch_recoveries']=0
        (self.root/'media-state.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.observe()
    def test_missing_rounds_are_not_overridden_by_ui_claims(self):
        result=handle(self.b,dict(phase='finish',passed=True,error='',stage=14,checks=list(CHECKS)),service.hardware_cleanup_ok)
        self.assertFalse(result['passed'])
    def test_build_gate_and_python35(self):
        from build_awake_trial import build
        for fields in ({'ux_probe':True},{'ux_probe':1},{'ux_probe':True,'client':True,'automated':True,'player_protocol':2,'ux_state':True,'toolbox':True}):
            with self.assertRaisesRegex(ValueError,'State probe requires'):build(BASE/'out/not-a-bundle',**fields)
        ast.parse((BASE/'client/ux_probe.py').read_text(),feature_version=(3,5))

if __name__=='__main__':unittest.main()
