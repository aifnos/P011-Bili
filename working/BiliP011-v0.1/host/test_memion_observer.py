import ast,hashlib,json,pathlib,tempfile,unittest
from memion_observer_artifact import PINS,artifact_name,source_hashes,validate
from hardware_seek_trial import PAYLOAD

BASE=pathlib.Path(__file__).resolve().parents[1]

class ObserverTests(unittest.TestCase):
    def test_exact_vendor_pins_and_private_identity(self):
        self.assertEqual(len(PINS),2)
        for digest in PINS.values():self.assertRegex(digest,r'^[a-f0-9]{64}$')
        self.assertNotEqual(artifact_name('a',{'source':'a'}),artifact_name('a',{'source':'b'}))

    def test_changed_elf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            import unittest.mock
            base=pathlib.Path(tmp);(base/'out').mkdir()
            raw=b'\x7fELF\x01'+b'\0'*13+b'\x28\0'+b'x'*20
            digest=hashlib.sha256(raw).hexdigest();sources={'source':'a'}
            path=base/'out'/artifact_name(digest,sources);path.mkdir();binary=path/'libmemion-observer.so';binary.write_bytes(raw)
            (path/'build.json').write_text(json.dumps({'schema':1,'sha256':digest,'sources':sources,'pins':PINS,'read_only_arguments':True}))
            with unittest.mock.patch('memion_observer_artifact.source_hashes',return_value=sources):
                self.assertEqual(validate(base,path)[0],binary)
                binary.write_bytes(raw+b'changed')
                with self.assertRaises(ValueError):validate(base,path)

    def test_observer_forwards_without_ioctl_or_writes_to_memory(self):
        source=(BASE/'probes/memion_observer.cpp').read_text()
        for required in ('call(object,fd,size,heapmask,flags)','errno=result_errno;return result;','RTLD_NOLOAD','serial<64','write(4,'):
            self.assertIn(required,source)
        for forbidden in ('ioctl(','mprotect(','PROT_WRITE','system(','popen(','/dev/ion'):
            self.assertNotIn(forbidden,source)

    def test_device_payload_keeps_safety_and_cleanup(self):
        ast.parse(PAYLOAD,feature_version=(3,5))
        self.assertIn('OBSERVER_PINS.items()',PAYLOAD)
        self.assertIn("'libmemion-observer.so'",PAYLOAD)
        self.assertIn("report['observer_vendor_unchanged']",PAYLOAD)

    def test_only_diagnostic_driver_enables_preload(self):
        source=(BASE/'client/hardware_client.hpp').read_text()
        pos=source.index('env.push_back("LD_PRELOAD=')
        self.assertGreater(source.rfind('#ifdef P011_PRIVATE_OMX_PROBE',0,pos),source.rfind('#endif',0,pos))
        self.assertIn('request.value("muted",false)',source)
        self.assertLess(source.index('lstat((root+"/libmemion-observer.so")'),source.index('mem=int(syscall('))
        self.assertEqual(len(source_hashes(BASE)),4)

if __name__=='__main__':unittest.main()
