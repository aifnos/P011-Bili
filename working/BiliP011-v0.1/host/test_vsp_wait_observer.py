import ast,pathlib,unittest
from cached_seek_trial import payload,assess
import test_cached_worker

BASE=pathlib.Path(__file__).resolve().parents[1]

class VspWaitObserverTests(unittest.TestCase):
    def profile(self):
        value=dict(poll_count=200,acquire_count=200,forward_errors=0,clock_errors=0,
                    freq_config_calls=200,freq_config_success=200,freq_config_failed=0,freq_null=0,freq_other=0,
                    timing_schema=1,gap_count=199,gap_clock_errors=0,cycle_schema=2,release_count=200,release_failed=0,
                    cycle_count=199,cycle_incomplete_polls=0,cycle_context_resets=0,cycle_order_resets=0,cycle_clock_errors=0,
                    cycle_extra_pairs=0,cycle_max_extra_pairs=0,seq_contexts=0,seq_start0=0,seq_start1=1,seq_start2=0)
        value.update({'seq_e'+str(i)+str(j):0 for i in range(3) for j in range(3)})
        value.update(seq_e10=200,seq_e02=200,seq_e21=199)
        return value

    def test_scope_and_channel_remain_private_and_no_driver_writes(self):
        source=(BASE/'probes/vsp_wait_observer.cpp').read_text()
        for value in ('RTLD_NOLOAD','__builtin_return_address(0)','P011_VSP_WAIT_PROFILE','/bili-hw','F_DUPFD_CLOEXEC',
                      'S_ISFIFO(info.st_mode)','write(evidence_fd,line','close(evidence_fd)','errno=result_errno;return result;'):
            self.assertIn(value,source)
        for value in ('ioctl(', 'mmap(', 'dup2(', 'write(2,'):
            self.assertNotIn(value,source)
        build=(BASE/'build/build_cached_worker.py').read_text()
        self.assertIn("'/src/probes/vsp_wait_observer.cpp'",build)
        self.assertNotIn('vsp_wait_observer',(BASE/'build/build_hardware.py').read_text())

    def test_payload_numeric_and_python35(self):
        source=payload();ast.parse(source,feature_version=(3,5))
        self.assertIn("env.pop('P011_VSP_WAIT_PROFILE',None)",source)
        self.assertIn("if VSP_PROFILE:env['P011_VSP_WAIT_PROFILE']='1'",source)
        self.assertIn('type(v) is int and v>=0',source)
        self.assertIn('len(profiles)!=1',source)

    def test_enabled_profile_missing_or_failed_cannot_pass(self):
        report=test_cached_worker.CachedWorkerTests().fixture()
        self.assertFalse(assess(report,'cached','throughput',False,True)['passed'])
        report.update(vsp_profile_requested=True,vsp_profile=self.profile())
        self.assertTrue(assess(report,'cached','throughput',False,True)['passed'])
        report['vsp_profile']['forward_errors']=1
        self.assertFalse(assess(report,'cached','throughput',False,True)['passed'])

    def test_frequency_only_forwards_original_argument_and_errno(self):
        source=(BASE/'probes/vsp_wait_observer.cpp').read_text()
        for text in ('FrequencyCall=int(*)(void*,int*)','requested=active&&level?*level:0',
                     'const int result=call(object,level);const int result_errno=errno;',
                     'frequency.levels[requested]++','freq_config_success','freq_level%u'):
            self.assertIn(text,source)
        self.assertNotIn('*level=',source)

    def test_gap_scope_is_thread_local_and_only_observes_timestamps(self):
        source=(BASE/'probes/vsp_wait_observer.cpp').read_text()
        self.assertIn('thread_local VspGapState previous_poll',source)
        self.assertIn('vsp_record_gap(previous_poll,gaps,object,wall0,wall1)',source)
        self.assertIn('if(role==0)previous_poll.valid=false',source)
        header=(BASE/'probes/vsp_gap_stats.hpp').read_text()
        self.assertIn('state.object!=object',header)
        self.assertIn('start<state.end',header)
        self.assertNotIn('->',header)

    def test_current_profile_needs_gap_data(self):
        report=test_cached_worker.CachedWorkerTests().fixture()
        value=self.profile()
        for field in ('timing_schema','gap_count','gap_clock_errors'):
            report.update(vsp_profile_requested=True,vsp_profile={k:v for k,v in value.items() if k!=field})
            self.assertFalse(assess(report,'cached','throughput',False,True)['passed'])

    def test_current_profile_rejects_missing_or_failed_frequency_observation(self):
        report=test_cached_worker.CachedWorkerTests().fixture()
        value=self.profile()
        for field in ('freq_config_calls','freq_config_success','freq_config_failed','freq_null','freq_other'):
            report.update(vsp_profile_requested=True,vsp_profile={k:v for k,v in value.items() if k!=field})
            self.assertFalse(assess(report,'cached','throughput',False,True)['passed'])

    def test_release_and_complete_cycle_evidence_required(self):
        for field in ('cycle_schema','release_count','release_failed','cycle_count','cycle_incomplete_polls',
                      'cycle_context_resets','cycle_order_resets','cycle_clock_errors'):
            value=self.profile();value.pop(field)
            report=test_cached_worker.CachedWorkerTests().fixture()
            report.update(vsp_profile_requested=True,vsp_profile=value)
            self.assertFalse(assess(report,'cached','throughput',False,True)['passed'],field)
        for field,number in (('release_failed',1),('cycle_count',198),('cycle_order_resets',1)):
            value=self.profile();value[field]=number
            report=test_cached_worker.CachedWorkerTests().fixture()
            report.update(vsp_profile_requested=True,vsp_profile=value)
            self.assertFalse(assess(report,'cached','throughput',False,True)['passed'],field)

    def test_release_observer_has_no_vendor_context_reads(self):
        source=(BASE/'probes/vsp_wait_observer.cpp').read_text()
        self.assertIn('VSP_RELEASE_Dev(void*p){return observe(2,p,__builtin_return_address(0),VSP_RELEASE_Dev);}',source)
        self.assertIn('thread_local VspCycleState current_cycle',source)
        self.assertIn('vsp_record_cycle(current_cycle,cycles,role,object,wall0,wall1)',source)
        header=(BASE/'probes/vsp_cycle_stats.hpp').read_text()
        self.assertNotIn('->',header.replace('POLL end -> RELEASE -> ACQUIRE -> next POLL start','sequence'))
        for forbidden in ('memcpy(', 'reinterpret_cast', 'usleep(', 'ioctl(', 'printf('):
            self.assertNotIn(forbidden,header)

    def test_sequence_role_totals_are_not_optional(self):
        fields=('seq_contexts','seq_start0','seq_start1','seq_start2','cycle_extra_pairs','cycle_max_extra_pairs')
        fields+=tuple('seq_e'+str(i)+str(j) for i in range(3) for j in range(3))
        for field in fields:
            value=self.profile();value.pop(field)
            report=test_cached_worker.CachedWorkerTests().fixture()
            report.update(vsp_profile_requested=True,vsp_profile=value)
            self.assertFalse(assess(report,'cached','throughput',False,True)['passed'],field)

if __name__=='__main__':unittest.main()
