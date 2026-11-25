"""Host tests; distinct module name from the container-only mock runner."""
import copy,hashlib,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
from cache_artifact import PINS
from output_cache_artifact import identity,validate
from performance_trial import output_cache_verified
BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'build'))
from cache_omx_overlay import overlay

class OutputCacheTests(unittest.TestCase):
    def test_fallback_requires_all_geometry_and_vendor_conditions(self):
        source=overlay('gstomx.c',(BASE/'third_party/gst-omx-1.14.2-p011/omx/gstomx.c').read_text(encoding='utf-8'),fallback=True)
        for required in ('p011_cache_enabled ()','port->index == 1','nBufferSize == 3133440',
                         'nFrameWidth == 1920','nFrameHeight == 1080','nStride == 1920','nSliceHeight == 1088',
                         'p011_cache_output_begin (port->port_def.nBufferSize, cache_eligible)',
                         'OMX_AllocateBuffer (comp->handle','p011_cache_allocate_end ('):
            self.assertIn(required,source)
        bridge=(BASE/'probes/memion_cache.cpp').read_text(encoding='utf-8')
        self.assertIn('scoped=scoped&&allocation.managed;',bridge)
        self.assertIn('if(record->managed&&!synchronize',bridge)
        self.assertIn('stats.fallback_registered++',bridge)
        self.assertIn('if(!record||record->reading||record->size!=size)',bridge)

    def test_runtime_vendor_gate_is_the_same_fixed_pin_set(self):
        source=(BASE/'client/hardware_cache_gate.hpp').read_text(encoding='utf-8')
        for name,sha in PINS.items():self.assertIn('"'+name+'","'+sha+'"',source)
        self.assertIn('G_CHECKSUM_SHA256',source);self.assertIn('16*1024*1024',source)
        self.assertIn('before.st_ino==after.st_ino',source)
        self.assertIn('/bili-media/[a-f0-9]{16}/bin/bili-hw',source)
        self.assertNotIn('O_WRONLY',source);self.assertNotIn('request',source.split('namespace p011_hw {',1)[1])

    def rows(self,mode):
        out=[]
        for n in range(6):
            state=dict(active=True,loaded=True,position=6+n,hardware_verified=True,hardware_private_plugin=True,
                hardware_cache_feature=True,hardware_cache_vendor_verified=True,hardware_output_cache_enabled=mode=='cached',
                hardware_cache_sync_errors=0,hardware_cache_ownership_errors=0,hardware_cache_changed_allocations=20 if mode=='cached' else 0,
                source_width=1920 if mode=='cached' else 1280,source_height=1080 if mode=='cached' else 720)
            prefix='hardware_cache_' if mode=='cached' else 'hardware_cache_fallback_'
            state[prefix+'read_begin']=100+n*30;state[prefix+'registered']=20;out.append(dict(player=state))
        return out

    def test_real_cache_and_fallback_require_growing_telemetry(self):
        for mode in ('cached','fallback'):
            self.assertTrue(output_cache_verified(self.rows(mode),mode))
            self.assertFalse(output_cache_verified(self.rows(mode)[:4],mode))
            self.assertFalse(output_cache_verified(self.rows(mode),'fallback' if mode=='cached' else 'cached'))
        for key,value in (('hardware_cache_vendor_verified',False),('hardware_cache_read_begin',100),
                          ('hardware_cache_sync_errors',1),('source_width',1280)):
            rows=self.rows('cached');rows[-1]['player'][key]=value
            self.assertFalse(output_cache_verified(rows,'cached'))

    def test_bundle_identity_includes_corresponding_source_and_safe_fallback(self):
        raw=b'\x7fELF\x01'+b'\0'*13+b'\x28\x00'+b'x'*40
        sha=hashlib.sha256(raw).hexdigest();sources={'one':'fixed'};body=b'generated source'
        modified={'gstomx.c':hashlib.sha256(body).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);out=base/'out'/identity(sha,sources);out.mkdir(parents=True)
            (out/'libgstomx.so').write_bytes(raw);(out/'modified-open-source').mkdir();(out/'modified-open-source/gstomx.c').write_bytes(body)
            meta=dict(schema=1,sources=sources,pins=PINS,sha256=sha,copy_mode=4,host_mock_passed=True,
                      unverified_geometry_uncached=True,cached_geometry=[1920,1080,1920,1088,3133440],modified_open_source=modified)
            def save():(out/'build.json').write_text(json.dumps(meta))
            with patch('output_cache_artifact.source_hashes',return_value=sources),patch('output_cache_artifact.modified_hashes',return_value=modified):
                save();self.assertEqual(validate(base,out)[1],meta)
                meta['unverified_geometry_uncached']=False;save()
                with self.assertRaises(ValueError):validate(base,out)
                meta['unverified_geometry_uncached']=True;save();(out/'modified-open-source/gstomx.c').write_bytes(b'changed')
                with self.assertRaises(ValueError):validate(base,out)

    def test_export_is_explicit_and_default_is_reviewed_bundle(self):
        worker=(BASE/'build/build_hardware.py').read_text(encoding='utf-8')
        self.assertIn('cached_output=False',worker);self.assertIn('cached_output and (not bundled or cache_probe)',worker)
        builder=(BASE/'build/build_strip_player.py').read_text(encoding='utf-8')
        self.assertIn("cached_output='--cached-output' in sys.argv",builder)
        self.assertIn("meta['bundled_omx']['output_cache']=True",builder)
        self.assertIn('media-e4ccc8fa53004efb',(BASE/'host/client_oneclick.py').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
