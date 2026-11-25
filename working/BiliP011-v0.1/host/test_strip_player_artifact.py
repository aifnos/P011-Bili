"""PC-only rejection tests for the fresh player / private SDL export pair."""
import hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from strip_player_artifact import source_hashes,validate_strip_player,validate_bundled_omx

class StripPlayerArtifactTests(unittest.TestCase):
    def fixture(self,base):
        for name in ('host/media_range_test.cpp','client/player.cpp','build/build_client.py','build/build_strip_player.py',
                     'build/presentation_protocol.py','third_party/presentation-time-v1.xml',
                     'build/build_hardware.py','build/export_runtime.py','host/strip_player_artifact.py',
                     'build/test_cache_vendor_gate.py','host/hardware_cache_gate_test.cpp','build/test_cached_client.py','host/hardware_cache_close_test.cpp',
                     'host/player_geometry_test.cpp','host/player_surface_test.cpp','host/player_controls_test.cpp','host/player_phase_test.cpp','host/player_packets_test.cpp','host/player_features_test.cpp','host/danmaku_timeline_test.cpp','host/hardware_clock_test.cpp','host/h264_access_unit_test.cpp'):
            path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
        out=base/'out';out.mkdir()
        binaries={}
        for name in ('bili-player','bili-api','bili-hw'):
            (out/name).write_bytes(name.encode());binaries[name]=hashlib.sha256(name.encode()).hexdigest()
        meta={'schema':1,'sources':source_hashes(base),'sdl_sha256':'known-sdl','binaries':binaries}
        (out/'strip-player.build.json').write_text(json.dumps(meta))
        return out,meta

    def validate(self,base,sha='known-sdl'):
        with patch('strip_player_artifact.validate_private_artifact',return_value=(None,None,base/'runtime',sha,None)):
            return validate_strip_player(base)

    def test_exact_pair(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);self.fixture(base)
            self.assertEqual(self.validate(base),base/'runtime')

    def test_changed_source_and_added_header_rejected(self):
        for name in ('client/player.cpp','client/new.hpp','host/player_surface_test.cpp','build/presentation_protocol.py','third_party/presentation-time-v1.xml'):
            with tempfile.TemporaryDirectory() as d:
                base=Path(d);self.fixture(base);(base/name).write_bytes(b'changed')
                with self.assertRaises(ValueError):self.validate(base)

    def test_stale_binary_rejected(self):
        for name in ('bili-player','bili-api','bili-hw'):
            with tempfile.TemporaryDirectory() as d:
                base=Path(d);out,_=self.fixture(base);(out/name).write_bytes(b'old')
                with self.assertRaises(ValueError):self.validate(base)

    def test_changed_sdl_pair_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);self.fixture(base)
            with self.assertRaises(ValueError):self.validate(base,'other-sdl')

    def test_unknown_schema_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);out,meta=self.fixture(base);meta['schema']=2
            (out/'strip-player.build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):self.validate(base)
    def test_bundled_omx_requires_exact_parallel_binary(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);out,meta=self.fixture(base)
            meta['bundled_omx']={'artifact':'omx-probe-'+'a'*16,'sha256':'expected'}
            with patch('private_omx_artifact.validate',return_value=(base/'plugin',{'copy_mode':2,'sha256':'expected'})):
                self.assertEqual(validate_bundled_omx(base,meta),base/'plugin')
            for plugin in ({'copy_mode':0,'sha256':'expected'},{'copy_mode':2,'sha256':'other'}):
                with patch('private_omx_artifact.validate',return_value=(base/'plugin',plugin)):
                    with self.assertRaises(ValueError):validate_bundled_omx(base,meta)
    def test_bundle_cannot_silently_omit_required_plugin(self):
        source=(Path(__file__).resolve().parents[1]/'build/export_runtime.py').read_text()
        self.assertIn("files['lib/gst/libgstomx.so']=validate_bundled_omx",source)
        self.assertIn("raise ValueError('Cannot omit required private OMX from this player')",source)
    def test_fused_pair_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);out,meta=self.fixture(base)
            meta['bundled_omx']={'artifact':'omx-probe-'+'a'*16,'sha256':'expected'}
            with patch('private_omx_artifact.validate',return_value=(base/'plugin',{'copy_mode':4,'sha256':'expected'})):
                with self.assertRaises(ValueError):validate_bundled_omx(base,meta)
                meta['bundled_omx']['fused_copy']=True
                self.assertEqual(validate_bundled_omx(base,meta),base/'plugin')
            with patch('private_omx_artifact.validate',return_value=(base/'plugin',{'copy_mode':2,'sha256':'expected'})):
                with self.assertRaises(ValueError):validate_bundled_omx(base,meta)
    def test_runtime_path_is_fixed_and_expected_plugin_is_verified(self):
        base=Path(__file__).resolve().parents[1]
        source=(base/'client/hardware_client.hpp').read_text()
        block=source.split('// Fixed sibling of this verified immutable media bundle',1)[1].split('#endif',1)[0]
        self.assertIn('/lib/gst',block)
        self.assertIn('lstat(',block)
        self.assertNotIn('request',block.split('environment.',1)[1])
        self.assertIn('status.value("omx_private_plugin",false)',source)
        worker=(base/'client/hardware_worker.cpp').read_text()
        self.assertIn('gst_plugin_get_filename(plugin)',worker)

if __name__=='__main__':unittest.main()
