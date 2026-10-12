"""Native-launch routing and acceptance gates; no game or Windows claims here."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launcher


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


native_smoke = module('windows_native_smoke', ROOT / 'tests' / 'windows_native_smoke.py')
budget = module('artifact_budget', ROOT / 'scripts' / 'check_artifact_budget.py')


class NativePackagingTests(unittest.TestCase):
    def test_default_routes_to_native_without_loading_browser(self):
        native = types.ModuleType('native_ui')
        calls = []
        native.run_native = lambda loader, **kw: (calls.append((loader, kw)) or 0)
        with patch.dict(sys.modules, {'native_ui': native}):
            self.assertEqual(launcher.main([]), 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(callable(calls[0][0]))
        self.assertEqual(calls[0][1]['current_version'], launcher.__version__)
        self.assertIsNone(calls[0][1]['smoke_report'])
        self.assertIsNone(calls[0][1]['on_ready'])
        self.assertTrue(calls[0][1]['enable_updates'])
        self.assertNotIn('webbrowser', Path(launcher.__file__).read_text(encoding='utf-8'))

    def test_native_no_updates_is_forwarded_for_rollback(self):
        native = types.ModuleType('native_ui')
        calls = []
        native.run_native = lambda loader, **kw: (calls.append(kw) or 0)
        with patch.dict(sys.modules, {'native_ui': native}):
            self.assertEqual(launcher.main(['--no-updates']), 0)
        self.assertFalse(calls[0]['enable_updates'])

    def test_native_smoke_uses_demo_loader_and_png_sibling(self):
        native = types.ModuleType('native_ui')
        def run(loader, **kw):
            loader()
            self.assertEqual(kw['smoke_report'], Path('result.json'))
            self.assertEqual(kw['smoke_screenshot'], Path('result.png'))
            return 0
        native.run_native = run
        with patch.dict(sys.modules, {'native_ui': native}), patch('server.load_startup_data', return_value={}) as load:
            self.assertEqual(launcher.main(['--native-smoke-report', 'result.json']), 0)
            self.assertTrue(load.call_args.kwargs['demo'])

    def test_native_ota_marker_requires_actual_ocr(self):
        native = types.ModuleType('native_ui')
        native.run_native = lambda loader, **kw: kw['on_ready']()
        with patch.dict(sys.modules, {'native_ui': native}), \
             patch.object(launcher, 'bundled_self_test', side_effect=RuntimeError('missing model')), \
             patch('updates.mark_update_healthy') as mark:
            with self.assertRaisesRegex(RuntimeError, 'missing model'):
                launcher.main(['--update-health', 'health.json'])
            mark.assert_not_called()

    def test_windowed_version_and_licenses_write_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(launcher.main(['--version-file', str(root / 'version.json')]), 0)
            self.assertEqual(json.loads((root / 'version.json').read_text())['applicationVersion'], launcher.__version__)
            with patch.object(launcher, 'print_licenses', side_effect=lambda: print('Apache test license')):
                self.assertEqual(launcher.main(['--licenses-file', str(root / 'licenses.txt')]), 0)
            self.assertIn('Apache', (root / 'licenses.txt').read_text())

    def test_native_acceptance_rejects_browser_offscreen_and_incomplete_proof(self):
        valid = {'status':'passed', 'backend':'qtwidgets', 'frozen':True, 'applicationVersion':'0.3.0',
                 'native_window':True, 'window_closed':True, 'capture_passed':True, 'ocr_passed':True,
                 'click_through_passed':True, 'qt_platform':'windows', 'screenshot_method':'win32 desktop capture'}
        native_smoke.validate_report(valid, '0.3.0')
        for key, value in [('qt_platform','offscreen'),('backend','browser'),('frozen',False),('ocr_passed',False),
                           ('capture_passed',False),('click_through_passed',False),('window_closed',False),('error','failure')]:
            result = dict(valid, **{key:value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                native_smoke.validate_report(result, '0.3.0')

    def test_spec_has_native_dpi_and_no_console(self):
        spec = (ROOT/'packaging/VGA-Aram-Helper.spec').read_text(encoding='utf-8')
        self.assertIn('console=False', spec)
        self.assertIn('windows.manifest', spec)
        self.assertIn('PerMonitorV2', (ROOT/'packaging/windows.manifest').read_text())
        self.assertNotIn('PySide6-Addons', (ROOT/'requirements-build.txt').read_text())

    def test_artifact_budget_is_bounded_and_ignores_expired_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'dist/release').mkdir(parents=True);(root/'dist/release/app.exe').write_bytes(b'fixture')
            fetch=lambda url:{'total_count':2,'artifacts':[{'expired':False,'size_in_bytes':126_000_000},{'expired':True,'size_in_bytes':600_000_000}]}
            report=budget.check_budget(root,fetcher=fetch)
            self.assertEqual(report['status'],'passed');self.assertEqual(report['existing_repository_artifact_bytes'],126_000_000)
            with self.assertRaisesRegex(RuntimeError,'budget would be exceeded'):
                budget.check_budget(root,fetcher=lambda url:{'total_count':1,'artifacts':[{'expired':False,'size_in_bytes':490_000_000}]})
            self.assertEqual(json.loads((root/'reports/windows-artifact-budget.json').read_text())['status'],'blocked')

    def test_artifact_budget_fails_on_unknown_repository_or_incomplete_listing(self):
        with self.assertRaises(RuntimeError):budget.check_budget(Path('.'),repository='other/repo')
        with self.assertRaises(RuntimeError):budget.check_budget(Path('.'),fetcher=lambda url:{'total_count':1,'artifacts':[]})


if __name__ == '__main__':unittest.main()
