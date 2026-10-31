import json
from pathlib import Path
import tempfile
import unittest
from monitor_preferences import load_preferences,save_preferences


class PreferencesTests(unittest.TestCase):
    def default(self):
        return {'live_identity':True,'minimize_on_start':False,'auto_item_sets':False,'item_set_dir':''}
    def test_old_install_without_preferences_uses_requested_new_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(load_preferences(root),self.default())
    def test_explicit_off_and_explicit_minimize_survive_restart(self):
        with tempfile.TemporaryDirectory() as root:
            expected=dict(self.default(),live_identity=False,minimize_on_start=True,auto_item_sets=True,item_set_dir='C:\\Riot Games\\League of Legends\\Config\\Global\\Recommended')
            save_preferences(root,expected);self.assertEqual(load_preferences(root),expected)
            self.assertEqual(set(json.loads((Path(root)/'monitor-preferences.json').read_text())),{'schema_version','live_identity','minimize_on_start','auto_item_sets','item_set_dir'})
    def test_unknown_or_malformed_old_values_do_not_reenable_auto_minimize(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'monitor-preferences.json'
            for value in ({'schema_version':0,'minimize_on_start':True},{'schema_version':1,'minimize_on_start':'true'},[],None):
                path.write_text(json.dumps(value));self.assertFalse(load_preferences(root)['minimize_on_start'])
    def test_item_set_path_validation(self):
        with tempfile.TemporaryDirectory() as root:
            for bad in (None,123,'x'*501,'a\x00b'):
                with self.subTest(bad=type(bad).__name__),self.assertRaises(ValueError):
                    save_preferences(root,dict(self.default(),item_set_dir=bad))
            path=Path(root)/'monitor-preferences.json';path.write_text(json.dumps({'schema_version':1,'item_set_dir':'a\x00b'}))
            self.assertEqual(load_preferences(root)['item_set_dir'],'')
    def test_unknown_fields_are_not_written(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):save_preferences(root,{'live_identity':True,'minimize_on_start':False,'token':'forbidden'})
