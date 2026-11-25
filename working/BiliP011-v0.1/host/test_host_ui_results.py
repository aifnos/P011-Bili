import json,pathlib,tempfile,unittest,zipfile
from PyQt5.QtGui import QImage
from host_ui_results import archive,collect,service


class HostUiResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='p011-host-ui-archive-')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)/'BiliP011-AutoQtQA-20260925-000000'
        (self.root/'screenshots').mkdir(parents=True)
        self.result=dict(passed=True,layer='PC Qt with synthetic API only',device_tested=False,
            device_capture_backend_tested=False,audio_played=False,account_page_captured=False,
            physical_touch_verified=False,error='',host_capture_error='',warnings=[],
            host_capture_backend='QQuickItem.grabToImage',checks=list(service.UI_QA_CHECKS),
            captures=list(service.UI_QA_CAPTURES),host_capture_records=[dict(name=n,width=800,height=480) for n in service.UI_QA_CAPTURES])
        picture=QImage(800,480,QImage.Format_RGB32);picture.fill(0xff223344)
        for name in service.UI_QA_CAPTURES:self.assertTrue(picture.save(str(self.root/'screenshots'/(name+'.png'))))
        self.write()

    def write(self):
        (self.root/'result.json').write_text(json.dumps(self.result),encoding='utf-8')

    def test_archive_is_fixture_labelled_and_whitelist_only(self):
        (self.root/'screenshots/account.png').write_bytes(b'PRIVATE_SENTINEL')
        (self.root/'ui-qa-result.json').write_text('PRIVATE_SENTINEL')
        self.result['host_fixture_state']={'value':'PRIVATE_SENTINEL'};self.write()
        path=archive(self.root)
        with zipfile.ZipFile(path) as z:
            self.assertEqual(len(z.namelist()),len(service.UI_QA_CAPTURES)+3)
            for name in z.namelist():self.assertNotIn(b'PRIVATE_SENTINEL',z.read(name))
            result=json.loads(z.read('result.safe.json'));self.assertFalse(result['device_tested'])
            self.assertIn('非实机',z.read('HOST-SCREENSHOTS.html').decode('utf-8'))
        with self.assertRaises(ValueError):archive(self.root)

    def test_device_account_and_failed_results_are_rejected(self):
        for key,value in (('device_tested',True),('account_page_captured',True),('passed',False),('warnings',['error'])):
            old=self.result[key];self.result[key]=value;self.write()
            with self.assertRaises(ValueError):collect(self.root)
            self.result[key]=old

    def test_missing_duplicate_or_foreign_capture_is_rejected(self):
        original=self.result['captures'][:]
        for names in (original[:-1],original+[original[0]],original[:-1]+['../account']):
            self.result['captures']=names;self.write()
            with self.assertRaises(ValueError):collect(self.root)

    def test_wrong_dimensions_or_records_are_rejected(self):
        self.result['host_capture_records'][0]['width']=0;self.write()
        with self.assertRaises(ValueError):collect(self.root)
        self.result['host_capture_records'][0]['width']=800;self.write()
        picture=QImage(800,268,QImage.Format_RGB32);picture.fill(0xff223344)
        self.assertTrue(picture.save(str(self.root/'screenshots'/(service.UI_QA_CAPTURES[0]+'.png'))))
        with self.assertRaises(ValueError):collect(self.root)


if __name__=='__main__':unittest.main()
