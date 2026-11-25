import json,pathlib,tempfile,unittest
from unittest.mock import Mock,patch
import client_oneclick

class ObserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.adb=Mock(out=pathlib.Path(self.tmp.name),sequence=1);self.report={}
    def tearDown(self):self.tmp.cleanup()
    def status(self,**kw):
        d=dict(host_exit=None,remote_exit=None,timeout=True);d.update(kw)
        (self.adb.out/'01-observe.status.json').write_text(json.dumps(d))
    def test_one_timeout_is_read_only_and_recorded(self):
        self.status()
        with patch.object(client_oneclick,'command',side_effect=[RuntimeError('observe failed'),"RESULT={'complete':False}"]) as c:
            self.assertFalse(client_oneclick.observe_status(self.adb,{},self.report)['complete'])
            self.assertEqual(self.report['observation_timeouts'],1)
            self.assertEqual([v.args[2:] for v in c.call_args_list],[('observe',['status']),('observe-retry',['status'])])
    def test_second_timeout_not_retried(self):
        self.status();self.report['observation_timeouts']=1
        with patch.object(client_oneclick,'command',side_effect=RuntimeError('fail')) as c:
            with self.assertRaises(RuntimeError):client_oneclick.observe_status(self.adb,{},self.report)
            self.assertEqual(c.call_count,1)
    def test_remote_failure_not_retried(self):
        self.status(host_exit=0,remote_exit=1,timeout=False)
        with patch.object(client_oneclick,'command',side_effect=RuntimeError('fail')) as c:
            with self.assertRaises(RuntimeError):client_oneclick.observe_status(self.adb,{},self.report)
            self.assertEqual(c.call_count,1)
    def test_invalid_response_fails_immediately(self):
        with patch.object(client_oneclick,'command',return_value='invalid') as c:
            with self.assertRaises(ValueError):client_oneclick.observe_status(self.adb,{},self.report)
            self.assertEqual(c.call_count,1)
    def test_retry_failure_propagates(self):
        self.status()
        with patch.object(client_oneclick,'command',side_effect=RuntimeError('fail')) as c:
            with self.assertRaises(RuntimeError):client_oneclick.observe_status(self.adb,{},self.report)
            self.assertEqual(c.call_count,2)

if __name__=='__main__':unittest.main()
