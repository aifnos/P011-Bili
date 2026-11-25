import json,struct,unittest,zlib,sys
from unittest.mock import patch
from test_client import BASE
sys.path.insert(0,str(BASE/'client'))
import live_danmaku as live
class LiveTests(unittest.TestCase):
    def test_auth_and_chat(self):
        message=dict(cmd='DANMU_MSG',info=[[0,1,25,0xff7299],'测试'])
        packets=live.unpack(live.packet(8,b'{"code":0}')+live.packet(5,json.dumps(message).encode()))
        self.assertEqual(packets[0],(8,{'code':0}));self.assertEqual(live.chat(packets[1][1]),{'text':'测试','color':0xff7299})
    def test_zlib(self):
        data=zlib.compress(live.packet(8,b'{"code":0}'))
        self.assertEqual(live.unpack(struct.pack('>IHHII',len(data)+16,16,2,5,1)+data),[(8,{'code':0})])
    def test_bombs_and_truncated(self):
        bomb=zlib.compress(b'A'*(live.LIMIT+1))
        for data in (b'bad',struct.pack('>IHHII',len(bomb)+16,16,2,5,1)+bomb,struct.pack('>IHHII',99,16,0,5,1)):
            with self.assertRaises(ValueError):live.unpack(data)
    def test_partial_fragment_ping(self):
        frames=live.Frames();self.assertEqual(frames.feed(b'\x02\x02ab\x89'),[])
        self.assertEqual(frames.feed(b'\x01x\x80\x02cd'),[(9,b'x'),(2,b'abcd')])
    def test_boundaries(self):
        for server in ({'host':'127.0.0.1','port':443},{'host':'evil.test','port':443},{'host':'broadcastlv.chat.bilibili.com','port':80}):
            with self.assertRaises(ValueError):live.connect(server,None)
        for raw in (b'\x82\x80',b'\xc2\x00',b'\x89\x7e\x01\x00'):
            with self.assertRaises(ValueError):live.Frames().feed(raw)
    def test_masking_and_privacy(self):
        payload=b'private';frame=live.masked(2,payload);mask=frame[2:6]
        self.assertEqual(bytes(c^mask[i%4] for i,c in enumerate(frame[6:])),payload)
        self.assertIsNone(live.chat({'cmd':'SEND_GIFT','info':[]}))
    def test_official_2245_port_reaches_tls(self):
        for port in (443,2245):
            with patch.object(live.socket,'create_connection',side_effect=OSError('fixture')) as dial:
                with self.assertRaises(OSError):live.connect({'host':'broadcastlv.chat.bilibili.com','port':port},None)
                dial.assert_called_once_with(('broadcastlv.chat.bilibili.com',port),timeout=5)
    def test_python35(self):
        import ast
        ast.parse((BASE/'client/live_danmaku.py').read_text(encoding='utf-8'),feature_version=(3,5))
if __name__=='__main__':unittest.main()
