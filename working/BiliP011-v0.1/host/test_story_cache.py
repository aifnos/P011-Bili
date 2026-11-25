"""PC-only deterministic cache/lifecycle tests; no service URLs or account."""
import pathlib
import sys
import tempfile
import threading
import time
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'client'))
from story_cache import StoryCache, identity, purge, can_prefetch

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name)
        self.now=[100.];self.download_gate=threading.Event();self.download_gate.set();self.c=None
        self.args=dict(kind='video',bvid='BV1Da411Y7U4',cid='1',quality=0,codec=0)
    def tearDown(self):
        if self.c:self.c.close()
        self.temp.cleanup()
    def make(self,download=None,ready=lambda:True):
        def resolve(a,c):return dict(a),dict(video='https://example.bilivideo.com/v',audio='https://example.bilivideo.com/a')
        def fetch(a,c):
            while not self.download_gate.wait(.01):
                if c.is_set():return {'cached':False}
            for name in ('v','a'):(self.root/'preload'/(a['key']+'-'+name+'.m4s')).write_bytes(b'fixture')
            return dict(cached=True,bytes=14)
        self.c=StoryCache(str(self.root),resolve,download or fetch,ready,lambda:self.now[0]);return self.c
    def wait(self,predicate):
        until=time.monotonic()+2
        while time.monotonic()<until:
            if predicate():return
            time.sleep(.01)
        self.fail('bounded worker did not reach state')
    def test_full_cache_private_hit_and_cleanup(self):
        c=self.make();c.schedule(self.args);self.wait(lambda:c.stats['completed']==1)
        args,data=c.take(self.args);self.assertTrue(data['video'].startswith('file://'));self.assertEqual(c.stats['media_hits'],1)
        self.assertEqual(len(list((self.root/'preload').iterdir())),2)
        self.assertTrue(c.close()['worker_stopped']);self.assertEqual(list((self.root/'preload').iterdir()),[])
    def test_metadata_ready_without_blocking_download(self):
        self.download_gate.clear();c=self.make();c.schedule(self.args);self.wait(lambda:c.stats['resolved']==1)
        self.assertTrue(c.take(self.args)[1]['video'].startswith('https://'));self.assertEqual(c.stats['metadata_hits'],1)
    def test_expiry_and_quality_key(self):
        c=self.make();c.schedule(self.args);self.wait(lambda:c.stats['completed']==1)
        self.assertIsNone(c.take(dict(self.args,quality=80)));self.now[0]+=91;self.assertIsNone(c.take(self.args))
        c.schedule(self.args);self.wait(lambda:c.stats['completed']==2);self.assertEqual(len(list((self.root/'preload').iterdir())),2)
    def test_four_entry_bound(self):
        c=self.make()
        for n in range(8):
            c.schedule(dict(self.args,cid=str(n)));self.wait(lambda:c.stats['completed']==n+1)
        self.assertEqual(len(c.rows),4);self.assertEqual(len(c.files),4)
        self.assertLessEqual(len(list((self.root/'preload').iterdir())),8)
    def test_replacement_cancels_inflight(self):
        self.download_gate.clear();c=self.make();c.schedule(self.args);self.wait(lambda:c.stats['resolved']==1)
        c.schedule(dict(self.args,cid='2'));self.wait(lambda:c.stats['resolved']==2);self.download_gate.set()
        self.wait(lambda:c.stats['completed']==1);self.assertGreaterEqual(c.stats['canceled'],1)
    def test_exit_before_stable_playback(self):
        c=self.make(ready=lambda:False);c.schedule(self.args);self.assertTrue(c.close()['worker_stopped']);self.assertEqual(c.stats['resolved'],0)
    def test_download_failure_falls_back_to_metadata(self):
        c=self.make(download=lambda a,c:dict(cached=False));c.schedule(self.args);self.wait(lambda:c.stats['resolved']==1)
        self.assertTrue(c.take(self.args)[1]['video'].startswith('https://'))
    def test_guardian_purge_is_narrow(self):
        p=self.root/'preload';p.mkdir();(p/('a'*16+'-v.m4s.part')).write_bytes(b'temp')
        self.assertEqual(purge(str(self.root)),1)
        (p/'keep-user-data.txt').write_text('keep')
        with self.assertRaises(ValueError):purge(str(self.root))
        self.assertTrue((p/'keep-user-data.txt').is_file())
    def test_identity_does_not_include_title(self):
        self.assertEqual(identity(self.args),identity(dict(self.args,title='Private display text')))
    def test_selected_file_is_pinned_during_next_eviction(self):
        c=self.make()
        for n in range(4):
            c.schedule(dict(self.args,cid=str(n)));self.wait(lambda:c.stats['completed']==n+1)
        c.take(dict(self.args,cid='0'));c.schedule(dict(self.args,cid='4'));self.wait(lambda:c.stats['completed']==5)
        self.assertIsNotNone(c.take(dict(self.args,cid='0')))
        self.assertIsNone(c.take(dict(self.args,cid='1')))
    def test_legacy_player_is_not_given_cached_files(self):
        self.assertFalse(can_prefetch(dict(active=True,position=10)))
        self.assertFalse(can_prefetch(dict(video_seek_actions=True,active=True,position=10)))
        self.assertFalse(can_prefetch(dict(video_seek_actions=0,active=True,position=1)))
        self.assertFalse(can_prefetch(dict(video_seek_actions=0,active=False,position=10)))
        self.assertFalse(can_prefetch(dict(video_seek_actions=0,active=True,switch_pending=True,position=10)))
        self.assertTrue(can_prefetch(dict(video_seek_actions=0,active=True,position=10)))
    def test_metadata_ahead_does_not_download_before_stability(self):
        calls=[];stable=[False]
        def resolve(a,c):calls.append('resolve');return a,dict(video='https://example.bilivideo.com/v')
        def download(a,c):calls.append('download');return dict(cached=False)
        self.c=StoryCache(str(self.root),resolve,download,lambda:stable[0],metadata_ready=lambda:True)
        self.c.schedule_provider(lambda c:dict(self.args));self.wait(lambda:'resolve' in calls)
        self.assertNotIn('download',calls);self.assertIsNotNone(self.c.take(self.args))
        stable[0]=True;self.wait(lambda:'download' in calls)
    def test_provider_cancellation_is_observed(self):
        started=threading.Event();ended=threading.Event();c=self.make()
        def provider(cancel):started.set();cancel.wait(1);ended.set();return dict(self.args)
        c.schedule_provider(provider);self.assertTrue(started.wait(1));c.cancel_pending();self.assertTrue(ended.wait(1))
        self.assertTrue(c.close()['worker_stopped']);self.assertEqual(c.stats['resolved'],0)
    def test_metadata_capability_and_startup_threshold(self):
        state=dict(video_seek_actions=0,active=True,position=.5)
        self.assertTrue(can_prefetch(state,True));self.assertFalse(can_prefetch(state))
        self.assertFalse(can_prefetch(dict(state,switch_pending=True),True))

    def test_two_step_priority_and_reuse(self):
        c=self.make();rows=[dict(self.args,cid=str(i)) for i in (1,2)]
        c.schedule_provider(lambda cancel:rows);self.wait(lambda:c.stats['completed']==2)
        self.assertEqual([row['args']['cid'] for row in c.rows.values()],['1','2'])
        c.take(rows[0]);c.schedule_provider(lambda cancel:[rows[1],dict(self.args,cid='3')])
        self.wait(lambda:c.stats['completed']==3);self.assertEqual(c.stats['reused'],1)
        self.assertEqual(c.stats['resolved'],3)

    def test_low_headroom_yields_inflight_then_resumes(self):
        safe=[True];started=threading.Event();released=threading.Event();calls=[]
        def download(args,cancel):
            calls.append(args['key']);started.set()
            if len(calls)==1:
                while not cancel.is_set():time.sleep(.01)
                released.set();raise ValueError('yield')
            return dict(cached=False)
        c=self.make(download=download,ready=lambda:safe[0]);c.schedule(self.args)
        self.assertTrue(started.wait(1));safe[0]=False;self.assertTrue(released.wait(1))
        self.wait(lambda:c.stats['yields']==1);time.sleep(.03);self.assertEqual(len(calls),1)
        safe[0]=True;self.wait(lambda:len(calls)==2);self.assertEqual(c.stats['failed'],0)

    def test_new_player_needs_actual_buffer_headroom(self):
        s=dict(video_seek_actions=0,active=True,position=4,prefix_cache_capable=True)
        self.assertTrue(can_prefetch(s,True));self.assertFalse(can_prefetch(s))
        self.assertTrue(can_prefetch(dict(s,prefetch_safe=True)))
        self.assertFalse(can_prefetch(dict(s,prefetch_safe=True,switch_pending=True)))
        self.assertFalse(can_prefetch(dict(s,prefetch_safe=True,performance_limited=True)))

    def test_failed_first_does_not_skip_second(self):
        calls=[]
        def fetch(a,c):calls.append(a['key']);raise ValueError('unavailable')
        c=self.make(download=fetch);c.schedule_provider(lambda c:[self.args,dict(self.args,cid='2')])
        self.wait(lambda:c.stats['failed']==2);self.assertEqual(len(calls),2)
        self.assertFalse(list((self.root/'preload').iterdir()))

if __name__=='__main__':unittest.main()
