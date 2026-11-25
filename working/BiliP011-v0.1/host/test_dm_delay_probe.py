import ast,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'client'))
from dm_delay_probe import wait_for_playback
from build_awake_trial import build

class Stop:
    def __init__(self):self.now=0;self.cancel=False
    def wait(self,n):self.now+=n;return self.cancel
    def is_set(self):return self.cancel

class DelayedDanmakuTests(unittest.TestCase):
    def test_waits_for_real_active_position_and_no_wall_sleep(self):
        stop=Stop()
        def read():return dict(player=dict(loaded=True,active=True,paused=False,position=stop.now))
        pos=wait_for_playback(read,lambda:True,stop,lambda:stop.now)
        self.assertGreaterEqual(pos,8);self.assertLess(pos,8.3)
    def test_cancellation_and_deadline(self):
        stop=Stop();self.assertIsNone(wait_for_playback(lambda:{},lambda:False,stop,lambda:stop.now));self.assertEqual(stop.now,0)
        self.assertIsNone(wait_for_playback(lambda:{},lambda:True,stop,lambda:stop.now));self.assertGreaterEqual(stop.now,20)
    def test_paused_and_invalid_state_does_not_release(self):
        for pos,paused in ((float('nan'),False),(float('inf'),False),(True,False),(9,True)):
            stop=Stop()
            self.assertIsNone(wait_for_playback(lambda:dict(player=dict(loaded=True,active=True,paused=paused,position=pos)),lambda:True,stop,lambda:stop.now))
    def test_builder_rejects_probe_without_fixed_explicit_benchmark(self):
        for value in (True,1,7,9,'8',8):
            with self.assertRaises(ValueError):build(pathlib.Path('not-read'),benchmark_danmaku_delay=value)
        for q in (32,64,120):
            with self.assertRaises(ValueError):build(pathlib.Path('not-read'),client=True,automated=True,player_protocol=2,benchmark_quality=q,benchmark_danmaku_delay=8)
    def test_q80_and_q116_reach_media_validation_but_seek_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            missing=pathlib.Path(directory)/'missing'
            for quality in (80,116):
                with self.assertRaises(FileNotFoundError):
                    build(missing,client=True,automated=True,player_protocol=2,benchmark_quality=quality,benchmark_danmaku_delay=8)
                with self.assertRaises(ValueError):
                    build(missing,client=True,automated=True,player_protocol=2,benchmark_quality=quality,benchmark_danmaku_delay=8,benchmark_seek=True)
    def test_probe_is_python35_and_off_by_default(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        ast.parse((base/'client/dm_delay_probe.py').read_text(),feature_version=(3,5))
        source=(base/'client/service.py').read_text(encoding='utf-8')
        self.assertIn('self.benchmark_danmaku_delay = False',source)
        self.assertIn('self.automation and self.protocol==2 and generation==1 and serial==1',source)
        self.assertIn("type(getattr(C,'BENCHMARK_DANMAKU_DELAY',None)) is int",source)
        self.assertIn("getattr(C,'BENCHMARK_QUALITY',None) in (80,116) and not state.benchmark_seek",source)

if __name__=='__main__':unittest.main()
