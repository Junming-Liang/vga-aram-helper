import json
from pathlib import Path
import tempfile
import unittest
from monitor_preferences import load_preferences,save_preferences


class PreferencesTests(unittest.TestCase):
    def test_old_install_without_preferences_uses_requested_new_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(load_preferences(root),{'live_identity':True,'minimize_on_start':False})
    def test_explicit_off_and_explicit_minimize_survive_restart(self):
        with tempfile.TemporaryDirectory() as root:
            expected={'live_identity':False,'minimize_on_start':True}
            save_preferences(root,expected);self.assertEqual(load_preferences(root),expected)
            self.assertEqual(set(json.loads((Path(root)/'monitor-preferences.json').read_text())),{'schema_version','live_identity','minimize_on_start'})
    def test_unknown_or_malformed_old_values_do_not_reenable_auto_minimize(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'monitor-preferences.json'
            for value in ({'schema_version':0,'minimize_on_start':True},{'schema_version':1,'minimize_on_start':'true'},[],None):
                path.write_text(json.dumps(value));self.assertFalse(load_preferences(root)['minimize_on_start'])
    def test_unknown_fields_are_not_written(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):save_preferences(root,{'live_identity':True,'minimize_on_start':False,'token':'forbidden'})
