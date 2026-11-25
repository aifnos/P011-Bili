"""Host-only typed danmaku, Story cursors and codec/quality contracts."""
import ast
import html
import json
import pathlib
import sys
import unittest
import threading
BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'client'))
sys.path.insert(0,str(BASE.parents[1]/'working/ToolboxNext-v0.5.1-native/runtime'))
import danmaku, service
from story import StoryFeed

def xml(mode,text='hello',size=25,color=0xffffff):
    return ('<i><d p="1,%d,%d,%d,0,0,private-author,99">%s</d></i>'%(mode,size,color,html.escape(text))).encode()

class UpgradeTests(unittest.TestCase):
    def test_all_ordinary_types(self):
        for mode in range(1,7):
            r=danmaku.decode(xml(mode,size=36,color=0x123456))['items'][0]
            self.assertEqual((r['mode'],r['size'],r['color']),(mode,36,0x123456))
            self.assertNotIn('private-author',str(r))
    def test_advanced_is_data(self):
        a=[.1,.2,'1-0',5,'comma, quote " and\nline',30,45,.9,.8,3000,200,1,'FontName',1]
        r=danmaku.decode(xml(7,json.dumps(a)))['items'][0]
        self.assertEqual(r['text'],a[4]);self.assertTrue(r['advanced']['relative']);self.assertEqual(r['advanced']['move'],3)
    def test_advanced_path(self):
        a=[20,30,'0.5-1',4,'path',0,0,200,150,3000,0,1,'',1,'M20,30L100,100L200,150']
        self.assertEqual(len(danmaku.decode(xml(7,json.dumps(a)))['items'][0]['advanced']['path']),3)
    def test_bad_advanced(self):
        for a in ('javascript:alert(1)','[]','[0,0,"1-0",99999,"x"]','[0,0,"1-0",5,"x",{},0]'):
            d=danmaku.decode(xml(7,a));self.assertEqual(d['items'],[]);self.assertEqual(d['unsupported'],1)
    def test_code_not_executed(self):
        for mode in (8,9):
            d=danmaku.decode(xml(mode,'arbitrary script'))
            self.assertEqual(d['items'],[]);self.assertEqual(d['unsupported'],1)
    def test_merge_not_invented(self):
        raw=xml(1).replace(b'</i>',xml(1)[3:])
        d=danmaku.decode(raw);self.assertEqual(len(d['items']),2);self.assertFalse(d['official_merge_count'])
        self.assertTrue(all('count' not in r for r in d['items']))
    def test_security(self):
        for raw in (b'<!DOCTYPE i><i></i>',b'<!ENTITY i><i></i>',b'x'*4194305):
            with self.assertRaises(ValueError):danmaku.decode(raw)
    def test_quality_codec_args(self):
        args={'kind':'video','bvid':'BV1Da411Y7U4','cid':'123'}
        for q in (0,6,16,32,64,80,120,125,126,127,333,65535):
            for c in service.CODECS:self.assertEqual(service.safe_args('play',dict(args,quality=q,codec=c))['codec'],c)
        for v in (True,5,99,'7'):
            with self.assertRaises(service.Failure):service.safe_args('play',dict(args,codec=v))
    def test_story_start(self):
        d=service.safe_args('play',{'story':True});self.assertTrue(d['portrait']);self.assertTrue(d['story'])
    def test_story_cursor_and_history(self):
        calls=[]
        def fetch(args):
            calls.append(dict(args));p=args['page']
            return {'items':[{'bvid':'BV000000000'+str(p),'cid':str(p)}],'source':'official-story','offset':str(p*10),'more':True}
        f=StoryFeed(fetch)
        for _ in range(50):i,r=f.target(1);f.commit(i)
        self.assertLessEqual(len(f.rows),34);self.assertEqual(calls[1]['offset'],'10');self.assertEqual(f.base+f.index,49)
        i,r=f.target(-1);self.assertEqual(r['cid'],'49')
    def test_story_no_fake_fallback(self):
        f=StoryFeed(lambda a:{'items':[],'source':'recommend','more':True})
        with self.assertRaises(ValueError):f.target(1)
    def test_story_prefetch_next_batch_does_not_commit(self):
        calls=[]
        def fetch(a):
            calls.append(a['page']);return dict(source='official-story',items=[dict(bvid='BV0000000001',cid=str(a['page']))],offset=str(a['page']*10),more=True)
        f=StoryFeed(fetch);i,_=f.target(1);f.commit(i)
        row=f.ahead(0,threading.Event());self.assertEqual(row['cid'],'2');self.assertEqual(f.index,0)
        self.assertEqual(calls,[1,2]);self.assertEqual(f.target(1)[1]['cid'],'2');self.assertEqual(calls,[1,2])
    def test_story_canceled_fetch_does_not_consume_cursor(self):
        cancel=threading.Event()
        def fetch(a,c):c.set();return dict(source='official-story',items=[dict(bvid='BV0000000001',cid='1')],offset='20',more=True)
        f=StoryFeed(None,fetch)
        with self.assertRaises(ValueError):f.ahead(-1,cancel)
        self.assertEqual((f.page,f.offset,f.index,len(f.rows)),(1,'',-1,0))
    def test_story_dedup_and_limit(self):
        n=[0]
        def fetch(a):n[0]+=1;return {'items':[{'bvid':'one','cid':'1'}],'source':'official-story','offset':'','more':True}
        f=StoryFeed(fetch);i,r=f.target(1);f.commit(i)
        with self.assertRaises(ValueError):f.target(1)
        self.assertEqual(n[0],4)
    def test_python35(self):
        for name in ('danmaku.py','story.py','service.py'):ast.parse((BASE/'client'/name).read_text(encoding='utf-8'),feature_version=(3,5))

if __name__=='__main__':unittest.main()
