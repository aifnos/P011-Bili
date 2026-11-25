import ast
import pathlib
import unittest
from cached_seek_trial import payload,assess
from test_cached_worker import CachedWorkerTests
from test_vsp_wait_observer import VspWaitObserverTests
from vsp_readback import evaluate_readback


def fixture():
    value=dict(schema=2,stride=64,limit=32,eligible_configurations=900,skipped_configurations=0,calls=15,accepted=15,
               getter_missing=0,return_failed=0,errno_failed=0,invalid_level=0,clock_errors=0,wall_ns=1500,max_ns=100)
    value.update({'level'+str(i):15 if i==3 else 0 for i in range(16)})
    return value


class VspReadbackTests(unittest.TestCase):
    def test_valid_means_driver_reported_level_not_physical_rate(self):
        result=evaluate_readback(fixture())
        self.assertTrue(result['evidence_complete'])
        self.assertEqual(result['driver_reported_levels'],{'3':15})
        self.assertFalse(result['physical_clock_measured'])
        self.assertFalse(result['frequency_changed'])

    def test_missing_unknown_bool_and_out_of_range_rejected(self):
        for key in fixture():
            value=fixture();value.pop(key);self.assertFalse(evaluate_readback(value)['evidence_complete'])
            for bad in (True,-1,2**64,'0'):
                value=fixture();value[key]=bad;self.assertFalse(evaluate_readback(value)['evidence_complete'])
        self.assertFalse(evaluate_readback(dict(fixture(),private_text=0))['evidence_complete'])
        for bad in (None,[],True):self.assertFalse(evaluate_readback(bad)['evidence_complete'])

    def test_swallowed_ioctl_failure_or_nonconserving_counts_rejected(self):
        for key,bad in [('getter_missing',1),('errno_failed',1),('return_failed',1),('invalid_level',1),('clock_errors',1),
                        ('accepted',14),('level3',14),('calls',14),('eligible_configurations',896),('max_ns',1501),('wall_ns',2000),('schema',1)]:
            value=fixture();value[key]=bad;self.assertFalse(evaluate_readback(value)['evidence_complete'],key)

    def test_requested_readback_cannot_silently_pass_without_evidence(self):
        report=CachedWorkerTests().fixture()
        report.update(vsp_profile_requested=True,vsp_profile=VspWaitObserverTests().profile())
        self.assertFalse(assess(report,'cached','throughput',vsp_profile=True,vsp_readback=True)['passed'])
        report.update(vsp_readback_requested=True,vsp_readback=fixture())
        self.assertTrue(assess(report,'cached','throughput',vsp_profile=True,vsp_readback=True)['passed'])
        report['vsp_readback']['errno_failed']=1
        self.assertFalse(assess(report,'cached','throughput',vsp_profile=True,vsp_readback=True)['passed'])

    def test_target_payload_and_bounded_private_readback(self):
        source=payload();ast.parse(source,feature_version=(3,5))
        self.assertIn("env.pop('P011_VSP_CLOCK_READBACK',None)",source)
        self.assertIn("if VSP_READBACK:env['P011_VSP_CLOCK_READBACK']='1'",source)
        cpp=(pathlib.Path(__file__).resolve().parents[1]/'probes/vsp_wait_observer.cpp').read_text()
        for required in ('ordinal%64||readback.calls>=32','configuration_result!=0','int level=-1',
                         'errno=0;result=call(object,&level);error=errno;',
                         'original_symbol<FrequencyCall>("VSP_GET_DEV_FREQ",caller,origin)',
                         'observe_readback(object,caller,(level&&requested>=0&&requested<16)?result:-1);'):
            self.assertIn(required,cpp)
        self.assertNotIn('ioctl(',cpp)


if __name__=='__main__':unittest.main()
