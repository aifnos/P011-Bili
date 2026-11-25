import ast
import copy
import importlib.util
import json
import pathlib
import re
import unittest
from omx_format_profile import check_format_shape, inspect_format
from cached_seek_trial import payload, assess
import test_cached_worker
import test_cached_worker_audit
from worker_wait_audit import inspect_result

BASE = pathlib.Path(__file__).resolve().parents[1]


def fixture(fps=60):
    request = [1,0,1920,1080,1920,1088,fps*65536,fps,1,7,21,20,3133440,0]
    readback = list(request); readback[0] = 2
    output = list(request); output[0] = 3; output[1] = 1; output[9] = 0
    return dict(schema=1,count=3,overflow=0,invalid=0,records=[request,readback,output])


class OmxFormatProfileTests(unittest.TestCase):
    def test_three_source_rates_and_noninteger_q16(self):
        for fps in (30,50,60):
            result=inspect_format(fixture(fps),fps)
            self.assertTrue(result['evidence_complete'])
            self.assertTrue(result['input_matches_requested'])
            self.assertTrue(result['requested_fps_matches_caps'])
            self.assertTrue(result['caps_match_source'])
            self.assertFalse(result['performance_passed'])
        value=fixture()
        for row in value['records']:row[6:9]=[int(60000/1001*65536),60000,1001]
        self.assertTrue(inspect_format(value,60000/1001)['requested_fps_matches_caps'])

    def test_mismatch_is_observed_not_silently_accepted_or_discarded(self):
        value=fixture();value['records'][1][6]=30*65536
        result=inspect_format(value,60)
        self.assertTrue(result['evidence_complete'])
        self.assertTrue(result['calls_succeeded'])
        self.assertFalse(result['input_matches_requested'])
        value['records'][1][13]=0x80001000
        self.assertFalse(inspect_format(value)['calls_succeeded'])
        self.assertEqual(inspect_format(value)['groups'][0]['input_readback']['error'],0x80001000)

    def test_missing_overflow_bad_order_and_caps_cannot_be_complete(self):
        for change in (lambda v:v.update(overflow=1),lambda v:v.update(invalid=1),
                       lambda v:v.update(count=0,records=[]),
                       lambda v:v.update(count=2,records=v['records'][:2]),
                       lambda v:v['records'][1].__setitem__(0,1),
                       lambda v:v['records'][2].__setitem__(8,2)):
            value=fixture();change(value)
            self.assertFalse(inspect_format(value)['evidence_complete'])
        value=fixture()
        self.assertFalse(inspect_format(value,30)['caps_match_source'])
        for row in value['records']:row[8]=0
        self.assertFalse(inspect_format(value)['requested_fps_matches_caps'])

    def test_numeric_privacy_and_bounds(self):
        for change in (lambda v:v.update(url='private'),lambda v:v.update(schema=True),
                       lambda v:v.update(count=4),lambda v:v.update(count=25,records=v['records']*8+[v['records'][0]]),
                       lambda v:v['records'][0].append(0),lambda v:v['records'][0].__setitem__(6,-1),
                       lambda v:v['records'][0].__setitem__(6,2**32),lambda v:v['records'][0].__setitem__(6,True),
                       lambda v:v['records'][0].__setitem__(6,'private')):
            value=fixture();change(value)
            with self.assertRaises(ValueError):check_format_shape(value)
        widest=dict(schema=1,count=24,overflow=2**32-1,invalid=2**32-1,records=[[1]+[2**32-1]*13]*24)
        check_format_shape(widest)
        self.assertLess(len('P011_OMX_FORMAT='+json.dumps(widest,separators=(',',':'))+'\n'),4096)

    def test_new_driver_requires_format_only_when_requested(self):
        report=test_cached_worker.CachedWorkerTests().fixture()
        self.assertTrue(assess(copy.deepcopy(report),'cached','throughput')['passed'])
        self.assertFalse(assess(copy.deepcopy(report),'cached','throughput',format_profile=True)['passed'])
        report.update(format_profile_requested=True,format_profile=fixture())
        self.assertTrue(assess(report,'cached','throughput',format_profile=True)['passed'])
        report['format_profile']['records'][1][6]=30*65536
        self.assertTrue(assess(report,'cached','throughput',format_profile=True)['passed'])
        self.assertFalse(report['playback_passed'])

    def test_legacy_audit_stays_legacy_and_new_missing_format_is_rejected(self):
        row=test_cached_worker_audit.CachedWorkerAuditTests().fixture(kind='throughput',fps=60,measured=52)
        original=copy.deepcopy(row)
        self.assertIsNone(inspect_result(row)['formats'])
        self.assertEqual(original,row)
        row['format_profile_requested']=True
        self.assertFalse(inspect_result(row)['current_observation_gate_passed'])
        row['format_profile']=fixture()
        self.assertTrue(inspect_result(row)['current_observation_gate_passed'])

    def test_python35_remote_single_record_and_no_vendor_raw_output(self):
        source=payload();ast.parse(source,feature_version=(3,5))
        self.assertLess(len(source.encode('utf-8')),64000)
        for part in ('len(formats)!=1','check_format_shape(format_profile)',"report['format_profile_requested']=VSP_PROFILE"):
            self.assertIn(part,source)

    def test_overlay_has_same_component_calls_and_preserves_failure_returns(self):
        spec=importlib.util.spec_from_file_location('format_test_overlay',BASE/'build/format_omx_overlay.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        source=(BASE/'third_party/gst-omx-1.14.2-p011/omx/gstomxvideodec.c').read_text(encoding='utf-8')
        result=module.overlay('gstomxvideodec.c',source)
        pattern=r'gst_omx_(?:port_update_port_definition|component_get_parameter|component_set_parameter)\s*\('
        self.assertEqual(re.findall(pattern,result),re.findall(pattern,source))
        self.assertEqual(result.count('p011_omx_format_record ('),3)
        self.assertEqual(result.count('if (p011_format_error != OMX_ErrorNone)\n      return FALSE;'),2)
        with self.assertRaises(ValueError):module.overlay('gstomxvideodec.c',result)
        self.assertEqual(module.overlay('gstomx.c',source),source)
        for shared in ('build/build_cache_plugin.py','build/cache_omx_overlay.py','build/build_hardware.py'):
            self.assertNotIn('omx_format_', (BASE/shared).read_text())


if __name__=='__main__':unittest.main()
