"""No-device identity/immutability regression for the isolated worker."""
import hashlib,json,pathlib,tempfile,unittest
from fused_worker_artifact import NAMES,source_hashes,validate

class FusedWorkerTests(unittest.TestCase):
    def fixture(self,base):
        for name in NAMES:
            path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
        raw=bytearray(32);raw[:5]=b'\x7fELF\x01';raw[18:20]=(40).to_bytes(2,'little')
        digest=hashlib.sha256(raw).hexdigest();out=base/'out'/('fused-worker-'+digest[:16]);out.mkdir(parents=True)
        (out/'bili-hw').write_bytes(raw);(out/'build.json').write_text(json.dumps({'schema':1,'sha256':digest,'sources':source_hashes(base)}))
        return out
    def test_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            base=pathlib.Path(folder);out=self.fixture(base);self.assertEqual(validate(base,out)[0],out/'bili-hw')
    def test_each_changed_dependency_refused(self):
        for name in NAMES:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                base=pathlib.Path(folder);out=self.fixture(base);(base/name).write_text('different')
                with self.assertRaises(ValueError):validate(base,out)
    def test_bad_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            base=pathlib.Path(folder);out=self.fixture(base);(out/'bili-hw').write_bytes(b'not ELF')
            with self.assertRaises(ValueError):validate(base,out)
    def test_wrong_path(self):
        with tempfile.TemporaryDirectory() as folder:
            base=pathlib.Path(folder);out=self.fixture(base)
            with self.assertRaises(ValueError):validate(base,out.parent)

if __name__=='__main__':unittest.main()
