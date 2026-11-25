"""PC-only evidence gate tests. No ADB, imports or actual pen processes."""
import ast,contextlib,io,json,pathlib,sys,time,types,unittest
from unittest.mock import patch
from client_soak import evaluate,PROBE
from build_awake_trial import build

class Soak(unittest.TestCase):
    def rows(self):
        return [dict(time=1000+t,player=dict(loaded=True,active=True,paused=False,muted=True,pulse_observed=True,
                     position=5+t,pause_actions=0,seek_actions=0,capture_count=0),
                     idle=dict(seconds=60,enabled=0,brightness=42,actual_brightness=42),
                     lease=dict(active=True,seq=t+1),player_age=.5,lease_age=.5) for t in range(0,131,5)]
    def test_continuous_two_idle_periods(self):
        r=evaluate(self.rows());self.assertTrue(r['passed']);self.assertEqual(r['continuous_seconds'],130)
    def test_33_seconds_not_enough(self):self.assertFalse(evaluate(self.rows()[:7])['passed'])
    def test_missing_samples_not_pass(self):self.assertFalse(evaluate([])['passed'])
    def test_screen_off_splits_run(self):
        rows=self.rows();rows[13]['idle']['actual_brightness']=0;self.assertFalse(evaluate(rows)['passed'])
    def test_enabled_auto_off_splits_run(self):
        rows=self.rows();rows[13]['idle']['enabled']=1;self.assertFalse(evaluate(rows)['passed'])
    def test_stale_or_frozen_evidence_rejected(self):
        for target,key,value in [('player','position',20),('lease','seq',1),(None,'player_age',3),(None,'lease_age',3)]:
            rows=self.rows()
            for row in rows:(row[target] if target else row).__setitem__(key,value)
            self.assertFalse(evaluate(rows)['passed'])
    def test_unknown_or_unmuted_audio_rejected(self):
        for key in ('muted','pulse_observed'):
            rows=self.rows()
            for row in rows:row['player'][key]=False
            self.assertFalse(evaluate(rows)['passed'])
    def test_missing_or_nonfinite_values_rejected(self):
        for value in (None,True,float('nan'),float('inf')):
            rows=self.rows();rows[13]['time']=value;self.assertFalse(evaluate(rows)['passed'])
    def test_sample_gap_breaks_continuity(self):
        rows=self.rows();del rows[12:15];self.assertFalse(evaluate(rows)['passed'])
    def test_seeks_cannot_fake_continuity(self):
        rows=self.rows();rows[13]['player']['position']+=20;self.assertFalse(evaluate(rows)['passed'])
    def test_target_python35_and_readonly_probe(self):
        import ast
        ast.parse(PROBE,feature_version=(3,5))
        for forbidden in ('os.kill','os.chmod','open(','cookies','account','sendEnable','subprocess','write('):self.assertNotIn(forbidden,PROBE)
    def test_probe_uses_bundled_parser_not_output_only_encoder(self):
        trial=types.SimpleNamespace(json=types.SimpleNamespace(dumps=json.dumps),
                                    idle_fields=lambda:{'seconds':60},read=lambda p,n:b'{"active":true,"seq":1,"position":5}')
        output=io.StringIO()
        with patch.dict(sys.modules,{'awake_trial':trial}),patch.object(sys,'path',list(sys.path)), \
             patch('os.stat',return_value=types.SimpleNamespace(st_mtime=time.time())),contextlib.redirect_stdout(output):
            exec(PROBE,{'ROOT':'/fixture/no-files'})
        row=ast.literal_eval(output.getvalue().strip()[7:])
        self.assertEqual(row['player']['position'],5);self.assertEqual(row['lease']['seq'],1)
    def test_builder_rejects_unbounded_or_nonexplicit_hold_before_io(self):
        for value in (-1,True,60,600,130.0):
            with self.assertRaises(ValueError):build(pathlib.Path('never-read'),client=True,automated=True,player_protocol=2,soak_seconds=value)
        with self.assertRaises(ValueError):build(pathlib.Path('never-read'),client=True,player_protocol=2,soak_seconds=130)
    def test_fixed_source_requires_bounded_explicit_automation(self):
        for value in (None,True,'invalid','BV1R7eg6gEnJ"'):
            with self.assertRaises(ValueError):build(pathlib.Path('never-read'),client=True,automated=True,player_protocol=2,soak_seconds=130,soak_bvid=value)
        for fields in ({},{'client':True,'automated':True,'player_protocol':2}):
            with self.assertRaises(ValueError):build(pathlib.Path('never-read'),soak_bvid='BV1R7eg6gEnJ',**fields)

if __name__=='__main__':unittest.main(verbosity=2)
