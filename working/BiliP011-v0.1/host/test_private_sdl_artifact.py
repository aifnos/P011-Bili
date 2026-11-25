"""Private runtime identity checks without Docker, ADB or a window."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from private_sdl_artifact import INPUT_NAMES, tree_hash, validate_private_artifact
import window_buffer_probe


class HostScannerEnvironmentTests(unittest.TestCase):
    def load_builder(self):
        path=Path(__file__).resolve().parents[1]/'build/build_sdl_probe.py'
        spec=importlib.util.spec_from_file_location('private_sdl_builder_test',path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_host_tools_override_cross_sdk(self):
        module=self.load_builder()
        source={'PATH':'/opt/p011/sdk/bin:/usr/bin','CC':'arm-gcc',
                'PKG_CONFIG':'/opt/p011/sdk/bin/pkg-config',
                'PKG_CONFIG_SYSROOT_DIR':'/sdk/sysroot','CPATH':'/sdk/include',
                'CONFIG_SITE':'/sdk/site','LD_PRELOAD':'/sdk/libhook.so'}
        env=module.host_environment(source)
        self.assertNotIn('/opt/p011',env['PATH'])
        self.assertEqual(env['CC'],'/usr/bin/gcc')
        self.assertEqual(env['PKG_CONFIG'],'/usr/bin/pkg-config')
        self.assertEqual(env['CONFIG_SITE'],'/dev/null')
        self.assertNotIn('PKG_CONFIG_SYSROOT_DIR',env)
        self.assertNotIn('CPATH',env)
        self.assertNotIn('LD_PRELOAD',env)
        self.assertEqual(source['CC'],'arm-gcc')

    def test_scoped_environment_preserves_unrelated_values(self):
        env=self.load_builder().host_environment({'HOME':'/home/builder','LANG':'C.UTF-8'})
        self.assertEqual(env['HOME'],'/home/builder')
        self.assertEqual(env['LANG'],'C.UTF-8')
        self.assertEqual(env['PKG_CONFIG_PATH'],'')
        self.assertIn('x86_64-linux-gnu/pkgconfig',env['PKG_CONFIG_LIBDIR'])


class PrivateSDLArtifactTests(unittest.TestCase):
    def fixture(self,root):
        sources={}
        for name in INPUT_NAMES:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            sources[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        sdl=root/'third_party/SDL2-2.0.8-p011'
        c=sdl/'src/video/wayland/SDL_waylandwindow.c';c.parent.mkdir(parents=True);c.write_bytes(b'fixture')
        raw=b'\x7fELF\x01\x01'+b'\0'*12+b'\x28\x00'+b'\0'*16
        out=root/'out/private-sdl-probe';out.mkdir(parents=True)
        for name in ('window-buffer-probe','libSDL2-2.0.so.0'):(out/name).write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest()
        meta={'schema':2,'sources':sources,'sdl_tree_sha256':tree_hash(sdl),
              'binary_sha256':sha,'runtime_sha256':sha,'configure_timeout_ms':500}
        (out/'build.json').write_text(json.dumps(meta))
        return out,sdl,meta

    def test_exact_sources_and_both_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            got=validate_private_artifact(root)
            self.assertEqual(got[0],out/'window-buffer-probe')
            self.assertEqual(got[3],meta['runtime_sha256'])

    def test_library_source_change_blocks_before_adb(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            (sdl/'src/video/wayland/SDL_waylandwindow.c').write_bytes(b'changed')
            with patch.object(window_buffer_probe,'BASE',root),patch.object(window_buffer_probe,'Adb') as adb:
                with self.assertRaises(ValueError):window_buffer_probe.main(private_sdl=True)
                adb.assert_not_called()

    def test_runtime_change_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            (out/'libSDL2-2.0.so.0').write_bytes(b'changed')
            with self.assertRaises(ValueError):validate_private_artifact(root)

    def test_wrong_bound_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            meta['configure_timeout_ms']=0;(out/'build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):validate_private_artifact(root)

    def test_unknown_source_path_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            meta['sources']['../secret']='ignored';(out/'build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):validate_private_artifact(root)

    def test_case_sensitive_tree_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,sdl,meta=self.fixture(root)
            (sdl/'a.txt').write_bytes(b'a');(sdl/'B.txt').write_bytes(b'B')
            expected=hashlib.sha256()
            for name in ('B.txt','a.txt','src/video/wayland/SDL_waylandwindow.c'):
                expected.update(name.encode()+b'\0');expected.update(hashlib.sha256((sdl/name).read_bytes()).digest())
            self.assertEqual(tree_hash(sdl),expected.hexdigest())

    def test_missing_tree_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):tree_hash(Path(d))


if __name__=='__main__':unittest.main()
