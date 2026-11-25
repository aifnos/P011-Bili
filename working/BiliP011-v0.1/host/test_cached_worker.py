import ast,copy,hashlib,json,pathlib,tempfile,unittest
from unittest.mock import patch
from cached_seek_trial import payload,assess
from cached_worker_artifact import validate,identity,PINS,BINS

BASE=pathlib.Path(__file__).resolve().parents[1]

class CachedWorkerTests(unittest.TestCase):
    def fixture(self,mode='cached'):
        final=dict(cache_final=True,cache_active=0,cache_registered=20,cache_forgotten=20,
                   cache_read_begin=300,cache_read_end=300,cache_sync_errors=0,cache_ownership_errors=0,
                   cache_changed_allocations=20 if mode=='cached' else 0,
                   cache_control_allocations=0 if mode=='cached' else 20)
        return dict(stock_unchanged=True,factory_config_unchanged=True,cache_vendor_unchanged=True,
                    owned_probe_directory_removed=True,cache_worker_preflight=True,child_exit=0,leftover_workers=0,
                    probe=dict(passed=True,cache_final=final,worker_status=dict(output_cache_probe=True,
                        output_cache_enabled=mode=='cached',encoded_nonref_skipped=0),
                        rate=dict(source_fps=60,consumed_fps=60,elapsed_seconds=12,drops=0,decoder_drops=0)))

    def test_payload_py35_separate_pins_and_preflight_process(self):
        source=payload();ast.parse(source,feature_version=(3,5))
        for value in ('VENDOR_PINS.items()',"init['output_cache_mode']=CACHE_MODE",
                      "(init['width'],init['height'])!=(1920,1080)",
                      "[DIRECTORY+'/bili-hw','--preflight']",'trial.child_limits(pre_parent)',
                      "report['cache_vendor_unchanged']",'def numeric(x)',"'cached-helper.py'"):
            self.assertIn(value,source)
        self.assertNotIn('ctypes.CDLL',source)
        self.assertNotIn('PINS=',source)

    def test_final_cache_evidence_is_required(self):
        for mode in ('cached','uncached'):
            self.assertTrue(assess(self.fixture(mode),mode,'seek')['passed'])
        for mutate in (lambda r:r['probe'].pop('cache_final'),
                       lambda r:r['probe']['cache_final'].update(cache_active=1),
                       lambda r:r['probe']['cache_final'].update(cache_sync_errors=1),
                       lambda r:r['probe']['cache_final'].update(cache_read_end=299),
                       lambda r:r['probe']['cache_final'].update(cache_forgotten=19),
                       lambda r:r['probe']['worker_status'].update(encoded_nonref_skipped=2),
                       lambda r:r.update(cache_vendor_unchanged=False)):
            result=self.fixture();mutate(result);self.assertFalse(assess(result,'cached','seek')['passed'])

    def test_throughput_never_becomes_playback_acceptance(self):
        report=assess(self.fixture(),'cached','throughput')
        self.assertTrue(report['passed']);self.assertTrue(report['unclocked_rate_meets_source'])
        self.assertFalse(report['worker_rate_met']);self.assertFalse(report['playback_passed'])
        report=self.fixture();report['probe']['rate']['consumed_fps']=53
        self.assertFalse(assess(report,'cached','rate')['worker_rate_met'])

    def test_cache_worker_build_is_opt_in_and_exclusive(self):
        source=(BASE/'build/build_hardware.py').read_text(encoding='utf-8')
        self.assertIn('cache_probe=False',source)
        self.assertIn('if bundled and cache_probe:raise ValueError',source)
        self.assertIn("'-DP011_CACHE_WORKER=1','-rdynamic'",source)
        bridge=(BASE/'probes/memion_cache.cpp').read_text(encoding='utf-8')
        self.assertIn('#ifdef P011_CACHE_WORKER',bridge)
        self.assertIn('if(!root||!owner||strcmp(root,owner))return false',bridge)
        worker=(BASE/'client/hardware_worker.cpp').read_text(encoding='utf-8')
        self.assertIn('w!=1920||h!=1080',worker)
        self.assertIn('J final=cache_snapshot();final["cache_final"]=true;',worker)
        self.assertGreater(worker.index('J final=cache_snapshot()'),worker.index('try{code=run();}'))

    def test_artifact_rejects_changed_binary_or_geometry(self):
        raw=b'\x7fELF\x01'+b'\0'*13+b'\x28\0'+b'x'*20
        binaries={name:hashlib.sha256(raw).hexdigest() for name in BINS};sources={'source':'exact'}
        bodies={'gstomx.c':b'one','gstomxvideodec.c':b'two'};modified={name:hashlib.sha256(raw).hexdigest() for name,raw in bodies.items()}
        with tempfile.TemporaryDirectory() as tmp:
            base=pathlib.Path(tmp);path=base/'out'/identity(binaries,sources);path.mkdir(parents=True)
            for name in BINS:(path/name).write_bytes(raw)
            (path/'modified-open-source').mkdir()
            for name,body in bodies.items():(path/'modified-open-source'/name).write_bytes(body)
            meta=dict(schema=1,format_observer_schema=1,cached_compat_schema=1,sources=sources,binaries=binaries,pins=PINS,production_default=False,
                      host_mock_passed=True,geometry=[1920,1080,1920,1088,3133440],modified_open_source=modified)
            def save():(path/'build.json').write_text(json.dumps(meta))
            save()
            with patch('cached_worker_artifact.source_hashes',return_value=sources),patch('cached_worker_artifact.modified_hashes',return_value=modified):
                self.assertEqual(validate(base,path),meta)
                meta['geometry'][0]=1280;save()
                with self.assertRaises(ValueError):validate(base,path)
                meta['geometry'][0]=1920;save();(path/'bili-hw').write_bytes(raw+b'changed')
                with self.assertRaises(ValueError):validate(base,path)

if __name__=='__main__':unittest.main()
