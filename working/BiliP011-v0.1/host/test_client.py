"""Host-only security/normalization/race tests. No ADB, no live login."""
import ast
import http.client
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import zlib
from unittest.mock import Mock, patch

BASE = pathlib.Path(__file__).resolve().parents[1]
NATIVE = BASE.parents[1]/'working/ToolboxNext-v0.5.1-native'
sys.path.insert(0, str(NATIVE/'runtime'))
spec = importlib.util.spec_from_file_location('bili_service', BASE/'client/service.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def fixture(op, args):
    video = {'title':'P011 中文视频测试', 'up':'示例 UP', 'bvid':'BV1Da411Y7U4', 'aid':'123', 'kind':'video',
             'cover':'https://i0.hdslb.com/bfs/archive/example.jpg', 'duration':'02:00'}
    if op in ('recommend', 'following', 'search', 'bangumi'):
        rows = [dict(video, title='第 %d 个长标题 · 中文搜索和触摸测试' % i) for i in range(1,8)]
        if op == 'bangumi' or args.get('type') == 'media_bangumi':
            for row in rows: row.update(kind='season', season='1', bvid='', title='番剧 · 选集测试')
        return {'items':rows, 'more':True, 'offset':'20'}
    if op == 'detail':
        return dict(video, description='仅用于主机布局和交互测试。不是设备测试，也不是在线 B 站内容。',
                    parts=[dict(title='第 %d 集 / 分 P' % i, kind='video', bvid='BV1Da411Y7U4', aid='123', cid=str(i)) for i in range(1,5)])
    if op == 'qualities': return {'items':[{'id':n,'label':label} for n,label in ((0,'自动 · 流畅优先'),(16,'360P 流畅'),(32,'480P 清晰'),(64,'720P 高清'),(80,'1080P 高负载'),(116,'1080P60 高帧率'),(120,'4K 超清'),(125,'HDR 真彩'),(127,'8K 超高清'))], 'codecs':[{'id':n,'label':label} for n,label in ((0,'自动'),(7,'AVC'),(12,'HEVC'),(13,'AV1'))], 'preview':False}
    if op == 'comments':
        rows=[{'id':str(100+i),'author':'示例用户 '+str(i),'text':'这是用于布局测试的中文长评论。大字与分段阅读要保持清楚，小屏中可上下滚动查看。'*((i%3)+1),'likes':12,'replies':3,'pinned':i==0} for i in range(8)]
        return {'items':rows,'aid':'123','next':args.get('next',0)+1,'more':args.get('next',0)<1}
    if op == 'status': return {'logged_in':False, 'name':''}
    if op == 'qr_new': return {'qr_key':'PRIVATE_TEST_KEY_123', 'matrix':['10'*10+'1']*21}
    if op == 'qr_poll': return {'code':86101, 'cookies':[]}
    if op == 'image': return b'not an image'
    raise service.Failure('BAD_INPUT')


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='p011-bili-unit-')
        self.root = pathlib.Path(self.temp.name)
        self.account = self.root/'account'; self.account.mkdir()
        self.b = service.Backend(str(self.root), '', '', str(self.account), {}, helper=fixture)
    def tearDown(self): self.b.close(); self.temp.cleanup()
    def job(self, op, args=None):
        key = self.b.submit(op, args or {})
        until=time.monotonic()+2
        while time.monotonic()<until:
            result=self.b.result(key)
            if not result.get('pending'): return result
            time.sleep(.01)
        self.fail('job timeout')
    def test_syntax_35(self): ast.parse((BASE/'client/service.py').read_text(encoding='utf-8'), feature_version=(3,5))
    def test_hardware_close_grace_exceeds_worker_deadline(self):
        for hardware,seconds in ((False,3),(True,12)):
            child=Mock();child.poll.return_value=None
            self.b.hardware_required=hardware;self.b.children={child}
            with patch.object(service.time,'monotonic',return_value=100):self.b.close()
            child.terminate.assert_called_once_with()
            child.wait.assert_called_once_with(timeout=seconds)
            child.kill.assert_not_called()
            self.b.children.clear()
    def test_toolbox_existing_user_root_and_isolation(self):
        # Evaluate only the pure path helper; no storage/server is instantiated.
        tree=ast.parse((BASE/'client/toolbox_runtime.py').read_text(encoding='utf-8'),feature_version=(3,5))
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='data_root' or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='USER_ROOT' for t in n.targets)]
        namespace={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'toolbox-path','exec'),namespace)
        self.assertEqual(namespace['data_root']('/candidate',False),'/mnt/data/p011-toolbox/user')
        self.assertEqual(namespace['data_root']('/candidate',True),'/candidate/qa-user')
    def test_known_bv(self): self.assertEqual(service.safe_args('open', {'text':'BV1Da411Y7U4'})['kind'], 'video')
    def test_known_link(self): self.assertEqual(service.safe_args('open', {'text':'https://www.bilibili.com/video/BV1Da411Y7U4/?p=1'})['bvid'],'BV1Da411Y7U4')
    def test_known_episode(self): self.assertEqual(service.safe_args('open', {'text':'https://www.bilibili.com/bangumi/play/ep1234'})['ep'],'1234')
    def test_foreign_link(self):
        with self.assertRaises(service.Failure): service.safe_args('open', {'text':'https://evil.test/video/BV1Da411Y7U4'})
    def test_no_raw_url_or_path(self):
        for args in ({'kind':'video','bvid':'file:///etc/passwd'}, {'kind':'video','bvid':'BV1Da411Y7U4','cid':'../secret'}):
            with self.assertRaises(service.Failure): service.safe_args('play', args)
    def test_unknown_op(self):
        with self.assertRaises(service.Failure): self.b.submit('shell', {'command':'echo no'})
    def test_pagination_limits(self):
        for page in (False, 0, 101, '1'):
            with self.assertRaises(service.Failure): self.b.submit('recommend', {'page':page})
    def test_search_utf8_limit(self):
        with self.assertRaises(service.Failure): service.safe_args('search', {'query':'字'*54})
    def test_card_no_url_or_cookie(self):
        result=self.job('recommend'); raw=json.dumps(result)
        self.assertNotIn('https://',raw); self.assertNotIn('cookie',raw); self.assertEqual(len(result['data']['items']),7)
    def test_detail_parts(self): self.assertEqual(len(self.job('detail',{'kind':'video','bvid':'BV1Da411Y7U4'})['data']['parts']),4)
    def test_qualities_authorized_list_only(self):
        result=self.job('qualities',{'kind':'video','bvid':'BV1Da411Y7U4','cid':'1'})
        self.assertEqual([x['id'] for x in result['data']['items']],[0,16,32,64,80,116,120,125,127])
        self.assertNotIn('https:',json.dumps(result))
    def test_qualities_reject_bad_input(self):
        for q in (True,-1,65536,'32',None):
            with self.assertRaises(service.Failure):service.safe_args('play',{'kind':'video','bvid':'BV1Da411Y7U4','cid':'1','quality':q})
        with self.assertRaises(service.Failure):service.safe_args('qualities',{'kind':'season','season':'1'})
    def test_comments_normalized(self):
        result=self.job('comments',{'aid':'123','next':0,'mode':3})
        self.assertTrue(result['ok']);self.assertEqual(len(result['data']['items']),8)
        self.assertTrue(result['data']['items'][0]['pinned'])
        self.assertEqual(set(result['data']['items'][0]),{'id','author','text','likes','replies','pinned'})
    def test_comment_boundaries(self):
        for patch in ({'aid':'../secret'},{'next':True},{'next':-1},{'mode':0},{'root':'https://evil.test/'}):
            with self.assertRaises(service.Failure):service.safe_args('comments',dict({'aid':'123'},**patch))
    def test_comment_schema_refused(self):
        def bad(op,args):return {'items':[{'id':'1','likes':True}],'aid':'123'}
        self.b.helper_override=bad
        self.assertEqual(self.job('comments',{'aid':'123'})['error'],'API_SCHEMA')
    def test_play_queue_confined(self):
        base={'kind':'video','bvid':'BV1Da411Y7U4','cid':'1'}
        valid=service.safe_args('play',dict(base,queue=[{'kind':'video','bvid':'BV1Da411Y7U4'}],queue_index=0))
        self.assertEqual(valid['queue'][0],{'kind':'video','bvid':'BV1Da411Y7U4'})
        for changes in ({'queue':[base]*25},{'queue_index':True},{'queue':[base],'queue_index':1},{'portrait':1},{'danmaku':'yes'}):
            with self.assertRaises(service.Failure):service.safe_args('play',dict(base,**changes))
    def test_player_automation_scoped(self):
        for action in ('pause','capture_landscape','shell'):
            with self.assertRaises(service.Failure):self.b.player_test({'action':action})
        self.b.automation=True;self.b.protocol=2;self.b.qa_claimed=True
        with self.assertRaises(service.Failure):self.b.player_test({'action':'shell'})
        with self.assertRaises(service.Failure):self.b.player_test({'action':'pause'})
    def test_player_pipe_none_safe(self):self.assertFalse(self.b.send_player(None,0,{}))
    def protocol_fixture(self,events):
        class Player:
            def poll(self):return None
        p=Player();p.stdout=io.BytesIO(b''.join((json.dumps(x)+'\n').encode() for x in events));p.stdin=io.BytesIO()
        self.b.protocol=2;self.b.player=p;self.b.play_generation=7
        self.b.start_danmaku=lambda *args:None
        self.b.helper_override=lambda op,args:dict(video='https://test.bilivideo.com/PRIVATE_SIGNED',audio='',quality=args.get('quality',16),qualities=[])
        return p
    def test_protocol_private_quality_roundtrip(self):
        p=self.protocol_fixture([dict(action='quality',seq=1,quality=32)])
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1'))
        value=json.loads(p.stdin.getvalue())
        self.assertTrue(value['ok']);self.assertTrue(value['keep_position']);self.assertEqual(value['quality'],32)
        self.assertNotIn('PRIVATE_SIGNED',json.dumps(self.b.state()))
        self.assertFalse(any('PRIVATE_SIGNED' in f.read_text(errors='replace') for f in self.root.iterdir() if f.is_file()))
    def test_protocol_rejects_replayed_and_unknown_actions(self):
        p=self.protocol_fixture([dict(action='shell',seq=1),dict(action='quality',seq=2,quality=32),dict(action='next',seq=2),dict(action='quality',seq=True,quality=32)])
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1'))
        self.assertEqual(len(p.stdin.getvalue().splitlines()),1)
    def test_protocol_codec_roundtrip_and_position(self):
        p=self.protocol_fixture([dict(action='codec',seq=1,codec=12),dict(action='codec',seq=2,codec=13)])
        self.b.helper_override=lambda op,args:dict(video='https://test.bilivideo.com/PRIVATE_SIGNED',audio='',quality=32,codec=args['codec'],qualities=[],codecs=[])
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1',quality=32))
        results=[json.loads(x) for x in p.stdin.getvalue().splitlines()]
        self.assertEqual([x['codec'] for x in results],[12,13]);self.assertTrue(all(x['keep_position'] and x['serial']==1 for x in results))
    def test_explicit_codec_unavailable_does_not_fallback(self):
        p=self.protocol_fixture([dict(action='codec',seq=1,codec=13)])
        calls=[]
        def unavailable(op,args):calls.append(args);raise service.Failure('CODEC_UNAVAILABLE')
        self.b.helper_override=unavailable
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1',quality=32))
        result=json.loads(p.stdin.getvalue());self.assertFalse(result['ok']);self.assertEqual(result['error'],'CODEC_UNAVAILABLE');self.assertEqual(len(calls),1)
    def test_official_story_bridge_forward_and_previous(self):
        p=self.protocol_fixture([dict(action='story',seq=1),dict(action='next',seq=2),dict(action='previous',seq=3)])
        def respond(op,args):
            if op=='story':return dict(source='official-story',offset='10',more=True,items=[dict(kind='video',bvid='BV1Da411Y7U4',cid=str(n)) for n in (1,2)])
            if op=='play':return dict(video='https://test.bilivideo.com/PRIVATE_SIGNED',audio='',quality=16,codec=7,qualities=[],codecs=[])
            raise service.Failure('BAD_INPUT')
        self.b.helper_override=respond
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1'))
        results=[json.loads(x) for x in p.stdin.getvalue().splitlines()]
        self.assertEqual([x['queue_index'] for x in results],[0,1,0]);self.assertTrue(all(x['story'] and not x['keep_position'] for x in results))
    def test_protocol_stale_generation_cannot_write(self):
        p=self.protocol_fixture([])
        self.assertFalse(self.b.send_player(p,6,dict(op='stream',video='PRIVATE_SIGNED')))
        self.assertEqual(p.stdin.getvalue(),b'')
    def test_protocol_playlist_boundary_retains_current(self):
        p=self.protocol_fixture([dict(action='previous',seq=1)])
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1'))
        value=json.loads(p.stdin.getvalue());self.assertFalse(value['ok']);self.assertEqual(value['error'],'CANCELED')
    def test_protocol_next_keeps_queue_and_resets_time(self):
        p=self.protocol_fixture([dict(action='next',seq=1)])
        a=dict(kind='video',bvid='BV1Da411Y7U4',cid='1')
        self.b.player_events(p,7,dict(a,queue=[a,dict(a,cid='2')],queue_index=0))
        value=json.loads(p.stdin.getvalue());self.assertTrue(value['ok']);self.assertFalse(value['keep_position'])
        self.assertEqual((value['serial'],value['queue_index'],value['queue_count']),(2,1,2))
    def test_protocol_quality_error_does_not_expose_exception(self):
        p=self.protocol_fixture([dict(action='quality',seq=1,quality=32)])
        def failed(*args):raise ValueError('PRIVATE_SIGNED')
        self.b.helper_override=failed
        self.b.player_events(p,7,dict(kind='video',bvid='BV1Da411Y7U4',cid='1'))
        value=json.loads(p.stdin.getvalue());self.assertFalse(value['ok']);self.assertEqual(value['error'],'INTERNAL')
        self.assertNotIn('PRIVATE',p.stdin.getvalue().decode())
    def test_long_part_queue_crosses_old_24_item_window(self):
        p=self.protocol_fixture([dict(action='next',seq=1),dict(action='previous',seq=2)])
        rows=[dict(kind='video',bvid='BV1Da411Y7U4',cid=str(n+1)) for n in range(59)]
        self.b.player_events(p,7,dict(rows[24],queue=rows,queue_index=24,queue_source=dict(category='parts')))
        values=[json.loads(x) for x in p.stdin.getvalue().splitlines()]
        self.assertEqual([v['queue_index'] for v in values],[25,24]);self.assertTrue(all(v['queue_count']==59 for v in values))
    def test_catalog_queue_skips_duplicates_and_empty_pages(self):
        p=self.protocol_fixture([dict(action='next',seq=1)])
        first=dict(kind='video',bvid='BV1Da411Y7U4',cid='1',playable=True)
        second=dict(first,bvid='BV1gi4y1V7Xx',cid='2');calls=[]
        def catalog(op,args,generation):
            calls.append(args['page']);return dict(items=[first,first] if args['page']==2 else [] if args['page']==3 else [second,second],more=args['page']<4)
        self.b.dispatch=catalog
        self.b.player_events(p,7,dict(first,queue=[first],queue_index=0,queue_more=True,queue_source=dict(category='watchlater',page=1)))
        value=json.loads(p.stdin.getvalue());self.assertTrue(value['ok']);self.assertEqual(value['queue_count'],2);self.assertEqual(calls,[2,3,4])
    def test_live_quality_uses_live_contract(self):
        p=self.protocol_fixture([dict(action='quality',seq=1,quality=150)]);calls=[]
        self.b.helper_override=lambda op,a: calls.append(op) or dict(video='https://test.bilivideo.com/PRIVATE',audio='',quality=150,codec=7)
        self.b.player_events(p,7,dict(kind='live',room='1',quality=80))
        self.assertEqual(calls,['live_play']);self.assertTrue(json.loads(p.stdin.getvalue())['ok'])
    def test_danmaku_bounded_encodings(self):
        raw=b'<i><d p="1.25,1,25,16777215,0,0,PRIVATE_ID,1">hi &amp; bye</d><d p="0.5,5,25,1">early</d></i>'
        for bits in (-15,15,31):
            packed=zlib.compressobj(wbits=bits);body=packed.compress(raw)+packed.flush()
            result=service.decode_danmaku(body)
            self.assertEqual([r['time'] for r in result['items']],[.5,1.25])
            self.assertEqual(result['items'][1]['text'],'hi & bye');self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertEqual(len(service.decode_danmaku(raw)['items']),2)
    def test_danmaku_entities_and_limits(self):
        for raw in (b'not XML',b'<!DOCTYPE x><i></i>',b'<!ENTITY x><i></i>',zlib.compress(b'X'*(4*1024*1024+1))):
            with self.assertRaises(service.Failure):service.decode_danmaku(raw)
        result=service.decode_danmaku(b'<i><d p="nan,1,25,1">bad</d><d p="1,1,25,1">&#x41;&lt;raw&gt;</d></i>')
        self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['text'],'A<raw>')
    def test_bootstrap_once(self):
        self.assertEqual(self.b.bootstrap(), self.b.token)
        with self.assertRaises(service.Failure): self.b.bootstrap()
    def test_bootstrap_timeout(self):
        self.b.bootstrap_deadline=0
        with self.assertRaises(service.Failure): self.b.bootstrap()
    def test_automation_disabled_by_default(self):
        self.b.bootstrap()
        with self.assertRaises(service.Failure): self.b.qa_start()
        self.assertFalse((self.root/'screenshots').exists())
    def test_automation_claim_once_and_failure_safe(self):
        self.b.automation=True;self.b.bootstrap();self.b.qa_start()
        with self.assertRaises(service.Failure): self.b.qa_start()
        for update in ({'error':'PRIVATE_TOKEN'}, {'captures':['../cookies']}, {'step':True}, {'passed':True}):
            value=dict(passed=False,error='ASSERTION',step=1,checks=['bootstrap'],captures=[]);value.update(update)
            with self.assertRaises(service.Failure): self.b.qa_finish(value)
        self.b.qa_finish(dict(passed=False,error='ASSERTION',step=1,checks=['bootstrap'],captures=[]))
        self.assertNotIn('PRIVATE_TOKEN',(self.root/'ui-qa-result.json').read_text())
        with self.assertRaises(service.Failure): self.b.qa_finish({})
    def test_qr_key_private(self):
        result=self.job('qr_new'); self.assertTrue(result['ok']); self.assertNotIn('PRIVATE_TEST_KEY', json.dumps(result))
        self.assertEqual(self.job('qr_poll', {'key':'USER_CANNOT_INJECT'})['data'], {'code':86101})
    def failed_ui_read_diagnostic(self,diagnostic):
        self.b.automation=True;self.b.protocol=2;self.b.bootstrap();self.b.qa_start()
        self.b.state=lambda:{'player':{}}
        self.b.qa_finish(dict(passed=False,error='NO_CONTENT',step=0,checks=['bootstrap'],captures=[],
                              player_checks=[],player_stage=0,player_diagnostic=diagnostic))
        return json.loads((self.root/'ui-qa-result.json').read_text())
    def test_automation_read_failure_preserves_numeric_cause(self):
        report=self.failed_ui_read_diagnostic(dict(read_error='NETWORK_ERROR',read_code=28))
        self.assertFalse(report['passed']);self.assertEqual(report['error'],'NO_CONTENT')
        self.assertEqual(report['player_diagnostic']['read_error'],'NETWORK_ERROR')
        self.assertEqual(report['player_diagnostic']['read_code'],28)
    def test_automation_read_failure_drops_untrusted_text_and_bool(self):
        report=self.failed_ui_read_diagnostic(dict(read_error='PRIVATE_TOKEN_OR_URL',read_code=True))
        self.assertNotIn('PRIVATE',json.dumps(report))
        self.assertNotIn('read_error',report['player_diagnostic']);self.assertNotIn('read_code',report['player_diagnostic'])
    def test_automation_read_diagnostic_cannot_report_stale_error(self):
        panel=(BASE/'client/BiliPanel.qml').read_text(encoding='utf-8')
        automation=(BASE/'client/BiliAutomation.qml').read_text(encoding='utf-8')
        self.assertIn('property int readErrorCode: 0',panel)
        self.assertIn('Math.floor(reply.code)===reply.code',panel)
        self.assertIn('Math.abs(reply.code)<100000000',panel)
        self.assertIn('read_error:target.readError?target.readErrorKind:""',automation)
        self.assertIn('read_code:target.readError?target.readErrorCode:0',automation)
    def automation_native_success(self):
        return dict(generation=1,reason='back',muted=True,pulse=True,loaded=True,gl_errors={},quality_switches=4,video_switches=8,rotation_actions=3,swipe_actions=7,pause_actions=6,seek_actions=6,scrub_actions=3,overlay_toggle_actions=2,danmaku_frames=1,draws=50,capture_count=20)
    def automation_result_fixture(self,native,bits=None,secondary=None,media=None,generation=4,player_checks=None):
        import struct
        self.b.automation=True;self.b.protocol=2;self.b.bootstrap();self.b.qa_start()
        for name in service.UI_QA_CAPTURES:
            (self.root/'screenshots'/(name+'.png')).write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00'*8+struct.pack('>II',800,480))
        # The finished player may have been invalidated by toolbox navigation.
        self.b.state=lambda:{'player':{}}
        self.b.play_generation=generation
        self.b.preferences=service.Preferences(str(self.root/'preferences'))
        self.b.preferences.save(self.b.playback_settings)
        if native is not None:(self.root/'player-primary-result.json').write_text(json.dumps(native))
        (self.root/'player-result.json').write_text(json.dumps(secondary if secondary is not None else dict(generation=2,reason='back',loaded=True,pulse=True,muted=True,gl_errors={})))
        (self.root/'media-state.json').write_text(json.dumps(media if media is not None else dict(self.b.playback_settings,generation=2,story=True)))
        (self.root/'render-info.json').write_text(json.dumps({'rgba_bits':bits or [8,8,8,8]}))
        expected=service.PLAYER_QA_CHECKS+(service.HARDWARE_QA_CHECKS if self.b.hardware_required else ())+(service.UX_HARDWARE_QA_CHECKS if self.b.hardware_required and self.b.library is not None else ())
        self.b.qa_finish(dict(passed=True,error='',step=12,checks=list(service.UI_QA_CHECKS),captures=list(service.UI_QA_CAPTURES),player_checks=list(expected) if player_checks is None else player_checks,player_stage=49,player_diagnostic={'native_keyboard_reused':True}))
        return json.loads((self.root/'ui-qa-result.json').read_text())
    def test_automation_audio_evidence_survives_toolbox_return(self):
        report=self.automation_result_fixture(self.automation_native_success())
        self.assertTrue(report['passed']);self.assertTrue(report['audio_played']);self.assertTrue(report['audio_output_muted']);self.assertFalse(report['physical_touch_verified'])
        self.assertTrue(report['preferences_reopened_verified'])
    def test_hardware_cleanup_rejects_forced_or_incomplete_exit(self):
        clean=dict(starts=3,normal_exits=3,abnormal_exits=0,forced_kills=0,last_exit=0)
        self.assertTrue(service.hardware_cleanup_ok({'hardware':clean}))
        for change in (dict(starts=0),dict(starts=True),dict(normal_exits=2),dict(abnormal_exits=1),dict(forced_kills=1),dict(last_exit=45)):
            self.assertFalse(service.hardware_cleanup_ok({'hardware':dict(clean,**change)}))
        for value in ({},None,{'hardware':None}):self.assertFalse(service.hardware_cleanup_ok(value))
    def test_hardware_automation_requires_clean_both_players(self):
        self.b.hardware_required=True
        report=self.automation_result_fixture(self.automation_native_success())
        self.assertFalse(report['passed']);self.assertTrue(report['hardware_required'])
    def test_cached_hardware_requires_final_pairs_for_every_worker(self):
        last=dict(cache_final=True,cache_active=0,cache_fallback_active=0,cache_sync_errors=0,cache_ownership_errors=0,
                  cache_registered=20,cache_forgotten=20,cache_read_begin=60,cache_read_end=60,
                  cache_fallback_registered=10,cache_fallback_forgotten=10,cache_fallback_read_begin=30,cache_fallback_read_end=30)
        clean=dict(starts=3,normal_exits=3,abnormal_exits=0,forced_kills=0,last_exit=0,
                   cache_sessions=3,cache_failures=0,cache_last=last)
        self.assertTrue(service.hardware_cleanup_ok({'hardware':clean}))
        for change in (dict(cache_sessions=2),dict(cache_failures=1),dict(cache_last={}),
                       dict(cache_last=dict(last,cache_fallback_active=1)),dict(cache_last=dict(last,cache_forgotten=19)),
                       dict(cache_last=dict(last,cache_fallback_read_end=29)),dict(cache_last=dict(last,cache_read_end=True))):
            self.assertFalse(service.hardware_cleanup_ok({'hardware':dict(clean,**change)}))
    def test_hardware_automation_with_exact_checks_and_clean_exits(self):
        self.b.hardware_required=True
        audit=dict(starts=3,normal_exits=3,abnormal_exits=0,forced_kills=0,last_exit=0)
        native=dict(self.automation_native_success(),hardware=audit)
        secondary=dict(generation=2,reason='back',loaded=True,pulse=True,muted=True,gl_errors={},hardware=audit)
        report=self.automation_result_fixture(native,secondary=secondary)
        self.assertTrue(report['passed']);self.assertEqual(len(report['player_checks']),42)
    def test_hardware_automation_rejects_missing_backend_checks(self):
        self.b.hardware_required=True
        with self.assertRaises(service.Failure):self.automation_result_fixture(self.automation_native_success(),player_checks=list(service.PLAYER_QA_CHECKS))
    def test_unavailable_stream_injection_is_one_shot_and_probe_only(self):
        self.b.automation=True;self.b.qa_claimed=True;self.b.protocol=2
        self.b.state=lambda:{'player':{'paused':True}}
        with self.assertRaises(service.Failure):self.b.player_test({'action':'ux_unavailable_stream'})
        self.b.ux_probe=True;self.b.state=lambda:{'player':{'paused':False}}
        with self.assertRaises(service.Failure):self.b.player_test({'action':'ux_unavailable_stream'})
        self.b.state=lambda:{'player':{'paused':True}};packets=[]
        self.b.send_player=lambda p,g,v:packets.append(v) or True
        self.assertTrue(self.b.player_test({'action':'ux_unavailable_stream'})['ok'])
        self.assertEqual(packets,[dict(op='test',action='quality_32')]);self.assertTrue(self.b.ux_fault_pending)
        with self.assertRaises(service.Failure):self.b.player_test({'action':'ux_unavailable_stream'})
    def test_state_probe_endpoint_is_disabled_in_normal_service(self):
        with self.assertRaises(service.Failure):self.b.ux_state_check({'phase':'finish','passed':True})
    def test_ux_hardware_requires_actual_story_replay_and_clean_shutdown(self):
        self.b.hardware_required=True;self.b.library=object()
        audit=dict(starts=3,normal_exits=3,abnormal_exits=0,forced_kills=0,last_exit=0)
        native=dict(self.automation_native_success(),hardware=audit)
        secondary=dict(generation=2,reason='back',loaded=True,pulse=True,muted=True,gl_errors={},hardware=audit)
        media=dict(self.b.playback_settings,generation=2,story=True,story_loop_completed=1,story_loop_failures=0,story_loop_pending=False)
        report=self.automation_result_fixture(native,secondary=secondary,media=media)
        self.assertTrue(report['passed']);self.assertIn('story-replay',report['player_checks'])
    def test_ux_hardware_missing_replay_is_not_a_pass(self):
        self.b.hardware_required=True;self.b.library=object()
        audit=dict(starts=3,normal_exits=3,abnormal_exits=0,forced_kills=0,last_exit=0)
        native=dict(self.automation_native_success(),hardware=audit)
        secondary=dict(generation=2,reason='back',loaded=True,pulse=True,muted=True,gl_errors={},hardware=audit)
        report=self.automation_result_fixture(native,secondary=secondary)
        self.assertFalse(report['passed'])
    def test_automation_rejects_duplicate_checks(self):
        with self.assertRaises(service.Failure):self.automation_result_fixture(self.automation_native_success(),player_checks=list(service.PLAYER_QA_CHECKS[:-1])+[service.PLAYER_QA_CHECKS[0]])
    def test_automation_preferences_mismatch_rejected(self):
        report=self.automation_result_fixture(self.automation_native_success(),media=dict(self.b.playback_settings,generation=2,story=True,dm_area=25))
        self.assertFalse(report['passed']);self.assertFalse(report['preferences_reopened_verified'])
    def test_automation_native_failure_is_recorded(self):
        report=self.automation_result_fixture({'gl_errors':{'mpv_1285':1}})
        self.assertFalse(report['passed']);self.assertEqual(report['error'],'PLAYER_QA_FAILED')
    def test_automation_rejects_posterized_color_buffer(self):
        report=self.automation_result_fixture(self.automation_native_success(),[4,4,4,4]);self.assertFalse(report['passed']);self.assertEqual(report['error'],'PLAYER_QA_FAILED')
    def test_automation_cancellation_generation_does_not_select_wrong_result(self):
        self.assertTrue(self.automation_result_fixture(self.automation_native_success(),generation=99)['passed'])
    def test_automation_second_run_missing_is_failure(self):
        self.assertFalse(self.automation_result_fixture(self.automation_native_success(),secondary={})['passed'])
    def test_automation_second_run_must_be_story(self):
        self.assertFalse(self.automation_result_fixture(self.automation_native_success(),media=dict(generation=2,story=False))['passed'])
    def test_automation_primary_identity_must_match(self):
        native=self.automation_native_success();native['generation']=2
        self.assertFalse(self.automation_result_fixture(native)['passed'])
    def test_automation_new_events_cannot_be_skipped(self):
        native=self.automation_native_success();native['video_switches']=7
        self.assertFalse(self.automation_result_fixture(native)['passed'])
    def test_automation_missing_native_result_is_not_success(self):
        report=self.automation_result_fixture(None)
        self.assertFalse(report['passed']);self.assertEqual(report['error'],'PLAYER_QA_FAILED')
    def test_qr_canceled_generation(self):
        self.b.qr_generation=2
        with self.assertRaises(service.Failure): self.b.dispatch('qr_new',{},1)
    def test_qr_poll_race(self):
        self.b.qr_key='OLD_KEY_123'; self.b.qr_generation=1; self.b.qr_deadline=time.monotonic()+60
        def race(op,args):
            self.b.qr_generation+=1
            return {'code':0,'cookies':['.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tTEST_SECRET']}
        self.b.helper_override=race
        with self.assertRaises(service.Failure): self.b.dispatch('qr_poll',{},1)
        self.assertFalse((self.account/'cookies.txt').exists())
    def test_cookie_scope(self):
        with self.assertRaises(service.Failure): self.b.save_cookies(['.evil.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tTEST_SECRET'])
        self.assertFalse((self.account/'cookies.txt').exists())
    def test_cookie_save_and_logout(self):
        self.b.save_cookies(['#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tTEST_SECRET'])
        self.assertIn('TEST_SECRET',(self.account/'cookies.txt').read_text())
        result=self.job('logout'); self.assertTrue(result['ok']); self.assertNotIn('TEST_SECRET',json.dumps(result))
        self.assertFalse((self.account/'cookies.txt').exists())
    def test_image_allowlist(self):
        for url in ('file:///etc/passwd','https://127.0.0.1/a','https://hdslb.com.evil.test/a','https://evil.test/a'):
            self.assertEqual(self.b.image_key(url),'')
        self.assertTrue(self.b.image_key('https://i0.hdslb.com/image.jpg'))
    def test_errors_do_not_echo(self):
        self.assertNotIn('secret', json.dumps(service.error_result(ValueError('secret'))))
        self.assertEqual(service.error_result(service.Failure('BAD_INPUT', 'secret'))['code'],-1)
    def test_play_diagnostics_safe(self):
        self.b.play_diagnostic('prepare_failed', error='NETWORK_ERROR', code=28)
        value=json.loads((self.root/'play-diagnostic.json').read_text())
        self.assertEqual(value,{'stage':'prepare_failed','generation':0,'error':'NETWORK_ERROR','code':28})
        self.b.play_diagnostic('player_exit', error='https://example.test/PRIVATE', code='PRIVATE')
        self.assertNotIn('PRIVATE',(self.root/'play-diagnostic.json').read_text())
        self.assertNotIn('error',json.loads((self.root/'play-diagnostic.json').read_text()))
    def test_failed_prepare_diagnostic(self):
        self.assertFalse(self.job('play',{'kind':'video','bvid':'BV1Da411Y7U4','cid':'1'})['ok'])
        value=json.loads((self.root/'play-diagnostic.json').read_text())
        self.assertEqual(value['stage'],'prepare_failed')
        self.assertEqual(value['error'],'BAD_INPUT')
    def test_player_exit_safe_code(self):
        class Exited:
            def wait(self):return 22
            def poll(self):return 22
        p=Exited();self.b.player=p;self.b.children.add(p)
        self.b.reap_player(p)
        self.assertEqual(self.b.state()['play_exit_code'],22)
        self.assertEqual(self.b.state()['play_end'],'failed')
        self.assertEqual(json.loads((self.root/'play-diagnostic.json').read_text())['code'],22)
    def test_stale_player_exit_does_not_overwrite(self):
        class Exited:
            def wait(self):return 22
        self.b.reap_player(Exited())
        self.assertIsNone(self.b.state()['play_exit_code'])
        self.assertFalse((self.root/'play-diagnostic.json').exists())
    def test_offline_pinyin(self):
        self.assertIn('电影',[x['text'] for x in self.b.lookup_pinyin('dianying')['candidates']])
        self.assertIn('你好',[x['text'] for x in self.b.lookup_pinyin('nihao')['candidates']])
        self.assertTrue(all(x['consume']>0 for x in self.b.lookup_pinyin('zh')['candidates']))
    def test_pinyin_does_not_use_network(self):
        def refused(*args):self.fail('Offline keyboard made network call')
        self.b.helper_override=refused
        self.assertTrue(self.job('pinyin',{'code':'zhong'})['ok'])
    def test_http_guards(self):
        server=service.HTTPServer(('127.0.0.1',0),service.Handler)
        server.backend=self.b; server.expected_host='127.0.0.1:'+str(server.server_address[1])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,headers=None,method='GET',body=None):
            c=http.client.HTTPConnection(*server.server_address,timeout=3)
            c.request(method,path,body=body,headers=headers or {})
            response=c.getresponse(); data=response.read(); code=response.status;c.close();return code,data
        try:
            self.assertEqual(request('/state')[0],403)
            good={'X-P011-Token':self.b.token}
            self.assertEqual(request('/state',good)[0],200)
            self.assertEqual(request('/state',dict(good,Origin='https://evil.test'))[0],403)
            self.assertEqual(request('/state',dict(good,Host='evil.test'))[0],403)
            self.assertEqual(request('/state',dict(good,**{'Sec-Fetch-Site':'cross-site'}))[0],403)
            code,body=request('/jobs',good,'POST','{"op":"shell","args":{}}')
            self.assertEqual(code,200);self.assertEqual(json.loads(body)['error'],'BAD_INPUT')
            self.assertEqual(request('/bootstrap',{'X-P011-Native-UI':'bili-qml-runtime'},'POST','{}')[0],200)
            self.assertEqual(request('/bootstrap',{'X-P011-Native-UI':'bili-qml-runtime'},'POST','{}')[0],409)
            status,body=request('/state',good)
            self.assertNotIn(self.b.token.encode(),body)
        finally: server.shutdown();server.server_close();thread.join(2)


class PerformanceFinishTests(unittest.TestCase):
    """Pure report gate tests: no worker threads, network, login, or ADB."""
    def record(self, request=None, player=None, **flags):
        with tempfile.TemporaryDirectory(prefix='p011-bili-report-') as root:
            backend=service.Backend.__new__(service.Backend)
            backend.root=root
            backend.automation=flags.get('automation',True)
            backend.qa_claimed=flags.get('qa_claimed',True)
            backend.protocol=flags.get('protocol',2)
            backend.benchmark_seek=flags.get('benchmark_seek',True)
            state=dict(muted=True,pulse_observed=True,loaded=True,quality=16,
                       active=True,paused=False,hardware_backend=True,hardware_verified=True,
                       scrub_actions=1,pause_actions=2,duration=400.,position=100.5)
            state.update(player or {})
            backend.state=lambda:{'player':state}
            payload=dict(mode='seek',passed=True,quality=16,stage=7)
            payload.update(request or {})
            self.assertEqual(backend.performance_finish(payload),{'recorded':True})
            report=json.loads((pathlib.Path(root)/'performance-qa.json').read_text())
            self.assertFalse(report['physical_acceptance'])
            return report

    def test_seek_success_requires_runtime_evidence(self):
        report=self.record()
        self.assertTrue(report['passed']);self.assertEqual(report['mode'],'seek')

    def test_timed_out_seek_is_recorded_as_failure(self):
        report=self.record(dict(passed=False,stage=6),dict(paused=True,position=6.))
        self.assertFalse(report['passed']);self.assertEqual(report['stage'],6)

    def test_no_seek_success_from_stage_or_request_alone(self):
        for request in (dict(stage=6),dict(passed=False)):
            with self.subTest(request=request):self.assertFalse(self.record(request)['passed'])

    def test_seek_requires_actual_hardware_muted_playing_and_loaded(self):
        for key in ('muted','pulse_observed','loaded','active','hardware_backend','hardware_verified'):
            with self.subTest(key=key):self.assertFalse(self.record(player={key:False})['passed'])
        self.assertFalse(self.record(player={'paused':True})['passed'])

    def test_seek_requires_actions_quality_and_target_position(self):
        for player in (dict(scrub_actions=0),dict(pause_actions=1),dict(quality=32),
                       dict(duration=0.),dict(position=6.),dict(position=102.)):
            with self.subTest(player=player):self.assertFalse(self.record(player=player)['passed'])

    def test_seek_requires_explicit_build_flag(self):
        with self.assertRaises(service.Failure):self.record(benchmark_seek=False)

    def test_not_available_to_normal_or_unclaimed_ui(self):
        for flags in (dict(automation=False),dict(qa_claimed=False),dict(protocol=1)):
            with self.subTest(flags=flags),self.assertRaises(service.Failure):self.record(**flags)

    def test_mode_and_stage_are_bounded(self):
        for request in (dict(mode='arbitrary'),dict(stage=-1),dict(stage=8),dict(stage=True),
                        dict(stage='7'),dict(passed=1),dict(quality=True)):
            with self.subTest(request=request),self.assertRaises(service.Failure):self.record(request)

    def test_regular_performance_keeps_its_original_gate(self):
        request=dict(mode='performance',stage=4)
        self.assertTrue(self.record(request,dict(paused=True,active=False,position=31.),benchmark_seek=False)['passed'])
        self.assertFalse(self.record(request,dict(paused=True,position=29.))['passed'])
        self.assertFalse(self.record(request,dict(paused=False,position=31.))['passed'])
        with self.assertRaises(service.Failure):self.record(dict(mode='performance',stage=6))


if __name__ == '__main__': unittest.main(verbosity=2)
