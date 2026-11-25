import ast,base64,pathlib,unittest,zlib
from ion_copy_trial import IDLE_GATE,PAYLOAD,SOURCES,artifact_name,source_hashes

class IonCopyTests(unittest.TestCase):
    def test_payload_python35_and_bounded_cleanup(self):
        ast.parse(IDLE_GATE+'\n'+PAYLOAD,feature_version=(3,5))
        for required in ('communicate(timeout=35)','child.terminate()','communicate(timeout=5)',
                         'child.kill()','communicate(timeout=3)',"os.listdir(DIRECTORY)!=['ion-copy-probe']",'before==after','require_private_idle()','stdout_raw=o,stderr_raw=e','finally:'):
            self.assertIn(required,PAYLOAD)
        for forbidden in ('killall','remount','/usr/bin/Z03','/dev/sprd_vsp'):
            self.assertNotIn(forbidden,PAYLOAD)
    def test_probe_is_cpu_only_and_does_not_skip_sync(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'probes/ion_copy_probe.cpp').read_text()
        self.assertIn('alarm(25)',source)
        self.assertIn('source(1920*1088*3/2)',source)
        self.assertIn('for(unsigned flags:{0u,unsigned(ION_FLAG_CACHED),0u})',source)
        self.assertIn('output!=expected',source)
        for access in ('RW','READ'):
            self.assertIn('DMA_BUF_SYNC_START|DMA_BUF_SYNC_'+access,source)
            self.assertIn('DMA_BUF_SYNC_END|DMA_BUF_SYNC_'+access,source)
        self.assertNotIn('/dev/sprd_vsp',source)
        self.assertNotIn('SDL_',source)
    def test_sources_and_no_playback_claim(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(set(source_hashes(base)),set(SOURCES))
        self.assertIn("result['playback_passed']=False",pathlib.Path(__file__).with_name('ion_copy_trial.py').read_text())

    def test_identity_includes_controller_and_canonical_source_order(self):
        a={'probe':'a','controller':'b'}
        self.assertEqual(artifact_name('c',a),artifact_name('c',dict(reversed(list(a.items())))))
        self.assertNotEqual(artifact_name('c',a),artifact_name('c',dict(a,controller='changed')))
        self.assertNotEqual(artifact_name('c',a),artifact_name('different',a))

    def test_private_processes_are_rejected_before_launch(self):
        class FakeOS:
            def listdir(self,path):return ['4','5','not-a-pid']
            def getpid(self):return 4
            def readlink(self,path):return '/mnt/data/p011-toolbox/other-probe'
        import io
        with self.assertRaisesRegex(ValueError,'Another private trial'):
            exec(IDLE_GATE,{'os':FakeOS(),'open':lambda *args:io.BytesIO(b'probe')})

if __name__=='__main__':unittest.main()
