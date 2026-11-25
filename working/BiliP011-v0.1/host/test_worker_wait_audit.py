import copy,unittest
import test_cached_worker_audit
from worker_wait_audit import inspect_sample,inspect_result,inspect_vsp


class WaitAuditTests(unittest.TestCase):
    def test_driver_readback_summary_is_recomputed_and_safe(self):
        from test_vsp_readback import fixture
        from vsp_readback import evaluate_readback
        row=test_cached_worker_audit.CachedWorkerAuditTests().fixture(kind='throughput',fps=60,measured=50)
        row.update(vsp_readback_requested=True,vsp_readback=fixture())
        row['vsp_readback_summary']=evaluate_readback(row['vsp_readback'])
        original=copy.deepcopy(row)
        result=inspect_result(row)
        self.assertTrue(result['current_observation_gate_passed'])
        self.assertEqual(result['readback']['driver_reported_levels'],{'3':15})
        self.assertEqual(row,original)
        for change in (lambda r:r['vsp_readback_summary']['driver_reported_levels'].update(private=1),
                       lambda r:r['vsp_readback_summary']['driver_reported_levels'].update({'3':'secret'}),
                       lambda r:r['vsp_readback_summary']['driver_reported_levels'].update({'3':14}),
                       lambda r:r['vsp_readback_summary'].update(sample_point='private'),
                       lambda r:r['vsp_readback_summary'].update(physical_clock_measured=True)):
            changed=copy.deepcopy(row);change(changed)
            with self.assertRaises(ValueError):inspect_result(changed)

    def test_poll_result_histogram_must_conserve_original_calls(self):
        value=self.sequence_fixture()
        value.update(poll_result_0=0,poll_result_2=0,poll_result_4=0,poll_result_negative=0,
                     poll_result_other=5,poll_result_other_min_u32=512,poll_result_other_max_u32=512)
        self.assertEqual(inspect_vsp(value)['poll_results']['poll_result_other'],5)
        for field,bad in [('poll_result_other',4),('poll_result_other_min_u32',513),('poll_result_other_max_u32',2**31)]:
            changed=copy.deepcopy(value);changed[field]=bad
            with self.assertRaises(ValueError):inspect_vsp(changed)

    def frequency_fixture(self):
        value=dict(poll_count=5,poll_wall_ns=60000000,poll_cpu_ns=100000,poll_max_ns=13000000,
                   poll_lt5ms=0,poll_5to10ms=0,poll_10to20ms=5,poll_20to50ms=0,poll_ge50ms=0,
                   acquire_count=5,acquire_wall_ns=10000,acquire_cpu_ns=1000,acquire_max_ns=5000,
                   stagefright_calls=0,codec_calls=10,forward_errors=0,clock_errors=0,
                   freq_config_calls=5,freq_config_success=5,freq_config_failed=0,freq_null=0,freq_other=0,
                   freq_stagefright_calls=0,freq_codec_calls=5)
        value.update({'freq_level'+str(i):5 if i==3 else 0 for i in range(16)})
        return value

    def test_frequency_request_is_not_a_measured_clock(self):
        result=inspect_vsp(self.frequency_fixture())
        self.assertTrue(result['evidence_complete'])
        self.assertEqual(result['frequency']['requested_levels'],{'3':5})
        self.assertFalse(result['hardware_frequency_measured'])
        self.assertFalse(result['frequency']['actual_clock_measured'])
        self.assertFalse(result['frequency']['requests_changed'])

    def test_frequency_histogram_and_calls_are_complete(self):
        for field,value in (('freq_config_calls',6),('freq_codec_calls',4),('freq_level3',4),
                            ('freq_config_success',4),('freq_null',1),('freq_other',1)):
            sample=self.frequency_fixture();sample[field]=value
            with self.assertRaises(ValueError):inspect_vsp(sample)
        sample=self.frequency_fixture();sample.pop('freq_level0')
        with self.assertRaises(ValueError):inspect_vsp(sample)
        sample=self.frequency_fixture();sample.update(freq_config_success=4,freq_config_failed=1)
        self.assertFalse(inspect_vsp(sample)['evidence_complete'])

    def timing_fixture(self):
        value=self.frequency_fixture()
        value.update(timing_schema=1,gap_count=4,gap_wall_ns=8000000,gap_max_ns=2000000,
                     gap_first_calls=1,gap_context_resets=0,gap_clock_errors=0,
                     gap_lt1ms=0,gap_1to2ms=0,gap_2to5ms=4,gap_5to10ms=0,gap_10to20ms=0,gap_ge20ms=0,
                     poll_detail_lt8ms=0,poll_detail_8to12ms=0,poll_detail_12to16_667ms=5,poll_detail_16_667to20ms=0,
                     poll_detail_20to25ms=0,poll_detail_25to33_333ms=0,poll_detail_33_333to50ms=0,poll_detail_ge50ms=0)
        return value

    def test_timing_is_call_scope_not_a_frame_or_hardware_claim(self):
        result=inspect_vsp(self.timing_fixture())
        self.assertTrue(result['evidence_complete'])
        self.assertEqual(result['timing']['mean_gap_ms'],2)
        self.assertEqual(result['timing']['poll_at_least_16_667ms'],0)
        self.assertTrue(result['timing']['not_per_frame_or_pure_hardware_time'])
        self.assertIsNone(inspect_vsp(self.frequency_fixture())['timing'])

    def test_timing_fields_histograms_and_conservation_are_required(self):
        for field,value in (('timing_schema',2),('gap_count',3),('gap_first_calls',2),('gap_2to5ms',3),
                            ('gap_max_ns',9000000),('poll_detail_12to16_667ms',4),('poll_detail_ge50ms',1)):
            row=self.timing_fixture();row[field]=value
            with self.assertRaises(ValueError):inspect_vsp(row)
        row=self.timing_fixture();row.pop('gap_clock_errors')
        with self.assertRaises(ValueError):inspect_vsp(row)

    def test_gap_clock_failure_stays_failed(self):
        row=self.timing_fixture();row.update(gap_clock_errors=1,gap_first_calls=0)
        self.assertFalse(inspect_vsp(row)['evidence_complete'])

    def cycle_fixture(self):
        value=self.timing_fixture()
        value.update(cycle_schema=1,release_count=5,release_wall_ns=500000,release_cpu_ns=5000,release_max_ns=100000,release_failed=0,
                     acquire_wall_ns=500000,acquire_max_ns=100000,codec_calls=15,
                     cycle_count=4,cycle_first_polls=1,cycle_incomplete_polls=0,cycle_context_resets=0,cycle_order_resets=0,cycle_clock_errors=0,
                     cycle_gap_wall_ns=8000000,cycle_gap_max_ns=2000000)
        for part,ns in (('postpoll',100000),('release',100000),('outer',1200000),('acquire',100000),('prepare',500000)):
            value['cycle_'+part+'_wall_ns']=ns*4;value['cycle_'+part+'_max_ns']=ns
        return value

    def test_cycle_derived_values_and_narrow_scope(self):
        result=inspect_vsp(self.cycle_fixture());cycle=result['cycle']
        self.assertTrue(result['evidence_complete']);self.assertEqual(cycle['count'],4)
        self.assertEqual(cycle['mean_gap_ms'],2);self.assertEqual(cycle['parts']['outer']['mean_ms'],1.2)
        self.assertAlmostEqual(sum(p['mean_ms'] for p in cycle['parts'].values()),cycle['mean_gap_ms'])
        self.assertTrue(cycle['input_copy_not_isolated']);self.assertTrue(cycle['includes_observer_and_scheduling'])
        self.assertIsNone(inspect_vsp(self.timing_fixture())['cycle'])

    def test_cycle_partition_must_match_calls_and_gap(self):
        for field,number in (('cycle_schema',2),('release_count',6),('cycle_count',3),('cycle_first_polls',0),
                             ('cycle_gap_wall_ns',7000000),('cycle_gap_max_ns',1900000),('cycle_release_wall_ns',500001),
                             ('cycle_outer_max_ns',3000000),('cycle_prepare_max_ns',1),('release_cpu_ns',600000)):
            value=self.cycle_fixture();value[field]=number
            with self.assertRaises(ValueError,msg=field):inspect_vsp(value)
        value=self.cycle_fixture();value.pop('cycle_prepare_wall_ns')
        with self.assertRaises(ValueError):inspect_vsp(value)

    def test_cycle_errors_and_release_failure_reject_evidence(self):
        for field in ('release_failed','cycle_order_resets','cycle_context_resets','cycle_clock_errors'):
            value=self.cycle_fixture();value[field]=1
            self.assertFalse(inspect_vsp(value)['evidence_complete'],field)

    def sequence_fixture(self,extra=False):
        value=self.cycle_fixture()
        value.update(cycle_schema=2,cycle_extra_pairs=0,cycle_max_extra_pairs=0,seq_contexts=0,
                     seq_start0=0,seq_start1=1,seq_start2=0)
        value.update({'seq_e'+str(i)+str(j):0 for i in range(3) for j in range(3)})
        value.update(seq_e02=5,seq_e10=5,seq_e21=4)
        if extra:
            value.update(acquire_count=7,release_count=7,codec_calls=19,acquire_wall_ns=700000,release_wall_ns=700000,
                         cycle_extra_pairs=2,cycle_max_extra_pairs=1,seq_e12=2,seq_e21=6,
                         cycle_release_wall_ns=600000,cycle_release_max_ns=200000,
                         cycle_acquire_wall_ns=600000,cycle_acquire_max_ns=200000,cycle_prepare_wall_ns=1600000)
        return value

    def test_extra_pairs_have_independent_sequence_and_duration_evidence(self):
        for extra in (False,True):
            result=inspect_vsp(self.sequence_fixture(extra))
            self.assertTrue(result['evidence_complete'])
            self.assertEqual(result['cycle']['extra_pairs'],2 if extra else 0)
            self.assertEqual(result['cycle']['mean_gap_ms'],2)
            self.assertFalse(result['cycle']['single_pair_assumption'])
            self.assertEqual(result['sequence']['transitions']['acquire_to_release'],2 if extra else 0)
            self.assertFalse(result['sequence']['frame_or_nal_identity_observed'])
        self.assertIsNone(inspect_vsp(self.cycle_fixture())['sequence'])

    def test_extra_pair_and_role_conservation_rejects_partial_or_fabricated_data(self):
        for field,number in (('cycle_extra_pairs',3),('cycle_max_extra_pairs',3),('cycle_schema',1),('seq_e12',1),
                             ('seq_start1',0),('seq_contexts',2),('cycle_release_max_ns',300000)):
            value=self.sequence_fixture(True);value[field]=number
            with self.assertRaises(ValueError,msg=field):inspect_vsp(value)
        for field in ('seq_start0','seq_e00','cycle_extra_pairs','cycle_max_extra_pairs'):
            value=self.sequence_fixture();value.pop(field)
            with self.assertRaises(ValueError,msg=field):inspect_vsp(value)
        value=self.sequence_fixture();value['seq_contexts']=1
        self.assertFalse(inspect_vsp(value)['evidence_complete'])

    def test_legacy_single_pair_failure_is_not_upgraded(self):
        value=self.cycle_fixture()
        value.update(cycle_count=3,cycle_incomplete_polls=1,cycle_order_resets=1,
                     cycle_gap_wall_ns=6000000)
        for part in ('postpoll','release','outer','acquire','prepare'):
            value['cycle_'+part+'_wall_ns']=value['cycle_'+part+'_max_ns']*3
        self.assertFalse(inspect_vsp(value)['evidence_complete'])
        self.assertTrue(inspect_vsp(value)['cycle']['single_pair_assumption'])

    def test_observer_numeric_report_fits_one_pipe_write(self):
        import json
        # Every unsigned counter at its widest value still fits the fixed line;
        # a long diagnostic must not silently disappear at teardown.
        widest={k:2**64-1 for k in self.sequence_fixture()}
        self.assertLess(len('P011_VSP_PROFILE='+json.dumps(widest,separators=(',',':'))+'\n'),4096)

    def sample(self):
        return dict(enabled=True,joined=True,identity_rejected=False,worker_observed=True,children_interface=False,
                    elapsed_seconds=20,samples=18,process_cpu_seconds=.5,interval_seconds=1,ticks_per_second=100,
                    max_samples=50,read_errors=0,sampling_wall_seconds=.5,clocks={'cpu0_khz':{'768000':18}},
                    threads={'222_999':dict(name='dec',samples=18,first_user=10,first_system=2,first_at=100,
                        last_user=100,last_system=12,last_at=117,policy=0,priority=0,states={'S':18},waits={'unavailable':18},
                        stacks={},syscalls={'vsp_poll_complete':18},wchan_available=False,schedstat_available=False)})

    def test_derived_cpu_and_no_duration_claim(self):
        result=inspect_sample(self.sample())
        self.assertTrue(result['evidence_complete']);self.assertEqual(result['observer_cpu_percent'],2.5)
        self.assertEqual(result['threads'][0]['cpu_seconds'],1)
        self.assertFalse(result['kernel_symbols_available']);self.assertFalse(result['scheduler_wait_available'])
        self.assertTrue(result['one_second_snapshot_not_a_function_duration'])

    def test_missing_or_historically_empty_samples_are_rejected_without_rewriting(self):
        row=test_cached_worker_audit.CachedWorkerAuditTests().fixture(kind='throughput',fps=60,measured=52)
        sample=self.sample();sample['threads']={};row['wait_sample']=sample
        original=copy.deepcopy(row);result=inspect_result(row)
        self.assertEqual(row,original)
        self.assertFalse(result['current_observation_gate_passed'])
        self.assertTrue(result['run_diagnostic_passed'])
        self.assertTrue(result['original_verdict_disagrees_with_complete_observation'])
        sample.pop('children_interface');self.assertFalse(inspect_sample(sample)['evidence_complete'])

    def test_safe_archive_gate_rejects_arbitrary_values_and_private_fields(self):
        for change in (lambda s:s.update(url='https://private'),
                       lambda s:s['threads']['222_999'].update(name='https://private'),
                       lambda s:s['threads']['222_999'].update(last_user=0),
                       lambda s:s['threads']['222_999']['syscalls'].update(secret=1),
                       lambda s:s['threads']['222_999']['states'].update(S=17),
                       lambda s:s['threads']['222_999'].update(raw_stack='deadbeef'),
                       lambda s:s['clocks'].update(private_address={'123':1}),
                       lambda s:s.update(process_cpu_seconds=float('nan'))):
            value=self.sample();change(value)
            with self.assertRaises(ValueError):inspect_sample(value)

    def test_vsp_clock_and_counts_are_conserved(self):
        value=dict(poll_count=5,poll_wall_ns=60000000,poll_cpu_ns=100000,poll_max_ns=13000000,
                   poll_lt5ms=0,poll_5to10ms=0,poll_10to20ms=5,poll_20to50ms=0,poll_ge50ms=0,
                   acquire_count=5,acquire_wall_ns=10000,acquire_cpu_ns=1000,acquire_max_ns=5000,
                   stagefright_calls=0,codec_calls=10,forward_errors=0,clock_errors=0)
        result=inspect_vsp(value)
        self.assertTrue(result['evidence_complete']);self.assertEqual(result['mean_poll_ms'],12)
        self.assertTrue(result['call_wall_time_includes_scheduling'])
        for field,number in (('codec_calls',11),('poll_10to20ms',4),('acquire_cpu_ns',50000),('private_pointer',12345)):
            bad=dict(value);bad[field]=number
            with self.assertRaises(ValueError):inspect_vsp(bad)


if __name__=='__main__':unittest.main()
