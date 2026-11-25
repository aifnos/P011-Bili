"""Synthetic PC-only observation checks; no clock requests or real sysfs I/O."""
import ast
import inspect
import io
import unittest
from unittest.mock import patch
from ddr_observation import read_ddr_state,summarize_ddr


class DdrObservationTests(unittest.TestCase):
    def opener(self,path,mode):
        self.assertEqual(mode,'r');self.assertTrue(path.startswith('/sys/class/devfreq/scene-frequency/'))
        if path.endswith('ddrinfo_freq_table'):return io.StringIO('0 256 384 667\n')
        if path.endswith('scene_dfs_list'):return io.StringIO('boost freq 667  magic 0x0 count 0\n')
        return io.StringIO('384\n')
    def test_python35_and_read_only_whitelist(self):
        source=inspect.getsource(read_ddr_state);ast.parse(source,feature_version=(3,5))
        self.assertNotIn("'w'",source);self.assertNotIn('scenario_dfs',source);self.assertNotIn('scaling_force_ddr_freq',source)
        with patch('builtins.open',side_effect=self.opener):result=read_ddr_state(True)
        self.assertFalse(result['errors']);self.assertEqual(len(result['values']),10)
        self.assertEqual(result['values']['frequency_table_raw'],[0,256,384,667])
    def test_zero_is_preserved_and_not_missing(self):
        with patch('builtins.open',side_effect=lambda *args:io.StringIO('0\n')):result=read_ddr_state()
        self.assertEqual(result['values']['reported_current_raw'],0);self.assertFalse(result['errors'])
    def test_failure_is_not_fabricated_zero(self):
        with patch('builtins.open',side_effect=FileNotFoundError(2,'PRIVATE')):result=read_ddr_state()
        self.assertFalse(result['values']);self.assertEqual(len(result['errors']),4);self.assertNotIn('PRIVATE',str(result))
    def test_invalid_and_oversized_input_is_not_exported(self):
        for value in ('SECRET','-1','4294967296','1.0','x'*4097):
            with self.subTest(value=value[:8]),patch('builtins.open',side_effect=lambda *args:io.StringIO(value)):
                result=read_ddr_state();self.assertFalse(result['values']);self.assertEqual(len(result['errors']),4)
                self.assertNotIn(value[:20],str(result['errors']))
    def test_unknown_and_duplicate_scene_rejected(self):
        for raw in ('private-name freq 667  magic 0x0 count 0','boost freq 667  magic 0x0 count 0\n'*2):
            def opened(path,mode):return io.StringIO(raw) if path.endswith('scene_dfs_list') else self.opener(path,mode)
            with patch('builtins.open',side_effect=opened):result=read_ddr_state(True)
            self.assertEqual(result['errors']['scenes'],{'kind':'format'});self.assertNotIn('scenes',result['values'])
    def rows(self):
        return [dict(time=10+n,process=dict(pid=1,start=2),player=dict(loaded=True,active=n<8,paused=n>=8,position=10),
                     ddr=dict(values=dict(reported_current_raw=667 if n<8 else 384),errors={},read_duration_ms=3.)) for n in range(13)]
    def test_summary_separates_playing_paused_without_claiming_cause(self):
        result=summarize_ddr(self.rows());self.assertTrue(result['observed']);self.assertFalse(result['causal_performance_result'])
        self.assertEqual(result['playing']['reported_current_histogram_raw'],{'667':7})
        self.assertEqual(result['paused']['reported_current_histogram_raw'],{'384':4})
    def test_sparse_zero_missing_and_malformed_observations_do_not_pass(self):
        for value in (0,None,True,'667',-1,4294967296):
            rows=self.rows();rows[3]['ddr']['values']['reported_current_raw']=value
            self.assertFalse(summarize_ddr(rows)['observed'])
        self.assertFalse(summarize_ddr([])['observed']);self.assertFalse(summarize_ddr(self.rows()[:8])['observed'])
        rows=self.rows()
        for n,row in enumerate(rows):row['process']['start']=n
        self.assertFalse(summarize_ddr(rows)['observed'])
    def test_explicit_benchmark_observation_cannot_pass_with_missing_evidence(self):
        import pathlib
        from performance_trial import PROBE
        source=(pathlib.Path(__file__).with_name('performance_trial.py')).read_text(encoding='utf-8')
        self.assertIn("report['passed']=report['passed'] and report['ddr_observation']['observed']",source)
        self.assertEqual(PROBE.count("print('RESULT='+repr(row))"),1)
        assembled=inspect.getsource(read_ddr_state)+'\n'+PROBE.replace("print('RESULT='+repr(row))","row['ddr']=read_ddr_state()\nprint('RESULT='+repr(row))")
        ast.parse(assembled,feature_version=(3,5))


if __name__=='__main__':unittest.main()
