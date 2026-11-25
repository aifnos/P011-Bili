"""Source-policy checks only; Gst query semantics run in the ARM preflight."""
import pathlib,unittest

BASE=pathlib.Path(__file__).resolve().parents[1]
class HardwareAllocationTests(unittest.TestCase):
    def setUp(self):
        self.header=(BASE/'client/hardware_allocation.hpp').read_text()
        self.worker=(BASE/'client/hardware_worker.cpp').read_text()
    def test_114_public_query_api_not_new_signal(self):
        self.assertIn('GST_PAD_PROBE_TYPE_QUERY_DOWNSTREAM|GST_PAD_PROBE_TYPE_PUSH',self.header)
        self.assertIn('gst_query_add_allocation_meta(query,GST_VIDEO_META_API_TYPE,nullptr)',self.header)
        self.assertIn('return GST_PAD_PROBE_HANDLED',self.header)
        self.assertNotIn('g_signal_connect',self.header)
    def test_only_cpu_mappable_formats_no_foreign_pool(self):
        self.assertIn('GST_CAPS_FEATURE_MEMORY_SYSTEM_MEMORY',self.header)
        self.assertIn('format!=GST_VIDEO_FORMAT_NV12&&format!=GST_VIDEO_FORMAT_I420',self.header)
        self.assertNotIn('gst_query_add_allocation_pool',self.header)
        self.assertNotIn('gst_query_add_allocation_param',self.header)
    def test_query_lifetime_and_attachment_before_running(self):
        self.assertLess(self.worker.index('p011_hw::VideoAllocation allocation'),self.worker.index('Pipeline p;'))
        self.assertLess(self.worker.index('allocation.attach(p.sink)'),self.worker.index('gst_element_set_state(p.pipe,GST_STATE_PAUSED)'))
    def test_mapping_uses_frame_metadata_not_caps_stride(self):
        self.assertIn('gst_video_frame_map(&mapped,&info,buffer,GST_MAP_READ)',self.worker)
        self.assertIn('GST_VIDEO_FRAME_COMP_STRIDE(&mapped,component)',self.worker)
        self.assertIn('GST_VIDEO_FRAME_COMP_DATA(&mapped,component)',self.worker)
        self.assertIn('gst_memory_is_type(memory,"openmax")',self.worker)
    def test_runtime_preflight_checks_query_semantics(self):
        self.assertIn('p011_hw::allocation_selftest()',self.worker)
        self.assertIn('allocation_checks==6',self.worker)
        self.assertIn('gst_query_get_n_allocation_metas(query)==1',self.header)
        self.assertIn('memory:GLMemory',self.header)
        check=(BASE/'host/client_native_check.py').read_text()
        self.assertIn("hardware_env['GST_REGISTRY']=ROOT+'/gst-hw-preflight-registry.bin'",check)
    def test_input_queue_telemetry_does_not_alter_limits_or_qos(self):
        self.assertIn('queue name=vin max-size-buffers=8 max-size-bytes=4194304 max-size-time=2000000000',self.worker)
        self.assertIn('g_object_get(p.video_input,"current-level-buffers"',self.worker)
        self.assertIn('g_object_get(p.video_network,"current-level-bytes"',self.worker)
        self.assertIn('sync=true qos=true max-lateness=40000000',self.worker)
        self.assertIn('for(auto*p:{sink,audio,vol,decoder,video_input,video_network,audio_network,audio_input})',self.worker)
        self.assertLess(self.worker.index('const bool cached_input='),self.worker.index('video.clear()'))
        self.assertIn('status["cached_media"]=cached_input;',self.worker)
        self.assertIn('audio_ahead>=GST_SECOND||audio_download.complete.load()',self.worker)
        self.assertIn('video_download.complete.load()',self.worker)
        self.assertIn('t==GST_EVENT_FLUSH_START)s.complete.store(false)',self.worker)

if __name__=='__main__':unittest.main()
