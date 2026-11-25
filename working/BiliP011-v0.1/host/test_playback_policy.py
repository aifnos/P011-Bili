"""No ADB: API-driven identifiers, settings reuse and resource headroom."""
import pathlib,sys,unittest,tempfile,json
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'client'))
import playback_policy as p

class PolicyTests(unittest.TestCase):
    def test_returned_future_quality_ids(self):
        for n in (0,16,80,120,125,126,127,333,65535):self.assertTrue(p.quality_id(n))
        for n in (-1,65536,True,1.0,'80',None):self.assertFalse(p.quality_id(n))
    def test_settings_partial(self):
        s=p.settings({'aspect':1,'dm_area':50,'dm_opacity':75})
        self.assertEqual(s,dict(p.DEFAULTS,aspect=1,dm_area=50,dm_opacity=75))
    def test_settings_untrusted(self):
        for raw in (None,[],{'aspect':True,'dm_area':0,'dm_opacity':999,'dm_size':'120','dm_speed':float('nan')}):self.assertEqual(p.settings(raw),p.DEFAULTS)
    def test_setting_roundtrip(self):
        for k,choices in p.CHOICES.items():
            for v in choices:self.assertEqual(p.settings({k:v})[k],v)
    def test_not_fixed_4k_cap(self):
        self.assertTrue(p.decode_budget({'width':7680,'height':4320},1800000))
        self.assertFalse(p.decode_budget({'width':7680,'height':4320},900000))
        self.assertFalse(p.decode_budget({'width':7680,'height':4320},300000))
    def test_normal_and_corrupt_sizes(self):
        self.assertTrue(p.decode_budget({'width':1920,'height':1080},300000))
        for d in ({'width':True},{'width':-1},{'width':999999},{'width':16384,'height':16384}):self.assertFalse(p.decode_budget(d,900000))
    def test_preferences_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            store=p.Preferences(str(pathlib.Path(root)/'private'));self.assertEqual(store.load(),p.DEFAULTS)
            store.save({'aspect':2,'dm_opacity':50});self.assertEqual(p.Preferences(store.directory).load(),dict(p.DEFAULTS,aspect=2,dm_opacity=50))
            self.assertEqual(sorted(x.name for x in pathlib.Path(store.directory).iterdir()),['settings-v1.json'])
    def test_preferences_unknown_file_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            store=p.Preferences(str(pathlib.Path(root)/'private'));target=pathlib.Path(store.path);target.write_text('{"user_file":true}')
            with self.assertRaises(ValueError):store.save({})
            self.assertEqual(json.loads(target.read_text()),{'user_file':True})
    def test_preferences_boolean_schema_not_version(self):
        with tempfile.TemporaryDirectory() as root:
            store=p.Preferences(str(pathlib.Path(root)/'private'))
            pathlib.Path(store.path).write_text('{"schema":true,"settings":{}}')
            pathlib.Path(store.path).chmod(0o600)
            with self.assertRaises(ValueError):store.load()

if __name__=='__main__':unittest.main()
