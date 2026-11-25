"""Synthetic byte-range roundtrips only; no device/account/CDN requests."""
import ast
import pathlib
import sys
import tempfile
import threading
import unittest
import http.client
import subprocess
from unittest import mock
BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'client'));sys.path.insert(0,str(BASE.parent/'ToolboxNext-v0.5.1-native/runtime'))
from media_relay import MediaRelay,byte_range,ClientDisconnected,CountedSlots

class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        self.backend=type('Backend',(),dict(root=str(self.root),lock=threading.RLock(),stopping=threading.Event(),children=set(),api='private-helper',env=None))()
        self.relay=MediaRelay(self.backend);self.payload=bytes(range(256))*400
        self.prefix=self.root/'synthetic.head';self.prefix.write_bytes(self.payload[:32768])
        self.name='a'*16+'-v';self.relay.rows[self.name]=dict(path=str(self.prefix),size=32768,total=len(self.payload),url='not-exposed')
        self.calls=[]
        self.pipe_stream=self.relay.stream
        def stream(row,start,end,request=None):self.calls.append((start,end));yield self.payload[start:end+1]
        self.relay.stream=stream
    def tearDown(self):self.relay.close();self.tmp.cleanup()
    def request(self,headers=None,path=None):
        c=http.client.HTTPConnection(self.relay.host,timeout=3)
        try:
            c.request('GET',path or self.relay.path+self.name,headers=headers or {});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def test_prefix_only_does_not_touch_network(self):
        status,h,data=self.request({'Range':'bytes=0-999'})
        self.assertEqual((status,data),(206,self.payload[:1000]));self.assertEqual(h['Content-Range'],'bytes 0-999/102400');self.assertEqual(self.calls,[])
    def test_prefix_tail_boundary_and_open_range(self):
        status,h,data=self.request({'Range':'bytes=32000-'})
        self.assertEqual((status,data),(206,self.payload[32000:]));self.assertEqual(self.calls,[(32768,102399)])
        self.assertEqual(self.relay.stats['prefix_bytes'],768)
    def test_seek_beyond_prefix(self):
        self.assertEqual(self.request({'Range':'bytes=50000-50999'})[2],self.payload[50000:51000]);self.assertEqual(self.calls,[(50000,50999)])
    def test_whole_stream_is_not_truncated_to_prefix(self):
        status,h,data=self.request();self.assertEqual(status,200);self.assertEqual(data,self.payload)
    def test_invalid_ranges_and_origins(self):
        for v in ('bytes=1-2,4-5','bytes=-50','bytes=102400-','bytes=9-1','bytes=0-999999999999999999'):
            self.assertEqual(self.request({'Range':v})[0],416)
        for h in ({'Origin':'http://example.com'},{'Sec-Fetch-Site':'same-origin'},{'Host':'example.com'}):self.assertEqual(self.request(h)[0],403)
        self.assertEqual(self.request(path='/wrong/'+self.name)[0],403)
        self.assertEqual(self.request(path=self.relay.path+'../secret')[0],404)
    def test_unregistered_and_removed_files(self):
        self.relay.remove('a'*16);self.assertEqual(self.request()[0],404)
    def test_out_of_range_end_is_clamped(self):self.assertEqual(byte_range('bytes=100-1000',500),(100,499,206))
    def test_native_ready_header_and_media_share_buffer(self):
        # Exercise the actual pipe reader, not the HTTP fixture's fake tail.
        # A single write coalesces READY and binary bytes into readline's buffer.
        original=subprocess.Popen
        script="import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'READY\\n'+bytes(range(256))*400);sys.stdout.buffer.flush()"
        def child(*args,**kwargs):return original([sys.executable,'-c',script],**kwargs)
        with mock.patch('media_relay.subprocess.Popen',side_effect=child):
            data=b''.join(self.pipe_stream({'url':'not-exposed','total':len(self.payload)},0,len(self.payload)-1))
        self.assertEqual(data,self.payload);self.assertEqual(self.backend.children,set())
    def test_short_native_pipe_is_reaped(self):
        original=subprocess.Popen
        script="import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b'READY\\nshort');sys.stdout.buffer.flush()"
        def child(*args,**kwargs):return original([sys.executable,'-c',script],**kwargs)
        with mock.patch('media_relay.subprocess.Popen',side_effect=child),self.assertRaises(OSError):
            b''.join(self.pipe_stream({'url':'not-exposed','total':100},0,99))
        self.assertEqual(self.backend.children,set())
    def test_posix_disconnected_decoder_interrupts_stalled_pipe(self):
        p=type('P',(),dict(stdout=object()))();request=object()
        with mock.patch('media_relay.os.name','posix'),mock.patch('media_relay.select.select',return_value=([request],[],[])),self.assertRaises(ClientDisconnected):
            self.relay.read_pipe(p,100,request)
    def test_stopping_does_not_wait_for_network_timeout(self):
        self.backend.stopping.set()
        with self.assertRaises(ClientDisconnected):self.relay.read_pipe(None,100,None)
    def test_bounded_worker_admission_and_cleanup_grace(self):
        slots=CountedSlots(self.relay,1);self.assertTrue(slots.acquire(False))
        timer=threading.Timer(.02,slots.release);timer.start()
        try:self.assertTrue(slots.acquire(False))
        finally:timer.join()
        self.assertFalse(slots.acquire(False));slots.release()
        self.assertEqual(self.relay.stats['busy_rejected'],1)
        self.assertEqual(self.relay.stats['workers_peak'],1)
    def test_python35(self):ast.parse((BASE/'client/media_relay.py').read_text(encoding='utf-8'),feature_version=(3,5))

if __name__=='__main__':unittest.main()
