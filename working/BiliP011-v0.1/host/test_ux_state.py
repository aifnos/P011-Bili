"""Private persistence and two-phase stream handoff. PC fixtures, never ADB."""
import ast
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from test_client import service,BASE
from library import Library

VIDEO=dict(kind='video',bvid='BV1Da411Y7U4',cid='1',title='合成测试',up='测试 UP')

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.library=Library(str(self.root/'library'))
    def tearDown(self):self.tmp.cleanup()
    def test_record_resume_missing_optional_ids(self):
        self.library.record(VIDEO,32,120)
        self.assertEqual(self.library.resume(VIDEO),32)
        self.assertEqual(Library(str(self.root/'library')).resume(VIDEO),32)
        self.library.record(VIDEO,118,120);self.assertEqual(self.library.resume(VIDEO),0)
    def test_no_credentials_or_stream_addresses_persist(self):
        self.library.record(dict(VIDEO,video='PRIVATE_URL',cookies='PRIVATE_COOKIE',queue=['PRIVATE']),20,90)
        self.assertNotIn('PRIVATE',pathlib.Path(self.library.path).read_text())
        self.assertEqual(len(list((self.root/'library').iterdir())),1)
    def test_mru_dedup_and_bounds(self):
        for n in range(70):self.library.record(dict(VIDEO,cid=str(n)),20,90)
        self.library.record(dict(VIDEO,cid='10'),42,90)
        rows=self.library.load()['history'];self.assertEqual(len(rows),60);self.assertEqual(rows[0]['cid'],'10')
        for n in range(30):self.library.search('中文 '+str(n))
        self.library.search('中文 15');rows=self.library.load()['searches'];self.assertEqual(len(rows),20);self.assertEqual(rows[0],'中文 15')
    def test_clear_is_local_and_scoped(self):
        self.library.record(VIDEO,20,90);self.library.search('电影');self.library.clear('searches')
        self.assertEqual(len(self.library.load()['history']),1)
        self.library.clear('history');self.assertEqual(self.library.load(),dict(history=[],searches=[]))
        with self.assertRaises(ValueError):self.library.clear('../account')
    def test_invalid_values_never_create_history(self):
        for position in (True,float('nan'),float('inf'),-1,'20'):
            with self.subTest(position=position),self.assertRaises(ValueError):self.library.record(VIDEO,position,120)
        self.library.record(VIDEO,1,120);self.assertFalse(self.library.load()['history'])
    def test_unknown_existing_file_preserved(self):
        path=pathlib.Path(self.library.path);path.write_text('{"schema":true,"history":[],"searches":[]}');os.chmod(path,0o600)
        before=path.read_bytes()
        with self.assertRaises(ValueError):self.library.record(VIDEO,20,90)
        self.assertEqual(path.read_bytes(),before)
    def test_bad_input_and_version_compatibility(self):
        for value in ('','x'*161,None):
            with self.assertRaises(ValueError):self.library.search(value)
        for name in ('library.py','story.py','story_cache.py','service.py'):ast.parse((BASE/'client'/name).read_text(encoding='utf-8'),feature_version=(3,5))

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.backend=service.Backend(str(self.root),'','',str(self.root/'account'),{},helper=lambda op,a:dict(video='https://example.bilivideo.com/private',audio='',codec=7,quality=16,qualities=[]))
        self.backend.protocol=2;self.backend.play_generation=4;self.started=[]
        self.backend.start_danmaku=lambda p,g,a,s:self.started.append((a['cid'],s))
    def tearDown(self):self.backend.player=None;self.backend.close();self.tmp.cleanup()
    def run_events(self,events):
        class Player:
            def poll(self):return None
        p=Player();p.stdout=io.BytesIO(b''.join((json.dumps(row)+'\n').encode() for row in events));p.stdin=io.BytesIO()
        self.backend.player=p
        args=dict(VIDEO,queue=[dict(VIDEO,cid=str(n)) for n in (1,2,3)],queue_index=0)
        self.backend.player_events(p,4,args)
        return [json.loads(row) for row in p.stdin.getvalue().splitlines()]
    def test_pending_switch_cannot_advance_or_start_danmaku(self):
        rows=self.run_events([dict(action='capabilities',switch_ack=True),dict(action='next',seq=1),dict(action='next',seq=2)])
        self.assertTrue(rows[0]['ok']);self.assertEqual(rows[1]['error'],'BUSY');self.assertEqual(self.started,[])
    def test_failed_candidate_retains_previous_queue_index(self):
        rows=self.run_events([dict(action='capabilities',switch_ack=True),dict(action='next',seq=1),dict(action='stream_result',seq=1,ok=False),dict(action='next',seq=2),dict(action='stream_result',seq=2,ok=True),dict(action='next',seq=3)])
        self.assertEqual([r['queue_index'] for r in rows],[1,1,2]);self.assertEqual(self.started,[('2',2)])
    def test_stale_and_nonboolean_ack_cannot_commit(self):
        rows=self.run_events([dict(action='capabilities',switch_ack=True),dict(action='next',seq=1),dict(action='stream_result',seq=9,ok=True),dict(action='stream_result',seq=1,ok=1),dict(action='next',seq=2)])
        self.assertEqual(rows[-1]['error'],'BUSY');self.assertFalse(self.started)
    def test_legacy_bridge_is_preserved(self):
        rows=self.run_events([dict(action='next',seq=1),dict(action='next',seq=2)])
        self.assertEqual([r['queue_index'] for r in rows],[1,2]);self.assertEqual(self.started,[('2',2),('3',3)])
    def test_library_watch_requires_matching_loaded_not_pending(self):
        b=self.backend;b.library=Library(str(self.root/'library'));b.play_item=(4,2,VIDEO)
        state=dict(generation=4,serial=2,loaded=True,position=20,duration=90,switch_pending=False)
        for patch in (dict(serial=1),dict(generation=3),dict(loaded=False),dict(switch_pending=True)):
            (self.root/'watch-state.json').write_text(json.dumps(dict(state,**patch)));b.remember_playback(True)
            self.assertEqual(b.library.load()['history'],[])
        (self.root/'watch-state.json').write_text(json.dumps(state));b.remember_playback(True)
        self.assertEqual(b.library.resume(VIDEO),20)
    def test_play_metadata_normalization_is_bounded(self):
        args=service.safe_args('play',dict(VIDEO,queue=[dict(VIDEO,part_title='P1',video='private')],resume=False))
        self.assertFalse(args['resume']);self.assertEqual(args['queue'][0]['part_title'],'P1');self.assertNotIn('video',args['queue'][0])
        with self.assertRaises(service.Failure):service.safe_args('play',dict(VIDEO,resume=1))
    def test_completed_player_cannot_resurrect_cleared_history(self):
        b=self.backend;b.library=Library(str(self.root/'library'));b.play_item=(4,2,VIDEO)
        state=dict(generation=4,serial=2,loaded=True,position=20,duration=90,switch_pending=False)
        (self.root/'watch-state.json').write_text(json.dumps(state))
        class Child:
            stdin=io.BytesIO()
            def wait(self):return 0
        b.player=Child();b.reap_player(b.player)
        self.assertEqual(b.library.resume(VIDEO),20);self.assertIsNone(b.play_item)
        b.library.clear('history');b.remember_playback(True)
        self.assertEqual(b.library.load()['history'],[])

class BundleBoundaryTests(unittest.TestCase):
    def test_verified_legacy_player_cannot_enable_new_resume(self):
        from build_awake_trial import build
        # Exact-build validation has its own tests. This boundary must not
        # depend on a local binary being rebuilt concurrently with unit tests.
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);media=base/'out/media-fixture';(media/'bin').mkdir(parents=True)
            (media/'bin/bili-player').write_bytes(b'legacy');(base/'out/bili-player').write_bytes(b'verified-current')
            with patch('build_awake_trial.BASE',base),patch('strip_player_artifact.validate_strip_player') as validate:
                with self.assertRaisesRegex(ValueError,'UX state player differs'):
                    build(media,client=True,player_protocol=2,ux_state=True)
                validate.assert_called_once_with(base)
    def test_ux_requires_explicit_protocol_two(self):
        from build_awake_trial import build
        for args in (dict(ux_state=1),dict(ux_state=True),dict(ux_state=True,client=True)):
            with self.assertRaisesRegex(ValueError,'UX state requires'):
                build(BASE/'out/media-e4ccc8fa53004efb',**args)

if __name__=='__main__':unittest.main()
