import ast,unittest
from screen_rate_trial import PAYLOAD,FRAMES,parse_output,assess


class ScreenRateTests(unittest.TestCase):
    def log(self,count=FRAMES):
        lines=['/GstPipeline:p/GstIdentity:p011_count.GstPad:sink: caps = video/x-raw, width=(int)480, height=(int)270, framerate=(fraction)60/1']
        for i in range(count):
            n=i*1000000000//60;s,n=divmod(n,1000000000)
            lines.append('/GstPipeline:p/GstIdentity:p011_count: last-message = chain (bytes, pts: 0:00:%02d.%09d)'%(s,n))
        lines+=['rendered: 870, dropped: 0, current: 60.00, average: 60.00']*20+['Got EOS from element p']
        return '\n'.join(lines).encode()

    def test_target_python35_no_window_or_system_writes(self):
        ast.parse(PAYLOAD,feature_version=(3,5))
        for v in ('video-sink=fakesink','text-overlay=false','sync=true','child.communicate(timeout=24)','any_vsp()','RLIMIT_CORE','GST_REGISTRY='):
            self.assertIn(v,PAYLOAD)
        for v in ('killall','reboot','/sys/','gst_element_set_state'):
            self.assertNotIn(v,PAYLOAD)

    def test_complete_raw_output_is_preserved_separately(self):
        self.assertIn('stdout_raw=o,stderr_raw=e,selected_stdout=selected',PAYLOAD)
        self.assertIn('stdout_prefix_only=False,stderr_prefix_only=False',PAYLOAD)
        self.assertIn("if len(o)>8388608 or len(e)>8388608:",PAYLOAD)
        self.assertNotIn('stdout_raw=o[:',PAYLOAD)

    def test_complete_ordered_frames_and_caps_required(self):
        r=parse_output(self.log(),480,270)
        self.assertTrue(r['timestamps_complete']);self.assertTrue(r['caps_verified']);self.assertTrue(r['eos'])
        self.assertEqual(r['decoded_frames'],900)
        self.assertFalse(parse_output(self.log(899),480,270)['timestamps_complete'])
        self.assertFalse(parse_output(self.log(),640,360)['caps_verified'])

    def test_duplicate_pts_or_missing_timestamp_not_accepted(self):
        body=self.log().replace(b'0:00:00.016666666',b'0:00:00.000000000')
        self.assertFalse(parse_output(body,480,270)['timestamps_complete'])
        with self.assertRaises(ValueError):parse_output(self.log().replace(b'pts:',b'wrong:'),480,270)
        with self.assertRaises(ValueError):parse_output(b'x'*1048577,480,270)

    def test_rate_alone_cannot_be_a_decoder_pass(self):
        r=dict(exit=0,timeout=False,forced=False,sampling_errors=0,sample_count=70,elapsed_seconds=15.1,pipeline=parse_output(self.log(),480,270))
        flags=('stock_unchanged','vendor_unchanged','decoder_library_observed','vsp_fd_observed','decoder_idle_after','sampler_joined','temporary_directory_removed')
        r.update({k:True for k in flags});self.assertTrue(assess(r))
        for k in flags:
            bad=dict(r);bad[k]=False;self.assertFalse(assess(bad),k)
        for k,v in [('exit',1),('timeout',True),('forced',True),('sample_count',0),('sampling_errors',1),('elapsed_seconds',22)]:
            self.assertFalse(assess(dict(r,**{k:v})),k)


if __name__=='__main__':unittest.main()
