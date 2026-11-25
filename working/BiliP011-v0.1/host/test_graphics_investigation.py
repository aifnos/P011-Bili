"""Host-only checks; no ADB, graphics allocation or Docker startup."""
import ast
import contextlib
import gzip
import hashlib
import io
import json
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from graphics_heap_probe import PAYLOAD
from inspect_kernel_graphics import inspect
import window_buffer_probe


class GraphicsInvestigationTests(unittest.TestCase):
    def test_target_python35(self):
        ast.parse(PAYLOAD, feature_version=(3,5))

    def test_query_not_allocate_or_write(self):
        self.assertIn('0xc0184908',PAYLOAD)
        self.assertIn('os.O_RDONLY',PAYLOAD)
        for forbidden in ('0xc0184900','O_WRONLY','O_RDWR','mount(','os.system(',"open(dev,'wb')"):
            self.assertNotIn(forbidden,PAYLOAD)

    def test_firmware_read_exact_boot_only(self):
        self.assertIn("'PARTNAME=boot'",PAYLOAD)
        self.assertIn('length==36700160',PAYLOAD)
        self.assertIn("open(dev,'rb')",PAYLOAD)

    def test_absent_symbols_are_unknown(self):
        self.assertIn("r['symbol_presence']={k:None",PAYLOAD)

    def test_extract_single_kernel(self):
        plain=b'\0'*1024+b'Linux version test\0ion_new_alloc dumb buffer fail\0'
        image,report=inspect(b'prefix'+gzip.compress(plain))
        self.assertEqual(image,plain)
        self.assertFalse(report['device_accessed'])
        self.assertTrue(report['markers'][0]['found'])

    def test_reject_no_kernel(self):
        with self.assertRaises(ValueError):inspect(gzip.compress(b'not a kernel'))

    def test_reject_multiple_kernels(self):
        compressed=gzip.compress(b'Linux version test\0')
        with self.assertRaises(ValueError):inspect(compressed+compressed)

    def fixture(self,root):
        names=['probes/window_buffer_probe.cpp','client/drm_trace.hpp','build/build_window_probe.py']
        sources={}
        for name in names:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            sources[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        raw=b'\x7fELF\x01\x01'+b'\0'*12+b'\x28\x00'+b'\0'*16
        (root/'out').mkdir();(root/'out/window-buffer-probe').write_bytes(raw)
        meta={'schema':1,'sources':sources,'binary_sha256':hashlib.sha256(raw).hexdigest()}
        (root/'out/window-buffer-probe.build.json').write_text(json.dumps(meta))
        return meta

    def test_manifest_accepts_exact_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);meta=self.fixture(root)
            self.assertEqual(window_buffer_probe.validate_artifact(root)[1],meta['binary_sha256'])

    def test_stale_sources_block_before_adb(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root)
            (root/'probes/window_buffer_probe.cpp').write_bytes(b'new source')
            with patch.object(window_buffer_probe,'BASE',root),patch.object(window_buffer_probe,'Adb') as adb:
                with self.assertRaises(ValueError):window_buffer_probe.main()
                adb.assert_not_called()

    def test_reject_unknown_manifest_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);meta=self.fixture(root)
            meta['sources']['../private']=hashlib.sha256(b'').hexdigest()
            (root/'out/window-buffer-probe.build.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError):window_buffer_probe.validate_artifact(root)

    def test_reject_changed_binary(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root)
            (root/'out/window-buffer-probe').write_bytes(b'changed')
            with self.assertRaises(ValueError):window_buffer_probe.validate_artifact(root)

    def test_failed_restoration_query_keeps_failed_safe_report(self):
        from test_wayland_evidence import VALID
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);self.fixture(root)
            (root/'logs').mkdir();(root/'runtime').mkdir()
            (root/'runtime/native_safety.py').write_text('# fixture, never executed')
            probe={'passed':True,'frames':200,'drawable':[800,268],'rgba_bits':[8]*4,'gl_error':0}
            answer={'exit':0,'timeout':False,'stdout':('PROBE='+json.dumps(probe)+'\n').encode(),
                    'stderr':VALID.encode()}
            with patch.object(window_buffer_probe,'BASE',root),patch.object(window_buffer_probe,'ROOT',root), \
                 patch.object(window_buffer_probe,'NATIVE',root),patch.object(window_buffer_probe,'Adb'), \
                 patch.object(window_buffer_probe,'result_from',side_effect=[{'stock':True},{'exists':True},answer,RuntimeError('PRIVATE')]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(window_buffer_probe.main(),1)
            reports=list((root/'logs').glob('*/result.json'))
            self.assertEqual(len(reports),1)
            report=json.loads(reports[0].read_text())
            self.assertFalse(report['passed'])
            self.assertFalse(report['stock_unchanged'])
            self.assertEqual(report['restoration_query_error_type'],'RuntimeError')
            self.assertNotIn('PRIVATE',reports[0].read_text())
            with zipfile.ZipFile(next((root/'logs').glob('*-safe.zip'))) as bundle:
                self.assertEqual(set(bundle.namelist()),{'result.json','probe.stdout.raw'})


if __name__=='__main__':unittest.main()
