"""Synthetic data only: library, media metadata and cloud resume boundaries."""
import copy
import tempfile
import unittest
from pathlib import Path
from test_client import service

BV='BV1Da411Y7U4'
class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);(root/'account').mkdir()
        self.data={};self.calls=[]
        self.b=service.Backend(str(root),'','',str(root/'account'),{},helper=self.helper)
    def tearDown(self):self.b.close();self.temp.cleanup()
    def helper(self,op,args):self.calls.append((op,args));return copy.deepcopy(self.data)
    def call(self,op,a):return self.b.dispatch(op,service.safe_args(op,a),self.b.qr_generation)
    def test_all_categories_validate(self):
        for c in service.catalog_features.CATEGORIES:
            self.assertEqual(service.safe_args('catalog_library',dict(category=c,id='123',bvid=BV))['category'],c)
    def test_reject_unbounded_and_arbitrary_contracts(self):
        for a in ({'category':'shell'},{'category':'popular','page':True},{'category':'popular','page':101},{'category':'up','id':'1;rm'},{'category':'related','bvid':'bad'}):
            with self.assertRaises(service.Failure):service.safe_args('catalog_library',a)
    def test_private_fields_stripped(self):
        self.data={'items':[dict(kind='video',bvid=BV,title='测试',mid='123',cover='https://i0.hdslb.com/example.jpg',token='NEVER',url='NEVER')],'more':True}
        r=self.call('catalog_library',{'category':'popular'})
        self.assertTrue(r['items'][0]['playable']);self.assertEqual(r['items'][0]['mid'],'123')
        self.assertNotIn('NEVER',str(r));self.assertNotIn('url',r['items'][0]);self.assertTrue(r['more'])
    def test_deleted_record_not_playable(self):
        self.data={'items':[{'kind':'video','title':'已失效'}]}
        self.assertFalse(self.call('catalog_library',{'category':'watchlater'})['items'][0]['playable'])
    def test_account_change_drops_result(self):
        self.data={'items':[]};self.b.qr_generation=2
        with self.assertRaises(service.Failure):self.b.dispatch('catalog_library',{'category':'folders','page':1},1)
    def test_metadata_filters_private_url_and_invalid_times(self):
        self.data={'tracks':[{'id':'10','label':'中文','url':'NEVER','ai':True}], 'chapters':[dict(start=2,end=8,title='第二章'),dict(start=-1,end=8),dict(start=float('nan'),end=8),dict(start=0,end=2,title='第一章')]}
        r=self.call('player_metadata',{'bvid':BV,'cid':'3'})
        self.assertEqual([c['start'] for c in r['chapters']],[0,2]);self.assertNotIn('NEVER',str(r));self.assertTrue(r['tracks'][0]['ai'])
    def test_subtitle_bounded_sorted(self):
        self.data={'cues':[dict(start=5,end=9,text='二'),dict(start=1,end=3,text='一'),dict(start=5,end=2,text='无效')]}
        r=self.call('player_subtitle',{'bvid':BV,'cid':'3','track':'1'})
        self.assertEqual([c['text'] for c in r['cues']],['一','二'])
        self.data={'cues':[{}]*12001}
        with self.assertRaises(service.Failure):self.call('player_subtitle',{'bvid':BV,'cid':'3','track':'1'})
    def test_resume_explicit_start_validated(self):
        args=dict(kind='video',bvid=BV,cid='3',start=91.5)
        self.assertEqual(service.safe_args('play',args)['start'],91.5)
        for bad in (True,-1,float('nan'),604801,'3'):
            with self.assertRaises(service.Failure):service.safe_args('play',dict(args,start=bad))
    def test_cloud_cid_preserved(self):
        self.data={'items':[dict(kind='video',bvid=BV,cid='33',position=72,playable=True)],'cursor':{'max':'0','view_at':'0','business':'archive'}}
        r=self.call('account_history',{})['items'][0]
        self.assertEqual(r['cid'],'33');self.assertEqual(r['position'],72)
    def test_queue_source_whitelist(self):
        args=dict(kind='video',bvid=BV,cid='3')
        self.assertEqual(service.safe_args('play',dict(args,queue_source=dict(category='parts',kind='video',bvid=BV)))['queue_source']['category'],'parts')
        with self.assertRaises(service.Failure):service.safe_args('play',dict(args,queue_source={'category':'arbitrary'}))
    def test_python35_syntax(self):
        import ast
        path=Path(service.__file__).with_name('catalog_features.py')
        ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,5))
if __name__=='__main__':unittest.main()
