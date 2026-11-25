"""Pure no-display diagnostic gates; never connects to ADB."""
import ast,base64,hashlib,json,pathlib,tempfile,unittest,zlib
from hardware_seek_trial import PROBE_SOURCES,PAYLOAD,probe_sources,validate_probe

class SeekDriverTests(unittest.TestCase):
    def fixture(self,root):
        for name in PROBE_SOURCES:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        (root/'out').mkdir()
        body=bytearray(32);body[:5]=b'\x7fELF\x01';body[18:20]=(40).to_bytes(2,'little')
        binary=root/'out/hardware-seek-probe';binary.write_bytes(body)
        meta={'schema':1,'sources':probe_sources(root),'binary_sha256':hashlib.sha256(body).hexdigest()}
        (root/'out/hardware-seek-probe.build.json').write_text(json.dumps(meta))
        return binary
    def test_exact_sources_and_arm_binary(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);binary=self.fixture(root)
            self.assertEqual(validate_probe(root)[0],binary)
    def test_any_changed_source_is_refused(self):
        for name in PROBE_SOURCES:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);self.fixture(root);(root/name).write_text('changed')
                with self.assertRaises(ValueError):validate_probe(root)
    def test_other_binary_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);binary=self.fixture(root);binary.write_bytes(b'not ARM')
            with self.assertRaises(ValueError):validate_probe(root)
    def test_payload_python35_and_legacy_command_budget(self):
        ast.parse(PAYLOAD,feature_version=(3,5))
        hashes={name:hashlib.sha256(name.encode()).hexdigest() for name in ('hardware-seek-probe','bili-hw','libgstomx.so')}
        constants='ROOT='+repr('/mnt/data/p011-toolbox/bili-awake/'+hashes['bili-hw'][:24])+'\nDIRECTORY='+repr('/mnt/data/p011-toolbox/bili-seek-probe-'+hashes['hardware-seek-probe'][:24])+'\nHASHES='+repr(hashes)+'\n'
        constants+='QUALITY=116\nBV="BV1gi4y1V7Xx"\nRATE=True\nPOOL=False\nPRIVATE=True\nMODE=2\nNONREF=True\nKEEP=3\nFUSED=False\nTHROUGHPUT=False\n'
        packed=base64.b64encode(zlib.compress((constants+PAYLOAD).encode(),9))
        self.assertLess(len(packed)+200,4096)
    def test_timeout_cleanup_requires_exact_worker_identity(self):
        self.assertIn("p['exe'] in (DIRECTORY+'/bili-hw',DIRECTORY+'/hardware-seek-probe')",PAYLOAD)
        self.assertIn("trial.environment(p).get('P011_SEEK_PROBE_ROOT')==DIRECTORY",PAYLOAD)
        self.assertIn('trial.terminate(p,kill=True,grace=15)',PAYLOAD)
        self.assertNotIn('killall',PAYLOAD)
        self.assertIn('if not left:',PAYLOAD)
    def test_rate_test_checks_actual_stream_and_has_no_window(self):
        self.assertIn("stream.get('quality')!=QUALITY or stream.get('codec')!=7",PAYLOAD)
        source=(pathlib.Path(__file__).resolve().parents[1]/'probes/hardware_seek_probe.cpp').read_text()
        self.assertIn('ticks()-rate_begin>=12000',source)
        self.assertIn('rate_frames=consumed',source)
        self.assertIn('rate[key]=s.value(key,0ULL)-rate_start.value(key,0ULL)',source)
        self.assertNotIn('SDL_',source)
    def test_pool_probe_is_private_and_stock_config_is_never_written(self):
        self.assertIn("if POOL:env['XDG_CONFIG_HOME']=DIRECTORY",PAYLOAD)
        self.assertIn("'factory_config_unchanged'",PAYLOAD)
        self.assertIn("raise ValueError('Factory workaround differs')",PAYLOAD)
        self.assertNotIn("open(p,'w')",PAYLOAD)
        conf=(pathlib.Path(__file__).resolve().parents[1]/'probes/gstomx-output-pool.conf').read_text()
        self.assertNotIn('no-disable-outport',conf)
        self.assertIn('core-name=/usr/lib/libsprd_omx_core.so',conf)
    def test_nonref_is_explicit_probe_and_qos_is_preserved(self):
        self.assertIn("init['nonref_probe']=NONREF",PAYLOAD)
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'client/hardware_worker.cpp').read_text()
        self.assertIn('request.value("nonref_probe",false)&&getenv("P011_SEEK_PROBE_ROOT")',source)
        self.assertIn('if(t.nonref_policy.drop(au,t.nonref_allowed.load()))',source)
        self.assertIn('sync=true qos=true max-lateness=40000000',source)
        self.assertNotIn('qos=false',source)

    def test_fused_probe_is_explicit_and_keeps_full_input(self):
        self.assertIn("init['fused_half_probe']=FUSED",PAYLOAD)
        self.assertIn("report['half_checks']!=2016",PAYLOAD)
        source=pathlib.Path(__file__).with_name('hardware_seek_trial.py').read_text()
        self.assertIn("plugin_meta['fused_half']!=a.fused_half_probe",source)
        self.assertIn("status.get('encoded_nonref_skipped')==0",source)
        self.assertIn("or a.nonref_probe",source)

    def test_unclocked_probe_is_muted_bounded_and_read_back(self):
        base=pathlib.Path(__file__).resolve().parents[1]
        source=(base/'client/hardware_worker.cpp').read_text(encoding='utf-8')
        gate=source.split('if(throughput_probe&&',1)[1].split('return 41;',1)[0]
        for fragment in ('probe_root','plugin_root','private_omx_probe','muted','limit>40','nonref_probe','high_fps_compat'):
            self.assertIn(fragment,gate)
        self.assertIn('g_object_get(p.decoder,"qos",&decoder_qos',source)
        self.assertIn('if(diagnostic_decoder_qos_property){',source)
        self.assertIn('gboolean decoder_qos=FALSE',source)
        self.assertNotIn('if(!g_object_class_find_property(G_OBJECT_GET_CLASS(p.decoder),"qos"))throw',source)
        self.assertIn('if(decoder_qos||sink_sync||sink_qos||sink_drop||lateness!=-1)throw 41',source)
        self.assertIn('sync=true qos=true max-lateness=40000000',source)

    def test_unclocked_result_never_claims_playback_rate_pass(self):
        source=pathlib.Path(__file__).with_name('hardware_seek_trial.py').read_text(encoding='utf-8')
        block=source.split('if a.throughput_probe:\n',1)[1].split("else:report['worker_rate_met']",1)[0]
        self.assertIn("report['playback_rate_passed']=False",block)
        self.assertIn("'unclocked_maximum_throughput_not_playback'",block)
        self.assertIn("status.get('encoded_nonref_skipped')==0",block)
        self.assertNotIn("report['worker_rate_met']=",block)
        self.assertIn("init['throughput_probe']=THROUGHPUT",PAYLOAD)

    def test_failed_unclocked_probe_keeps_diagnostic_scope(self):
        source=pathlib.Path(__file__).with_name('hardware_seek_trial.py').read_text(encoding='utf-8')
        before_rate=source.split("if a.rate_probe and 'rate'",1)[0]
        self.assertIn("'unclocked_maximum_throughput_not_playback' if a.throughput_probe",before_rate)
        self.assertIn("if a.throughput_probe:report['playback_rate_passed']=False",before_rate)

if __name__=='__main__':unittest.main()
