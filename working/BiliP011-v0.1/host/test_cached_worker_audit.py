import copy,unittest
from cached_worker_audit import audit_row,compare,numeric,remote_record

class CachedWorkerAuditTests(unittest.TestCase):
    def fixture(self,mode='cached',kind='rate',fps=30,measured=None,failed=False):
        if measured is None:measured=fps
        enabled=mode=='cached';drops=500 if failed else 0
        final=dict(cache_final=True,cache_active=0,cache_registered=20,cache_forgotten=20,
                   cache_read_begin=500,cache_read_end=500,cache_sync_errors=0,cache_ownership_errors=0,
                   cache_changed_allocations=20 if enabled else 0,cache_control_allocations=0 if enabled else 20)
        rate=dict(source_fps=fps,consumed_fps=measured,consumed_frames=measured*12,elapsed_seconds=12,
                  drops=0,decoder_drops=drops,encoded_nonref_skipped=0,omx_profile_copy_count=360,
                  omx_profile_copy_wall_ns=(3 if enabled else 20)*360e6,omx_profile_fill_count=360,
                  omx_profile_fill_wall_ns=(4 if enabled else 21)*360e6,omx_profile_acquire_wall_ns=100,
                  mean_reported_worker_cpu_percent=48 if enabled else 147,queue_samples=100,queue_nonempty_samples=100)
        status=dict(output_cache_probe=True,output_cache_enabled=enabled,encoded_nonref_skipped=0,
                    hardware_library=True,vsp_open=True,omx_private_plugin=True,fused_half_copy=True,
                    unsynchronized_throughput_probe=kind=='throughput',position=139)
        near=not failed and measured>=fps*.95
        return dict(kind=kind,cache_mode=mode,bvid='BV1Da411Y7U4',artifact='cached-worker-'+'a'*16,
            binaries={k:'a'*64 for k in ('bili-hw','hardware-seek-probe','libgstomx.so')},
            passed_scope='no_window_cached_worker_'+kind+'_only',width=1920,height=1080,
            stock_unchanged=True,factory_config_unchanged=True,cache_vendor_unchanged=True,
            owned_probe_directory_removed=True,cache_worker_preflight=True,leftover_workers=0,
            playback_passed=False,physical_acceptance=False,window_opened=False,stock_ui_replaced=False,
            audible_audio_requested=False,child_exit=1 if failed else 0,passed=not failed,
            worker_rate_met=near and kind=='rate',unclocked_rate_meets_source=near and kind=='throughput',
            probe=dict(passed=not failed,worker_failed=False,worker_error=0,private_plugin_loaded=True,
                cache_final=final,worker_status=status,rate=rate,last_frame_pts=139,paused_position=138,paused_frame_pts=138.1,
                lifecycle=dict(starts=1,normal_exits=1,last_exit=0,forced_kills=0,abnormal_exits=0,max_close_ms=80)))

    def series(self):
        return [self.fixture('uncached'),self.fixture(),self.fixture('uncached'),self.fixture(kind='seek'),
                self.fixture(fps=60,measured=.5,failed=True),self.fixture(fps=50,measured=.5,failed=True),
                self.fixture(kind='throughput',fps=60,measured=52),self.fixture('uncached','throughput',60,47),
                self.fixture(kind='throughput',fps=50,measured=48)]

    def test_failed_rates_remain_failed_while_cpu_gain_is_separate(self):
        report=compare(self.series())
        self.assertTrue(report['evidence_valid']);self.assertEqual(report['failed_driver_runs'],2)
        self.assertTrue(report['thirty_fps_worker_rate_passed']);self.assertTrue(report['cached_seek_passed'])
        self.assertGreater(report['cpu_reduction_vs_lower_control_percent'],60)
        self.assertFalse(report['playback_passed']);self.assertFalse(report['full_high_rate_playback_passed'])
        self.assertFalse(report['production_integration_verified']);self.assertFalse(report['power_measured'])

    def test_unclocked_tolerance_is_not_exact_source_fps(self):
        sample=audit_row(self.fixture(kind='throughput',fps=50,measured=48))
        self.assertTrue(sample['within_five_percent_diagnostic_gate'])
        self.assertFalse(sample['measured_at_least_source_rate'])

    def test_rejects_identity_lifecycle_hidden_skips_and_false_claims(self):
        for mutate in (lambda r:r[1]['probe']['cache_final'].update(cache_active=1),
                       lambda r:r[1]['probe']['cache_final'].update(cache_read_end=499),
                       lambda r:r[1]['probe']['worker_status'].update(encoded_nonref_skipped=1),
                       lambda r:r[1].update(playback_passed=True),
                       lambda r:r[1].update(artifact='cached-worker-'+'b'*16),
                       lambda r:r[4].update(passed=True),
                       lambda r:r[1]['probe']['lifecycle'].update(forced_kills=1),
                       lambda r:r[1]['probe']['rate'].update(consumed_frames=359),
                       lambda r:r[1]['probe']['rate'].update(worker_url='https://private.example')):
            rows=self.series();mutate(rows)
            with self.assertRaises(ValueError):compare(rows)

    def test_requires_controls_and_high_rate_failures(self):
        rows=self.series();rows[4]=copy.deepcopy(rows[0])
        with self.assertRaises(ValueError):compare(rows)
        rows=self.series();rows[0]['cache_mode']='cached'
        with self.assertRaises(ValueError):compare(rows)

    def test_numeric_records_reject_secrets_and_nonfinite_numbers(self):
        numeric(dict(ok=True,nested=[1,2.5,dict(error=0)]))
        for value in ('private',dict(value='secret'),float('nan'),float('inf'),None,dict(**{'../key':1})):
            with self.assertRaises(ValueError):numeric(value)

    def test_raw_parser_retains_separate_transport_exit(self):
        raw=b"RESULT={'child_exit': 1, 'probe': {'passed': False}}\r\r\n\r\r\n__REMOTE_EXIT__=0\r\r\n"
        self.assertEqual(remote_record(raw),dict(child_exit=1,probe=dict(passed=False)))
        for bad in (raw.replace(b'__REMOTE_EXIT__=0',b'__REMOTE_EXIT__=1'),raw+raw,
                    raw.replace(b"'child_exit': 1",b"'child_exit': 'secret'"),raw+b'private output\n'):
            with self.assertRaises(ValueError):remote_record(bad)

if __name__=='__main__':unittest.main()
