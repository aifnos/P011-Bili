"""No network or account writes; synthetic native time and canonical IDs."""
import ast
import copy
import tempfile
import unittest
from unittest.mock import patch
from test_client import service,BASE
from media_actions import WatchClock

BV='BV1Da411Y7U4'
def sample(p,**kw):
    s=dict(position=p,duration=120.,loaded=True,paused=False,idle=False,rate=1.,switch_pending=False,finished=False,completed=False)
    s.update(kw);return s

class ClockTests(unittest.TestCase):
    def test_no_report_without_actual_progress(self):
        c=WatchClock(0,1000)
        for i in range(25):self.assertIsNone(c.sample(sample(0),i))
        self.assertEqual(c.real,0);self.assertFalse(c.ever)
    def test_start_pause_resume_and_periodic(self):
        c=WatchClock(0,1000);self.assertIsNone(c.sample(sample(0),0))
        self.assertEqual(c.sample(sample(1),1)['play_type'],3)
        for i in range(2,16):self.assertIsNone(c.sample(sample(i),i))
        r=c.sample(sample(16),16);self.assertEqual((r['play_type'],r['realtime'],r['real_played_time']),(0,16,16))
        self.assertEqual(c.sample(sample(16,paused=True),17)['play_type'],2)
        self.assertIsNone(c.sample(sample(16,paused=True),25));self.assertEqual(c.real,16)
        self.assertIsNone(c.sample(sample(16),26));self.assertEqual(c.sample(sample(17),27)['play_type'],3)
    def test_double_speed_wall_and_media_separate(self):
        c=WatchClock(0,1000);c.sample(sample(0,rate=2),0)
        for i in range(1,17):r=c.sample(sample(i*2,rate=2),i)
        self.assertEqual(r['real_played_time'],16);self.assertEqual(r['realtime'],32)
    def test_seek_does_not_invent_watching(self):
        c=WatchClock(0,1000);c.sample(sample(0),0);c.sample(sample(1),1)
        r=c.sample(sample(100),2);self.assertEqual(r['play_type'],1);self.assertEqual(c.real,1)
        self.assertEqual(r['played_time'],100);c.sample(sample(99),3);self.assertEqual(c.real,1)
    def test_gap_buffer_switch_and_invalid_not_counted(self):
        c=WatchClock(0,1000);c.sample(sample(0),0);c.sample(sample(1),1)
        c.sample(sample(21),21);self.assertEqual(c.real,1)
        c.sample(sample(22,switch_pending=True),22);c.sample(sample(90),23);self.assertEqual(c.real,1)
        for p in (float('nan'),float('inf'),-1,500):self.assertIsNone(c.sample(sample(p),24))
    def test_only_native_eof_marks_finished(self):
        c=WatchClock(0,1000);c.sample(sample(0),0);c.sample(sample(1),1)
        self.assertNotEqual(c.sample(sample(120,finished=True),2)['played_time'],-1)
        r=c.sample(sample(120,completed=True,finished=True),3);self.assertEqual((r['play_type'],r['played_time']),(4,-1))
        self.assertIsNone(c.sample(sample(120,completed=True,finished=True),4))

class MediaActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.calls=[]
        self.b=service.Backend(self.tmp.name,'','',self.tmp.name,{},helper=self.fake)
    def tearDown(self):self.b.close();self.tmp.cleanup()
    def fake(self,op,a):
        self.calls.append((op,copy.deepcopy(a)))
        if op=='media_context':return {'aid':'2','cid':'1','duration':120,'ordinary':True}
        if op=='status':return {'logged_in':True}
        if op in ('danmaku_send','watch_heartbeat'):return {'confirmed':True,'visible':False}
        raise service.Failure('BAD_INPUT')
    def call(self,op,a=None):return self.b.dispatch(op,service.safe_args(op,a or {}),self.b.qr_generation)
    def context(self):return self.call('danmaku_context',dict(bvid=BV,cid='1',position=30))['intent']
    def test_message_nonce_exact_video_part_position_one_use(self):
        a=dict(bvid=BV,cid='1',position=30,intent=self.context(),mode=1,message='合成弹幕')
        self.assertTrue(self.call('danmaku_send',a)['confirmed']);self.assertFalse(self.call('cloud_state')['enabled'])
        with self.assertRaises(service.Failure):self.call('danmaku_send',a)
        for key,value in [('bvid','BV1gi4y1V7Xx'),('cid','2'),('position',31)]:
            changed=dict(a,intent=self.context());changed[key]=value
            with self.assertRaises(service.Failure):self.call('danmaku_send',changed)
        self.assertEqual(sum(op=='danmaku_send' for op,_ in self.calls),1)
    def test_account_change_and_expiry(self):
        a=dict(bvid=BV,cid='1',position=30,intent=self.context(),mode=1,message='合成弹幕');self.b.qr_generation+=1
        with self.assertRaises(service.Failure):self.call('danmaku_send',a)
        a['intent']=self.context()
        with patch('media_actions.time.monotonic',return_value=10**9):
            with self.assertRaises(service.Failure):self.call('danmaku_send',a)
    def test_reject_scripts_types_colors_and_invalid_text(self):
        for mode in (0,6,7,8,9,True,'1'):
            with self.assertRaises(service.Failure):service.safe_args('danmaku_send',dict(bvid=BV,cid='1',position=0,intent='f'*32,mode=mode,message='x'))
        for text in ('','  ','a'*101,'bad\ntext',None):
            with self.assertRaises(service.Failure):service.safe_args('danmaku_send',dict(bvid=BV,cid='1',position=0,intent='f'*32,mode=1,message=text))
        for p in (True,-1,float('nan'),float('inf'),86401):
            with self.assertRaises(service.Failure):service.safe_args('danmaku_context',dict(bvid=BV,cid='1',position=p))
        with self.assertRaises(service.Failure):self.call('danmaku_context',dict(bvid=BV,cid='1',position=121))
    def test_uncertain_not_retried(self):
        a=dict(bvid=BV,cid='1',position=30,intent=self.context(),mode=1,message='x')
        self.b.helper_override=lambda op,a:(_ for _ in ()).throw(service.Failure('HELPER_TIMEOUT'))
        with self.assertRaises(service.Failure) as e:self.call('danmaku_send',a)
        self.assertEqual(e.exception.error,'ACTION_UNCONFIRMED')
        with self.assertRaises(service.Failure) as e:self.call('danmaku_send',a)
        self.assertEqual(e.exception.error,'ACTION_EXPIRED')
    def test_automation_all_write_paths_blocked(self):
        nonce=self.context();cloud=self.call('cloud_state')['intent'];self.b.automation=True;before=len(self.calls)
        for op,a in [('danmaku_send',dict(bvid=BV,cid='1',position=30,intent=nonce,mode=1,message='x')),('cloud_enable',dict(value=True,intent=cloud))]:
            with self.assertRaises(service.Failure) as e:self.call(op,a)
            self.assertEqual(e.exception.error,'ACTION_DISABLED')
        for op in ('danmaku_send','watch_heartbeat'):
            with self.assertRaises(service.Failure):self.b.helper(op,{})
        self.b.media_actions.enabled=True;self.b.media_actions.observe(sample(10))
        self.assertEqual(len(self.calls),before)
    def test_optin_account_bound_and_session_only(self):
        self.assertFalse(self.call('cloud_state')['enabled'])
        with patch('media_actions.threading.Thread') as worker:
            self.assertTrue(self.call('cloud_enable',dict(intent=self.call('cloud_state')['intent'],value=True))['enabled']);self.assertTrue(worker.called)
            self.b.qr_generation+=1;self.assertFalse(self.call('cloud_state')['enabled'])
        self.assertFalse(self.b.media_actions.enabled)
    def test_report_derived_only_from_bound_native_snapshot(self):
        actions=self.b.media_actions;actions.enabled=True;actions.generation=0;self.b.play_generation=1
        self.b.play_item=(1,1,dict(bvid=BV,cid='1',kind='video'))
        with patch('media_actions.time.monotonic',return_value=0):actions.observe(dict(sample(0),generation=1,serial=1))
        with patch('media_actions.time.monotonic',return_value=1):actions.observe(dict(sample(1),generation=1,serial=2))
        self.assertEqual(actions.confirmed,0)
        with patch('media_actions.time.monotonic',return_value=2):actions.observe(dict(sample(2),generation=1,serial=1))
        self.assertEqual(actions.confirmed,1);self.assertEqual(self.calls[-1][1]['played_time'],2)
        self.assertNotIn('watch_heartbeat',service.PUBLIC_OPS);self.assertNotIn('media_context',service.PUBLIC_OPS)
    def test_python35(self):ast.parse((BASE/'client/media_actions.py').read_text(encoding='utf-8'),feature_version=(3,5))

if __name__=='__main__':unittest.main()
