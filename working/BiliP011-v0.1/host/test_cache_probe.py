import ast,hashlib,json,pathlib,sys,tempfile,unittest
import copy
from unittest.mock import patch
from cache_artifact import PINS,identity,modified_hashes,validate
from cache_trial import PAYLOAD,parse_probe
from cache_pixel_audit import compare
from cache_timing_audit import compare as compare_timing

BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'build'))
from cache_omx_overlay import overlay,replace_once

class CacheProbeTests(unittest.TestCase):
    def test_protocol_exactly_one_record(self):
        self.assertEqual(parse_probe(b'noise\r\nCACHE_DECODE={"passed":true}\r\n'),{'passed':True})
        self.assertEqual(parse_probe(b''),{})
        self.assertEqual(parse_probe(b'CACHE_DECODE={}\nCACHE_DECODE={}\n'),{})
        self.assertEqual(parse_probe(b'CACHE_DECODE=[]\n'),{})

    def test_device_python35_and_safety_gates(self):
        ast.parse(PAYLOAD,feature_version=(3,5))
        for required in ('before=stock_snapshot()','require_private_idle()',
                         'VENDOR_PINS.items()','owned_directory(DIRECTORY)',
                         'child.communicate(timeout=45)','child.poll() is not None',
                         'not stat.S_ISREG','os.rmdir(DIRECTORY)',
                         'stock_unchanged=before==after','vendor_unchanged='):
            self.assertIn(required,PAYLOAD)
        for forbidden in ('killall','rmtree','LD_PRELOAD','remount'):
            self.assertNotIn(forbidden,PAYLOAD)
        controller=(BASE/'host/cache_trial.py').read_text(encoding='utf-8')
        self.assertNotIn("\\nPINS=",controller)
        self.assertIn("exec(compile(raw,HELPER,'exec'))",controller)
        self.assertIn('hashlib.sha256(raw).hexdigest()!=EXPECTED',controller)

    def test_exact_anchors_reject_duplicates_or_missing(self):
        self.assertEqual(replace_once('abc','b','x'),'axc')
        for source in ('ac','abbc'):
            with self.assertRaises(ValueError):replace_once(source,'b','x')

    def test_output_only_scope_and_lifetime(self):
        root=BASE/'third_party/gst-omx-1.14.2-p011/omx'
        source=overlay('gstomx.c',(root/'gstomx.c').read_text())
        for required in ('OMX_DirOutput','OMX_PortDomainVideo','port->index != 1',
                         'nFrameWidth != 1920','nFrameHeight != 1080',
                         'nStride != 1920','nSliceHeight != 1088',
                         'OMX_COLOR_FormatYUV420SemiPlanar'):
            self.assertIn(required,source)
        self.assertEqual(source.count('p011_cache_allocate_begin ('),1)
        self.assertEqual(source.count('p011_cache_allocate_end ('),1)
        self.assertIn('if (tmp == OMX_ErrorNone) p011_cache_forget (cache_base);',source)
        decoder=overlay('gstomxvideodec.c',(root/'gstomxvideodec.c').read_text())
        start=decoder.index('gboolean cache_reading = p011_cache_read_begin')
        half=decoder.index('ret=p011_video_fill_half',start)
        end=decoder.index('p011_cache_read_end',half)
        publish=decoder.index('GST_BUFFER_PTS (outbuf)',end)
        self.assertLess(start,half);self.assertLess(half,end);self.assertLess(end,publish)

    def test_bridge_changes_only_scoped_known_allocation(self):
        source=(BASE/'probes/memion_cache.cpp').read_text()
        for required in ('bool cached=false,scoped=allocation.active','allocation.calls++',
                         'heapmask!=1||flags!=512','if(cached)heapmask=0x80000001u',
                         'DMA_BUF_SYNC_START|DMA_BUF_SYNC_READ','DMA_BUF_SYNC_END|DMA_BUF_SYNC_READ',
                         'errno!=EINTR&&errno!=EAGAIN','errno=result_errno;return result;',
                         'RTLD_NOLOAD','_ZNK6MemIon7getBaseEv','_ZNK6MemIon9getHeapIDEv'):
            self.assertIn(required,source)
        for forbidden in ('mprotect(','mmap(','dup(','/dev/ion','system(','popen('):
            self.assertNotIn(forbidden,source)

    def test_pixel_probe_is_finite_and_has_no_audio_or_window(self):
        source=(BASE/'probes/cache_decode_probe.cpp').read_text()
        for required in ('alarm(35)','30000000','appsink name=sample sync=false',
                         'setrlimit(RLIMIT_CORE','setrlimit(RLIMIT_CPU','setrlimit(RLIMIT_FSIZE',
                         'G_CHECKSUM_SHA256','pts<=previous','unique.size()<200',
                         'stats.read_begin==240','stats.read_end==240',
                         'stats.registered==stats.forgotten','vsp_open()','libraries(root)'):
            self.assertIn(required,source)
        for forbidden in ('pulsesink','autovideosink','SDL_','http://','https://'):
            self.assertNotIn(forbidden,source)

    def test_artifact_checks_binary_source_recipe_and_mock(self):
        sources={'source':'pinned'};modified={'gstomx.c':'one','gstomxvideodec.c':'two'}
        digests={name:hashlib.sha256(body.encode()).hexdigest() for name,body in modified.items()}
        raw=b'\x7fELF\x01'+b'\0'*13+b'\x28\0'+b'x'*20
        binaries={name:hashlib.sha256(raw).hexdigest() for name in ('cache-decode-probe','libgstomx.so')}
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);path=base/'out'/('cache-omx-probe-'+identity(binaries,sources));path.mkdir(parents=True)
            for name in binaries:(path/name).write_bytes(raw)
            (path/'modified-open-source').mkdir()
            for name,body in modified.items():(path/'modified-open-source'/name).write_text(body)
            meta=dict(schema=1,sources=sources,pins=PINS,synthetic_only=True,host_mock_passed=True,
                      binaries=binaries,modified_open_source=digests)
            def save():(path/'build.json').write_text(json.dumps(meta))
            save()
            with patch('cache_artifact.source_hashes',return_value=sources),patch('cache_artifact.modified_hashes',return_value=digests):
                self.assertEqual(validate(base,path),meta)
                meta['host_mock_passed']=False;save()
                with self.assertRaises(ValueError):validate(base,path)
                meta['host_mock_passed']=True;save()
                file=path/'modified-open-source/gstomx.c';file.write_text('different')
                with self.assertRaises(ValueError):validate(base,path)
                file.write_text('one');(path/'cache-decode-probe').write_bytes(raw+b'changed')
                with self.assertRaises(ValueError):validate(base,path)

    def test_recipe_generates_both_corresponding_sources(self):
        self.assertEqual(set(modified_hashes(BASE)),{'gstomx.c','gstomxvideodec.c'})
        self.assertEqual(len(PINS),4)

    def test_pixel_audit_rejects_any_frame_or_lifecycle_difference(self):
        frames=[{'pts_ns':x*16666667,'sha256':hashlib.sha256(str(x).encode()).hexdigest()} for x in range(240)]
        rows=[]
        for mode in ('uncached','cached','uncached'):
            rows.append(dict(mode=mode,artifact='same',fixture_sha256='same',passed=True,
                stock_unchanged=True,vendor_unchanged=True,temporary_directory_removed=True,
                exit=0,timeout=False,playback_passed=False,probe=dict(
                    passed=True,hardware_confirmed=True,eos=True,window_opened=False,
                    network_media=False,stopped=False,cached=mode=='cached',frames=copy.deepcopy(frames),
                    elapsed_ms=1000,cache=dict(active=0,sync_errors=0,ownership_errors=0,registered=20,
                        forgotten=20,read_begin=240,read_end=240,sync_ns=1000,
                        changed_allocations=20 if mode=='cached' else 0,
                        control_allocations=0 if mode=='cached' else 20))))
        self.assertTrue(compare(rows)['identical_pts_and_sha256'])
        self.assertFalse(compare(rows)['full_rate_playback_passed'])
        for mutate in (lambda r:r[1]['probe']['frames'][50].update(sha256='different'),
                       lambda r:r[2]['probe']['frames'][30].update(pts_ns=1),
                       lambda r:r[1]['probe']['cache'].update(sync_errors=1),
                       lambda r:r[1]['probe'].update(pixels_checked=False),
                       lambda r:r[1].update(playback_passed=True),
                       lambda r:r[1].update(fixture_sha256='different')):
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(ValueError):compare(changed)

    def test_timing_audit_is_not_pixel_or_playback_pass(self):
        rows=[]
        for mode,copy_ms,fps in (('uncached',18,45),('cached',1.5,70),('uncached',19,46)):
            rows.append(dict(mode=mode,check='timing',artifact='same',fixture_sha256='same',
                passed=True,stock_unchanged=True,vendor_unchanged=True,temporary_directory_removed=True,
                playback_passed=False,exit=0,timeout=False,probe=dict(
                    passed=True,hardware_confirmed=True,eos=True,stopped=False,network_media=False,
                    window_opened=False,pixels_checked=False,cached=mode=='cached',hash_ms=0,
                    frames=[dict(pts_ns=x*16666667,sha256='') for x in range(240)],
                    sample_span_ms=239000/fps,unclocked_sample_fps=fps,elapsed_ms=6000,
                    profile=dict(copy_count=240,fill_count=240,copy_wall_ns=copy_ms*240e6,fill_wall_ns=copy_ms*240e6),
                    cache=dict(active=0,sync_errors=0,ownership_errors=0,registered=20,forgotten=20,
                               read_begin=240,read_end=240,sync_ns=1000,
                               changed_allocations=20 if mode=='cached' else 0,
                               control_allocations=0 if mode=='cached' else 20))))
        result=compare_timing(rows)
        self.assertTrue(result['cache_copy_improvement_observed'])
        self.assertTrue(result['cache_throughput_improvement_observed'])
        self.assertFalse(result['full_rate_playback_passed'])
        for mutate in (lambda r:r[1]['probe'].update(hash_ms=1),
                       lambda r:r[1]['probe'].update(pixels_checked=True),
                       lambda r:r[1]['probe']['profile'].update(copy_count=239),
                       lambda r:r[1]['probe'].update(unclocked_sample_fps=500)):
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(ValueError):compare_timing(changed)

if __name__=='__main__':unittest.main()
