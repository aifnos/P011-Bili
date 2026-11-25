import unittest
from frame_diagnostics import analyze,PHASES,FIELDS,COMPONENTS,GLYPHS

class FrameDiagnosticsTests(unittest.TestCase):
    def rows(self):
        rows=[]
        for n in range(4):
            s=dict(active=True,loaded=True,hardware_verified=True,position=2+n,hardware_total_drops=n)
            s.update({k:n if k==COMPONENTS[-1] else 0 for k in COMPONENTS});s.update({k:n for k in GLYPHS})
            for p in PHASES:
                for f in FIELDS:s['phase_'+p+'_'+f]=n
            rows.append(dict(player=s))
        return rows
    def test_explicit_warmup_and_component_events(self):
        r=analyze(self.rows());self.assertTrue(r['available']);self.assertIn('including_warmup',r['scope'])
        self.assertEqual(len(r['events']),3);self.assertEqual(r['observed_drop_deltas'][COMPONENTS[-1]],3)
        self.assertEqual(r['events'][0]['position_from'],2);self.assertEqual(r['events'][0]['glyph_deltas'][GLYPHS[0]],1)
    def test_old_missing_or_boolean_values_not_evidence(self):
        self.assertFalse(analyze([])['available'])
        for bad in (None,True,-1,1.2,'1'):
            rows=self.rows();rows[1]['player']['phase_overlay_count']=bad
            self.assertFalse(analyze(rows)['available'])
    def test_position_is_finite(self):
        for bad in (True,None,float('nan'),float('inf'),-1):
            rows=self.rows();rows[1]['player']['position']=bad
            self.assertFalse(analyze(rows)['available'])
    def test_reject_component_mismatch_and_counter_reset(self):
        rows=self.rows();rows[2]['player']['hardware_total_drops']=99
        self.assertFalse(analyze(rows)['available'])
        rows=self.rows();rows[2]['player']['phase_swap_total_us']=0
        self.assertEqual(analyze(rows)['reason'],'counter_reset')
    def test_paused_not_counted_and_player_total_not_used(self):
        rows=self.rows()
        for r in rows:r['player']['drops']=999
        rows.append(dict(player=dict(active=False,loaded=True,hardware_verified=True)))
        self.assertTrue(analyze(rows)['available']);self.assertEqual(analyze(rows)['samples'],4)
    def test_instrumentation_is_guarded_and_contains_no_media(self):
        from pathlib import Path
        base=Path(__file__).resolve().parents[1]
        src=(base/'client/player_v2.cpp').read_text(encoding='utf-8')
        self.assertIn('profile_playing=hw.active&&loaded&&!pause&&!idle&&!replacing',src)
        self.assertIn('painter.glyph_metric_loads',src)
        pure=(base/'client/player_phase.hpp').read_text()
        self.assertNotIn('std::string',pure);self.assertNotIn('getenv(',pure)
        self.assertIn('if(!playing)return',pure)
        self.assertIn("'player_phase'",(base/'build/build_strip_player.py').read_text())

if __name__=='__main__':unittest.main()
