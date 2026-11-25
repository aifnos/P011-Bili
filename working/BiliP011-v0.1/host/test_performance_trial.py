"""Host-only audit of numeric benchmark accounting and explicit build gate."""
import ast,pathlib,re,unittest
from performance_trial import metrics,PROBE,compatible_playback,paused_capture_policy,fused_copy_verified,cached_retention_verified,frame_rate_states_verified
from build_awake_trial import build

class PerformanceTests(unittest.TestCase):
    def rows(self):
        return [dict(time=10+n,process=dict(pid=1,start=2,ticks=100+n*50,hz=100,rss_kb=50000),player=dict(position=6+n,loaded=True,active=True,paused=False,drops=2)) for n in range(8)]
    def test_cpu_single_core_percent(self):
        r=metrics(self.rows())['playing'];self.assertEqual(r['mean_cpu_percent'],50);self.assertEqual(r['samples'],7);self.assertEqual(r['dropped_frames_delta'],0)
    def test_fused_evidence_requires_real_dimensions_and_backend(self):
        rows=self.rows()
        for n,row in enumerate(rows):row['player'].update(source_width=1920,source_height=1080,hardware_output_width=960,
            hardware_output_height=540,hardware_fused_frames=100+n*30,hardware_verified=True,hardware_private_plugin=True,hardware_fused_copy=True)
        self.assertTrue(fused_copy_verified(rows));self.assertFalse(fused_copy_verified(rows[:4]));self.assertFalse(fused_copy_verified([]))
        for field,value in (('hardware_output_width',1920),('hardware_output_height',270),('hardware_fused_frames',0),
                            ('hardware_fused_frames',True),('hardware_fused_copy',False),('hardware_verified',False),('source_width',3840)):
            changed=[dict(row,player=dict(row['player'])) for row in rows];changed[3]['player'][field]=value
            self.assertFalse(fused_copy_verified(changed))
    def test_fused_evidence_rejects_stale_or_reset_frames(self):
        for bad in (100,129,130):
            rows=self.rows()
            for n,row in enumerate(rows):row['player'].update(source_width=1920,source_height=1080,hardware_output_width=960,
                hardware_output_height=540,hardware_fused_frames=100+n*30,hardware_verified=True,hardware_private_plugin=True,hardware_fused_copy=True)
            rows[2]['player']['hardware_fused_frames']=bad
            self.assertFalse(fused_copy_verified(rows))
    def test_fused_evidence_requires_finite_advancing_playback(self):
        for bad in (None,True,'8',float('nan'),float('inf'),6,7):
            rows=self.rows()
            for n,row in enumerate(rows):row['player'].update(source_width=1920,source_height=1080,hardware_output_width=960,
                hardware_output_height=540,hardware_fused_frames=100+n*30,hardware_verified=True,hardware_private_plugin=True,hardware_fused_copy=True)
            rows[2]['player']['position']=bad
            self.assertFalse(fused_copy_verified(rows))
    def test_pid_reuse_not_correlated(self):
        rows=self.rows()
        for n,row in enumerate(rows):row['process']['start']=n
        self.assertEqual(metrics(rows)['playing']['samples'],0)
    def test_paused_requires_both_ends(self):
        rows=self.rows()
        for row in rows[3:]:row['player'].update(paused=True,active=False)
        self.assertEqual(metrics(rows)['paused']['samples'],4)
    def test_probe_python35(self):ast.parse(PROBE,feature_version=(3,5))
    def test_child_restart_excluded_from_cpu_delta(self):
        rows=self.rows()
        for n,row in enumerate(rows):row['process']['children']=[dict(pid=3,start=n)]
        self.assertEqual(metrics(rows)['playing']['samples'],0)
    def test_hardware_process_counted_with_parent(self):
        self.assertIn("config.MEDIA+'/bin/bili-hw'",PROBE)
        self.assertIn("row['process']['ticks']+=",PROBE)
    def test_sample_is_fixed_not_personalized(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/'client/BiliPerformance.qml').read_text(encoding='utf-8')
        self.assertIn('@BENCHMARK_BVID@',source);self.assertIn('target.selectedCodec=7',source)
        self.assertIn('115000',source);self.assertNotIn('following',source)
    def test_empty_no_success(self):self.assertIsNone(metrics([])['playing']['mean_cpu_percent'])
    def test_screenshots_do_not_pollute_playing_window(self):
        rows=self.rows()
        self.assertFalse(paused_capture_policy(rows))
        rows.append(dict(player=dict(paused=True,active=False,capture_count=2)))
        self.assertTrue(paused_capture_policy(rows))
        rows[2]['player']['capture_count']=1
        self.assertFalse(paused_capture_policy(rows))
    def test_capture_counter_is_strict(self):
        for count in (-1,True,1.5,'1',None):
            self.assertFalse(paused_capture_policy([dict(player=dict(paused=True,capture_count=count))]))
        source=(pathlib.Path(__file__).resolve().parents[1]/'client/BiliPerformance.qml').read_text(encoding='utf-8')
        self.assertIn('if(stage===4&&p.paused&&!captured)',source)
        self.assertNotIn('p.position>=24&&!capturedStats',source)
    def rate_rows(self):
        rows=self.rows()
        for row in rows:row['player'].update(stats_rate_state=3,submitted_fps=30.)
        for n in range(5):
            rows.append(dict(time=18+n,process=dict(pid=1,start=2),player=dict(
                position=13,loaded=True,active=False,paused=True,stats_rate_state=1,submitted_fps=0.)))
        return rows
    def test_rate_state_requires_both_playing_and_paused_windows(self):
        rows=self.rate_rows();self.assertTrue(frame_rate_states_verified(rows))
        self.assertFalse(frame_rate_states_verified(rows[:8]));self.assertFalse(frame_rate_states_verified(rows[8:]))
        self.assertFalse(frame_rate_states_verified([]))
        self.assertEqual(rows[-1]['player']['submitted_fps'],0.)
    def test_rate_state_rejects_old_or_misclassified_status(self):
        for value in (None,True,1.,'1',0,2,3,4):
            rows=self.rate_rows();rows[-1]['player']['stats_rate_state']=value
            self.assertFalse(frame_rate_states_verified(rows))
        rows=self.rate_rows();rows[3]['player']['stats_rate_state']=1
        self.assertFalse(frame_rate_states_verified(rows))
    def test_rate_state_does_not_count_pause_edge_as_measurement(self):
        rows=self.rate_rows();rows[8]['player']['stats_rate_state']=3
        self.assertTrue(frame_rate_states_verified(rows))
    def test_rate_state_rejects_repeated_time_pid_reuse_and_switching(self):
        for field,value in (('time',10),('switch_pending',True),('position',float('nan'))):
            rows=self.rate_rows()
            for row in rows:
                if field=='time':row[field]=value
                else:row['player'][field]=value
            self.assertFalse(frame_rate_states_verified(rows))
        rows=self.rate_rows()
        for n,row in enumerate(rows):row['process']['start']=n
        self.assertFalse(frame_rate_states_verified(rows))
    def test_compatibility_is_separate_from_full_source_rate(self):
        v=dict(samples=8,high_fps_compat=True,wall_seconds=12.,source_fps=60.,submitted_fps=41.,maximum_avsync_ms=100.,
               nonref_skipped_frames_delta=228,dropped_frames_delta=0,decoder_dropped_frames_delta=0)
        self.assertTrue(compatible_playback(v,True));self.assertFalse(v['submitted_fps']>=v['source_fps']*.95)
        self.assertFalse(compatible_playback(v,False))
        for changes in (dict(high_fps_compat=False),dict(nonref_skipped_frames_delta=0),dict(submitted_fps=29.),
                        dict(maximum_avsync_ms=151),dict(dropped_frames_delta=100),dict(source_fps=30.),
                        dict(submitted_fps=float('nan')),dict(wall_seconds=9),dict(samples=4),dict(decoder_dropped_frames_delta=-1)):
            self.assertFalse(compatible_playback(dict(v,**changes),True))
    def test_actual_frames_not_ui_draw_count(self):
        rows=self.rows()
        for n,row in enumerate(rows):row['player'].update(submitted_frames=n*30,draws=n*100,source_fps=60,avsync=.08)
        r=metrics(rows)['playing'];self.assertEqual(r['submitted_fps'],30);self.assertEqual(r['source_fps'],60);self.assertEqual(r['maximum_avsync_ms'],80)

    def test_cached_retention_requires_cache_policy_and_retained_frame_rate(self):
        rows=[]
        for n in range(15):
            state=dict(active=True,loaded=True,position=6+n,hardware_verified=True,hardware_private_plugin=True,
                hardware_cache_feature=True,hardware_cache_vendor_verified=True,hardware_output_cache_enabled=True,
                hardware_cache_sync_errors=0,hardware_cache_ownership_errors=0,hardware_cache_changed_allocations=20,
                hardware_cache_read_begin=100+n*45,hardware_cache_registered=20,source_width=1920,source_height=1080)
            state.update(high_fps_compat=True,hardware_cached_retention_active=True,hardware_nonref_keep_every=2,
                hardware_encoded=100+n*45,hardware_nonref_skipped=50+n*15,submitted_frames=n*45,
                source_fps=60,avsync=.05,drops=0,decoder_drops=0)
            rows.append(dict(time=10+n,process=dict(pid=1,start=2,ticks=100+n*60,hz=100,rss_kb=50000),player=state))
        playing=metrics(rows)['playing']
        self.assertTrue(cached_retention_verified(rows,playing,True))
        self.assertFalse(cached_retention_verified(rows,playing,False))
        for changes in (dict(cached_retention_active=False),dict(submitted_fps=40),dict(encoded_frames_delta=None),
                        dict(encoded_frames_delta=True),dict(encoded_frames_delta=900),dict(source_fps=120)):
            self.assertFalse(cached_retention_verified(rows,dict(playing,**changes),True))
        for field,value in (('hardware_cached_retention_active',False),('hardware_nonref_keep_every',0),
                            ('hardware_nonref_keep_every',True),('hardware_cache_vendor_verified',False),
                            ('hardware_output_cache_enabled',False),('hardware_cache_sync_errors',1)):
            changed=[dict(row,player=dict(row['player'])) for row in rows];changed[5]['player'][field]=value
            self.assertFalse(cached_retention_verified(changed,metrics(changed)['playing'],True))

    def test_worker_cache_retention_is_bound_to_existing_snapshot(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        worker=(base/'client/hardware_worker.cpp').read_text(encoding='utf-8')
        section=worker.split('p011_hw::RetentionCacheEvidence retention{',1)[1].split('#endif',1)[0]
        for key in ('cache_vendor_verified','cache_changed_allocations','cache_active','cache_read_begin',
                    'cache_fallback_active','cache_sync_errors','cache_ownership_errors'):
            self.assertIn(key,section)
        self.assertIn('encoded_trace.cached_output_ready.store(retention.ready())',section)
        self.assertIn('t.cached_output_ready.store(false);t.select_production_policy()',worker)
        self.assertIn('caps_width==1920&&caps_height==1080',worker)
        self.assertIn('hardware_cached_retention_active',(base/'client/player_v2.cpp').read_text(encoding='utf-8'))
    def test_stock_probe_35_and_private_channel(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/'probes/gst_decode_probe.py').read_text()
        ast.parse(source,feature_version=(3,5));self.assertIn('ssl-strict=true',source);self.assertIn('os.write(report_fd',source);self.assertIn('fakesink',source)
    def test_software_probe_python35(self):
        source=(pathlib.Path(__file__).resolve().parents[1]/'probes/mpv_decode_probe.py').read_text()
        ast.parse(source,feature_version=(3,5));self.assertIn("'vo':'null'",source);self.assertIn("'audio':'no'",source)
    def test_explicit_guard_before_any_io(self):
        for q in (-1,0,True,65536,'80'):
            with self.assertRaises(ValueError):build(pathlib.Path('not-accessed'),client=True,automated=True,player_protocol=2,benchmark_quality=q)
        with self.assertRaises(ValueError):build(pathlib.Path('not-accessed'),client=True,automated=False,player_protocol=2,benchmark_quality=80)
    def test_seek_probe_is_explicit_and_bounded(self):
        for value in (True,'true',1):
            with self.assertRaises(ValueError):build(pathlib.Path('not-accessed'),benchmark_seek=value)
        source=(pathlib.Path(__file__).resolve().parents[1]/'client/BiliPerformance.qml').read_text(encoding='utf-8')
        self.assertIn('property bool seekProbe:false',source)
        self.assertIn('p.scrub_actions>=1',source)
        self.assertIn('p.hardware_backend&&p.hardware_verified',source)
    def test_hardware_network_rings_are_bounded_and_not_disk_caches(self):
        # Configuration policy only; not proof of vendor-plugin availability.
        source=(pathlib.Path(__file__).resolve().parents[1]/'client/hardware_worker.cpp').read_text(encoding='utf-8')
        rings=re.findall(r'queue2 name=(vnet|anet) ring-buffer-max-size=([0-9]+) max-size-bytes=([0-9]+)',source)
        self.assertEqual(rings,[('vnet','8388608','4194304'),('anet','2097152','1048576')])
        self.assertEqual(sum(int(row[1]) for row in rings),10*1024*1024)
        self.assertNotIn('temp-template=',source)
        self.assertIn('omxh264dec name=dec',source)
        self.assertIn('GST_SEEK_FLAG_FLUSH|GST_SEEK_FLAG_ACCURATE',source)

if __name__=='__main__':unittest.main()
