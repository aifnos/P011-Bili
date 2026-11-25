"""Fixtures only. Never mutate a real account or solve a captcha."""
import ast
import copy
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch
from test_client import service,BASE

BV='BV1Da411Y7U4'
REL={'like':False,'favorite':False,'coin':0}

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);(self.root/'account').mkdir();self.calls=[]
        self.b=service.Backend(str(self.root),'','',str(self.root/'account'),{},helper=self.fixture)
    def tearDown(self):self.b.close();self.tmp.cleanup()
    def fixture(self,op,args):
        self.calls.append((op,copy.deepcopy(args)))
        if op=='relation':return dict(REL)
        if op=='favorites':return {'items':[{'id':'42','title':'我的收藏','selected':False}]}
        if op=='interaction':return {'confirmed':True,'state_available':True,'relation':dict(REL,like=True)}
        if op=='season_relation':return {'following':False,'title':'合成番剧'}
        if op=='season_follow':return {'confirmed':True,'state_available':False}
        if op=='account_history':return {'items':[],'more':False,'cursor':{'max':'0','view_at':'0','business':'archive'}}
        if op=='password_challenge':return {'token':'t'*32,'gt':'g'*32,'challenge':'c'*32}
        if op=='password_login':return {'cookies':['.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tUNIT_ONLY']}
        raise service.Failure('BAD_INPUT')
    def call(self,op,args=None):return self.b.dispatch(op,service.safe_args(op,args or {}),self.b.qr_generation)
    def intent(self):return self.call('relation',{'bvid':BV})['intent']
    def test_strict_actions(self):
        for action in ('dislike','shell','password'):
            with self.assertRaises(service.Failure):service.safe_args('interaction',{'bvid':BV,'action':action,'intent':'f'*32})
        for count in (True,0,3,'1'):
            with self.assertRaises(service.Failure):service.safe_args('interaction',{'bvid':BV,'action':'coin','count':count,'intent':'f'*32})
    def test_one_use_intent(self):
        a={'bvid':BV,'action':'like','value':True,'intent':self.intent()}
        self.assertTrue(self.call('interaction',a)['confirmed'])
        with self.assertRaises(service.Failure):self.call('interaction',a)
        self.assertEqual(sum(op=='interaction' for op,args in self.calls),1)
    def test_watchlater_and_follow_bound_to_video(self):
        for action in ('watchlater','follow'):
            for value in (False,True):
                a=service.safe_args('interaction',dict(bvid=BV,action=action,value=value,intent=self.intent(),owner_mid='999',url='https://evil.test/'))
                self.assertNotIn('owner_mid',a);self.assertNotIn('url',a)
                self.assertTrue(self.call('interaction',a)['confirmed'])
                with self.assertRaises(service.Failure):self.call('interaction',a)
        self.b.automation=True
        with self.assertRaises(service.Failure):self.call('interaction',dict(bvid=BV,action='follow',value=True,intent='f'*32))
    def test_comment_text_and_reply_binding(self):
        a=dict(bvid=BV,action='comment',message='合成文字',root='0',parent='0',intent=self.intent())
        self.assertTrue(self.call('interaction',a)['confirmed'])
        self.b.features.note_comments(BV,'',[{'id':'20'}],self.b.qr_generation)
        a.update(root='20',parent='20',intent=self.intent());self.assertTrue(self.call('interaction',a)['confirmed'])
        self.b.features.note_comments(BV,'20',[{'id':'21'}],self.b.qr_generation)
        a.update(parent='21',intent=self.intent());self.assertTrue(self.call('interaction',a)['confirmed'])
        for root,parent in [('20','999'),('21','21')]:
            a.update(root=root,parent=parent,intent=self.intent())
            with self.assertRaises(service.Failure):self.call('interaction',a)
    def test_comment_invalid_text(self):
        for text in ('','  ','a'*161,'bad\ntext',None):
            with self.assertRaises(service.Failure):service.safe_args('interaction',dict(bvid=BV,action='comment',message=text,root='0',parent='0',intent='f'*32))
        with self.assertRaises(service.Failure):service.safe_args('interaction',dict(bvid=BV,action='comment_like',value=True,root='0',parent='0',intent='f'*32))
    def test_comment_like_once_and_automation(self):
        self.b.features.note_comments(BV,'',[{'id':'20'}],self.b.qr_generation)
        a=dict(bvid=BV,action='comment_like',value=True,root='20',parent='20',intent=self.intent())
        self.assertTrue(self.call('interaction',a)['confirmed'])
        with self.assertRaises(service.Failure):self.call('interaction',a)
        self.b.automation=True
        with self.assertRaises(service.Failure) as ctx:self.call('interaction',dict(a,intent='f'*32))
        self.assertEqual(ctx.exception.error,'ACTION_DISABLED')
    def test_season_intent_and_no_writes_automated(self):
        a=dict(season='1',value=True,intent=self.call('season_relation',{'season':'1'})['intent'])
        self.assertTrue(self.call('season_follow',a)['confirmed'])
        with self.assertRaises(service.Failure):self.call('season_follow',a)
        a['intent']=self.intent()
        with self.assertRaises(service.Failure):self.call('season_follow',a)
        a['intent']=self.call('season_relation',{'season':'1'})['intent'];self.b.automation=True
        with self.assertRaises(service.Failure) as ctx:self.call('season_follow',a)
        self.assertEqual(ctx.exception.error,'ACTION_DISABLED')
    def test_cross_video_and_login_intents_rejected(self):
        nonce=self.intent();self.b.qr_generation+=1
        with self.assertRaises(service.Failure):self.call('interaction',dict(bvid=BV,action='triple',intent=nonce))
        nonce=self.intent()
        with self.assertRaises(service.Failure):self.call('interaction',dict(bvid='BV1gi4y1V7Xx',action='triple',intent=nonce))
        self.assertFalse(any(op=='interaction' for op,args in self.calls))
    def test_automated_writes_blocked_before_helper(self):
        nonce=self.intent();self.b.automation=True
        for op,a in [('interaction',dict(bvid=BV,action='triple',intent=nonce)),('password_challenge',{})]:
            with self.assertRaises(service.Failure) as ctx:self.call(op,a)
            self.assertEqual(ctx.exception.error,'ACTION_DISABLED')
        self.assertEqual(len(self.calls),1)
    def test_lost_write_response_not_retried(self):
        nonce=self.intent();self.b.helper_override=lambda op,args:(_ for _ in ()).throw(service.Failure('HELPER_TIMEOUT'))
        with self.assertRaises(service.Failure) as ctx:self.call('interaction',dict(bvid=BV,action='triple',intent=nonce))
        self.assertEqual(ctx.exception.error,'ACTION_UNCONFIRMED')
        with self.assertRaises(service.Failure) as ctx:self.call('interaction',dict(bvid=BV,action='triple',intent=nonce))
        self.assertEqual(ctx.exception.error,'ACTION_EXPIRED')
    def test_folder_identity_preserved(self):self.assertEqual(self.call('favorites',{'bvid':BV})['items'][0]['id'],'42')
    def test_history_is_explicit_cloud(self):
        d=self.call('account_history');self.assertEqual(d['source'],'official-account');self.assertEqual(d['items'],[])
        with self.assertRaises(service.Failure):service.safe_args('account_history',{'max':'../../etc'})
    def test_password_private_token_and_single_use(self):
        d=self.call('password_challenge');self.assertNotIn('token',d)
        a=dict(username='fixture',password='private-unit-only',nonce=d['nonce'],challenge='c'*32,validate='v'*32,seccode='s'*32)
        with patch.object(self.b,'save_cookies') as save:
            self.assertTrue(self.call('password_login',a)['logged_in']);self.assertEqual(save.call_count,1)
        self.assertEqual(self.calls[-1][1]['token'],'t'*32)
        with self.assertRaises(service.Failure):self.call('password_login',a)
        self.assertFalse((self.root/'account'/'cookies.txt').exists())
    def test_password_cancel_and_logout_generation(self):
        d=self.call('password_challenge');self.call('password_cancel');self.assertIsNone(self.b.features.login)
        d=self.call('password_challenge');self.b.qr_generation+=1
        with self.assertRaises(service.Failure):self.call('password_login',dict(username='fixture',password='x',nonce=d['nonce'],challenge='c',validate='v',seccode='s'))
    def test_password_is_not_accepted_without_proof(self):
        with self.assertRaises(service.Failure):service.safe_args('password_login',dict(username='u',password='p',nonce='f'*32))
    def test_cancel_during_login_discards_delayed_credentials(self):
        d=self.call('password_challenge')
        def delayed(op,args):
            self.b.features.dispatch('password_cancel',{},0)
            return self.fixture(op,args)
        self.b.helper_override=delayed
        with patch.object(self.b,'save_cookies') as save:
            with self.assertRaises(service.Failure) as ctx:
                self.call('password_login',dict(username='fixture',password='x',nonce=d['nonce'],challenge='c',validate='v',seccode='s'))
            self.assertEqual(ctx.exception.error,'CANCELED');save.assert_not_called()
    def test_cancel_during_challenge_discards_delayed_token(self):
        def delayed(op,args):
            self.b.features.dispatch('password_cancel',{},0)
            return self.fixture(op,args)
        self.b.helper_override=delayed
        with self.assertRaises(service.Failure) as ctx:self.call('password_challenge')
        self.assertEqual(ctx.exception.error,'CANCELED');self.assertIsNone(self.b.features.login)
    def test_login_invalidates_old_write_intents(self):
        intent=self.intent();d=self.call('password_challenge')
        with patch.object(self.b,'save_cookies'):
            self.call('password_login',dict(username='fixture',password='x',nonce=d['nonce'],challenge='c',validate='v',seccode='s'))
        with self.assertRaises(service.Failure):self.call('interaction',dict(bvid=BV,action='triple',intent=intent))
    def test_changed_account_cannot_receive_stale_relation_intent(self):
        def delayed(op,args):
            self.b.qr_generation+=1
            return self.fixture(op,args)
        self.b.helper_override=delayed
        with self.assertRaises(service.Failure) as ctx:self.intent()
        self.assertEqual(ctx.exception.error,'CANCELED');self.assertEqual(self.b.features.intents,{})
    def test_live_url_and_args(self):
        self.assertEqual(service.safe_args('open',{'text':'https://live.bilibili.com/1234'})['room'],'1234')
        self.assertEqual(service.safe_args('play',{'kind':'live','room':'1234'})['codec'],7)
        with self.assertRaises(service.Failure):service.safe_args('play',{'kind':'live','room':'../xx'})
    def test_listen_boolean(self):
        self.assertTrue(service.safe_args('play',dict(kind='video',bvid=BV,cid='1',listen=True))['listen'])
        with self.assertRaises(service.Failure):service.safe_args('play',dict(kind='video',bvid=BV,cid='1',listen='yes'))
    def test_python35(self):ast.parse((BASE/'client/account_features.py').read_text(encoding='utf-8'),feature_version=(3,5))
    def test_no_fake_feedback(self):
        d=self.call('feature_capabilities');self.assertFalse(d['not_interested'])
        self.assertNotIn('dislike',service.PUBLIC_OPS)
    def test_native_capture_and_test_driver_contract(self):
        from client_results import CAPTURES
        cpp=(BASE/'client/player_v2.cpp').read_text(encoding='utf-8')
        captures=set(re.findall(r'"(player-[a-z0-9-]+)"',cpp.split('static const std::vector<std::string>names={',1)[1].split('};',1)[0]))
        self.assertTrue({n for n in CAPTURES if n.startswith('player-')}.issubset(captures))
        self.assertNotIn('TestCase{',(BASE/'client/BiliFeatureAutomation.qml').read_text(encoding='utf-8'))
        driver=(BASE/'client/PlayerAutomation.qml').read_text(encoding='utf-8')
        step=driver.split('case 41:',1)[1].split('case 42:',1)[0]
        self.assertIn('Math.abs(p.slide_offset||0)>.1',step)
        self.assertLess(step.index('Date.now()-storySettledAt<350'),step.index('storySwipes++'))
        gesture=driver.split('case 64:',1)[1].split('case 65:',1)[0]
        self.assertIn('gestureAttempts<3',gesture)
        self.assertIn('if(!p.gesture_seeking)',gesture)

if __name__=='__main__':unittest.main()
