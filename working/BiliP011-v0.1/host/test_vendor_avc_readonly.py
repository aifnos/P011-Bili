import ast,hashlib,pathlib,tempfile,unittest
from vendor_avc_readonly import LIBRARIES,PROBE,verify_copy

class VendorReadOnlyTests(unittest.TestCase):
    def test_fixed_scope_and_target_python35(self):
        self.assertEqual(len(LIBRARIES),4)
        self.assertTrue(all('/' not in n and n.endswith('.so') for n in LIBRARIES))
        ast.parse(PROBE,feature_version=(3,5))
        for forbidden in ('ctypes','subprocess','os.unlink','os.chmod',"'wb'",'kill'):
            self.assertNotIn(forbidden,PROBE)
        self.assertIn('before==after',PROBE)
    def test_matching_elf_copy_and_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'vendor.so';body=bytearray(64)
            body[:5]=b'\x7fELF\x01';body[18:20]=(40).to_bytes(2,'little');path.write_bytes(body)
            record={'size':len(body),'sha256':hashlib.sha256(body).hexdigest()}
            verify_copy(path,record)
            record['size']+=1
            with self.assertRaises(ValueError):verify_copy(path,record)
    def test_non_arm_copy_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'vendor.so';body=b'not executable';path.write_bytes(body)
            with self.assertRaises(ValueError):verify_copy(path,{'size':len(body),'sha256':hashlib.sha256(body).hexdigest()})

if __name__=='__main__':unittest.main()
