"""Host-only gates for the source-built diagnostic plugin."""
import hashlib,json,pathlib,tempfile,unittest
from private_omx_artifact import source_hashes,validate

class PrivateOmxTests(unittest.TestCase):
    def fixture(self,base):
        for name in ('third_party/gst-omx-1.14.2-p011/COPYING','third_party/gst-omx-1.14.2-p011/omx/p011_copy.h','build/build_omx_probe.py','host/private_omx_artifact.py','host/omx_parallel_test.c','host/omx_half_test.cpp','client/hardware_pack.hpp','client/hardware_output.hpp'):
            path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        raw=bytearray(32);raw[:5]=b'\x7fELF\x01';raw[18:20]=(40).to_bytes(2,'little');digest=hashlib.sha256(raw).hexdigest()
        path=base/'out'/('omx-probe-'+digest[:16]);path.mkdir(parents=True)
        (path/'libgstomx.so').write_bytes(raw)
        (path/'build.json').write_text(json.dumps(dict(schema=4,copy_mode=1,neon=True,fused_half=False,host_sanitizer_checks=38056,half_sanitizer_checks=2350,sha256=digest,sources=source_hashes(base))))
        return path
    def test_exact_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);self.assertTrue(validate(base,path)[1]['neon'])
    def test_changed_source_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);(base/'third_party/gst-omx-1.14.2-p011/omx/p011_copy.h').write_text('changed')
            with self.assertRaises(ValueError):validate(base,path)
    def test_changed_binary_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);(path/'libgstomx.so').write_bytes(b'bad')
            with self.assertRaises(ValueError):validate(base,path)
    def test_unknown_mode_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);meta=json.loads((path/'build.json').read_text());meta['neon']='yes';(path/'build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):validate(base,path)
    def test_private_path_only_in_diagnostic_compile(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        code=(base/'client/hardware_client.hpp').read_text()
        # More than one diagnostic block now exists. Check the actual
        # environment writes, not whichever block happens to appear last.
        scopes=[];guarded=[]
        for line in code.splitlines():
            line=line.strip()
            if line.startswith('#ifdef '):scopes.append(line.split()[1])
            elif line.startswith(('#if ','#ifndef ')):scopes.append(line)
            elif line.startswith(('#else','#elif')):
                self.assertTrue(scopes);scopes[-1]='alternate:'+line
            elif line.startswith('#endif'):
                self.assertTrue(scopes);scopes.pop()
            elif 'env.push_back("GST_PLUGIN_PATH_1_0="+root)' in line or 'env.push_back("LD_PRELOAD=' in line:
                self.assertIn('P011_PRIVATE_OMX_PROBE',scopes)
                guarded.append(line)
        self.assertEqual(len(guarded),2)
        self.assertEqual(scopes,[])
        self.assertIn('if(request.value("private_omx_probe",false))',guarded[0])
        self.assertIn('LD_PRELOAD="+root+"/libmemion-observer.so"',guarded[1])
        source=(base/'probes/hardware_seek_probe.cpp').read_text()
        self.assertIn('if(!hw.private_plugin_loaded())report["passed"]=false',source)
    def test_only_two_output_copy_sites_changed(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'third_party/gst-omx-1.14.2-p011/omx/gstomxvideodec.c').read_text()
        self.assertEqual(source.count('p011_copy_planes ('),3)
        self.assertIn('#ifdef P011_OMX_FUSED_HALF',source)
        self.assertIn('GST_OMX_HACK_NO_DISABLE_OUTPORT',source)
    def test_profile_is_numeric_readonly_and_per_frame(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'third_party/gst-omx-1.14.2-p011/omx/p011_profile.h').read_text()
        self.assertIn('CLOCK_THREAD_CPUTIME_ID',source)
        self.assertIn('CLOCK_MONOTONIC',source)
        self.assertIn('cleanup(p011_profile_end)',source)
        self.assertIn('g_mutex_lock (&p011_profile_lock)',source)
        for forbidden in ('fopen(', 'system(', '/mnt/', 'http'):
            self.assertNotIn(forbidden,source)
        dec=(base/'third_party/gst-omx-1.14.2-p011/omx/gstomxvideodec.c').read_text()
        self.assertEqual(dec.count('P011_PROFILE (COPY)'),3)
        self.assertIn('GST_TYPE_STRUCTURE, G_PARAM_READABLE',dec)
        self.assertLess(dec.index('P011_PROFILE (COPY)',dec.index('/* Different strides */')),dec.index('for (p = 0;',dec.index('/* Different strides */')))
    def test_parallel_completion_precedes_release_and_free_joins(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h').read_text()
        self.assertIn('while(part->busy)pthread_cond_wait',source)
        self.assertIn('pthread_join(w->thread,NULL)',source)
        self.assertIn('if(bytes>=524288)',source)
        self.assertIn('if(!*owner)*owner=p011_copy_worker_new()',source)
        self.assertNotIn('pthread_detach',source)
        build=(base/'build/build_omx_probe.py').read_text()
        self.assertIn('-fsanitize=address,undefined',build)
    def test_three_thread_mode_is_exact_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);meta=json.loads((path/'build.json').read_text())
            meta.update(copy_mode=3,neon=False);(path/'build.json').write_text(json.dumps(meta))
            self.assertEqual(validate(base,path)[1]['copy_mode'],3)
            meta.update(copy_mode=4);(path/'build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):validate(base,path)
        source=(pathlib.Path(__file__).resolve().parents[1]/'third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h').read_text()
        self.assertIn('threads=w->second?3:2',source)
        self.assertIn('if(w->second)p011_copy_worker_free(w->second)',source)

    def test_fused_mode_requires_separate_identity_and_pixel_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);path=self.fixture(base);meta=json.loads((path/'build.json').read_text())
            meta.update(copy_mode=4,neon=False,fused_half=True);(path/'build.json').write_text(json.dumps(meta))
            self.assertTrue(validate(base,path)[1]['fused_half'])
            meta['half_sanitizer_checks']=0;(path/'build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):validate(base,path)

    def test_fused_caps_are_honest_and_production_requires_explicit_pair(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'third_party/gst-omx-1.14.2-p011/omx/gstomxvideodec.c').read_text()
        self.assertEqual(source.count('state = p011_video_output_state (self,'),2)
        self.assertIn('"p011-copy-scale",G_TYPE_INT,2',source)
        self.assertIn('gst_buffer_memset(outbuf,0,0,size)',source)
        self.assertIn('self->use_buffers = FALSE',source)
        worker=(base/'client/hardware_worker.cpp').read_text()
        self.assertIn('if(bool(half_capable)!=fused_half)throw 41',worker)
        self.assertIn('p011_hw::fused_output_valid',worker)
        self.assertIn("(omx['copy_mode']==4)!=('--fused-copy' in sys.argv)",(base/'build/build_strip_player.py').read_text())
        guard=worker.split('static bool bundled_omx_path',1)[1].split('static void private_profile',1)[0]
        self.assertIn('#ifdef P011_BUNDLED_OMX',guard)
        self.assertIn('readlink("/proc/self/exe"',guard)
        self.assertIn('expected==filename',guard)
        self.assertIn('!S_ISREG(info.st_mode)',guard)
        self.assertNotIn('request.',guard)

if __name__=='__main__':unittest.main()
