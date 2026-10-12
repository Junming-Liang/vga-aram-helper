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
        self.assertIsNone(calls[0][1]['selection_smoke_input'])
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

    def test_selection_diagnostic_is_explicit_paired_and_offline_demo(self):
        native = types.ModuleType('native_ui')
        def run(loader, **kw):
            loader()
            self.assertEqual(kw['selection_smoke_input'], Path('owned.json'))
            self.assertEqual(kw['smoke_report'], Path('selection.json'))
            self.assertIsNone(kw['smoke_screenshot'])
            self.assertFalse(kw['enable_updates'])
            return 0
        native.run_native = run
        with patch.dict(sys.modules, {'native_ui': native}), patch('server.load_startup_data', return_value={}) as load:
            self.assertEqual(launcher.main(['--selection-smoke-input', 'owned.json', '--selection-smoke-report', 'selection.json']), 0)
            self.assertTrue(load.call_args.kwargs['demo'])
        for args in (['--selection-smoke-input', 'owned.json'], ['--selection-smoke-report', 'selection.json'],
                     ['--selection-smoke-input', 'owned.json', '--selection-smoke-report', 'selection.json', '--headless']):
            with self.subTest(args=args), self.assertRaises(SystemExit): launcher.main(args)

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
        valid = {'status':'passed', 'backend':'qtwidgets', 'frozen':True, 'applicationVersion':'0.4.2',
                 'native_window':True, 'window_closed':True, 'capture_passed':True, 'ocr_passed':True,
                 'click_through_passed':True, 'qt_platform':'windows', 'screenshot_method':'win32 desktop capture',
                 'source_tier_display_passed':True, 'source_tier_hero_specific':True, 'source_tier_missing_passed':True,
                 'source_tier_screen_order_preserved':True, 'source_tier_no_winrate_display':True,
                 'source_tier_rendered':['虚构源评级（演示）：T1','虚构源评级（演示）：T2','虚构源评级（演示）：T3']}
        valid.update(dict.fromkeys(native_smoke.NATIVE_AUTOMATION_FIELDS, True))
        valid.update(self.geometry_fixture())
        native_smoke.validate_report(valid, '0.4.2')
        for field in native_smoke.NATIVE_AUTOMATION_FIELDS:
            for bad in (False, None, 1, 'true'):
                with self.subTest(field=field, value=bad), self.assertRaises(RuntimeError):
                    native_smoke.validate_report(dict(valid, **{field: bad}), '0.4.2')
        for key, value in [('qt_platform','offscreen'),('backend','browser'),('frozen',False),('ocr_passed',False),
                           ('capture_passed',False),('click_through_passed',False),('window_closed',False),('error','failure'),
                           ('source_tier_display_passed',False),('source_tier_hero_specific',False),
                           ('source_tier_missing_passed',False),('source_tier_screen_order_preserved',False),
                           ('source_tier_no_winrate_display',False),('source_tier_rendered',[])]:
            result = dict(valid, **{key:value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                native_smoke.validate_report(result, '0.4.2')

    @staticmethod
    def geometry_fixture(scale=1):
        return dict(physical_mock_geometry_passed=True, overlay_layout_passed=True, requested_app_scale=scale,
                    mock_qwindow_dpr=scale, overlay_qwindow_dpr=scale, overlay_compact=False,
                    desktop_work_area_physical=dict(x=0,y=0,width=1024,height=728),
                    mock_window_physical=dict(x=12,y=20,width=960,height=600),
                    clientRect=dict(x=12,y=20,width=960,height=600),
                    overlay_window_physical=dict(x=32,y=350,width=920,height=240))

    def test_three_native_scales_keep_distinct_evidence_and_explicit_environment(self):
        self.assertEqual([native_smoke.evidence_prefix(s) for s in native_smoke.APP_SCALES],
                         ['windows-native','windows-native-scale150','windows-native-scale200'])
        with tempfile.TemporaryDirectory() as temporary:
            before={'SystemRoot':r'C:\Windows','QT_SCALE_FACTOR':'9','QT_QPA_PLATFORM':'offscreen',
                    'QT_SCREEN_SCALE_FACTORS':'7','QT_PLUGIN_PATH':'untrusted','PYSIDE_DESIGNER_PLUGINS':'untrusted'}
            env=native_smoke.native_environment(before,Path(temporary),'1.5')
            self.assertEqual(env['QT_SCALE_FACTOR'],'1.5')
            self.assertEqual([key for key in env if key.startswith(('QT_','PYSIDE_'))],['QT_SCALE_FACTOR'])
            self.assertEqual(before['QT_SCALE_FACTOR'],'9')
        for invalid in ('0','1.25','2.5','nan'):
            with self.subTest(scale=invalid),self.assertRaises(ValueError):native_smoke.evidence_prefix(invalid)

    def test_actual_native_scale_geometry_cannot_be_smaller_or_outside(self):
        for scale in (1,1.5,2):
            native_smoke.validate_physical_geometry(self.geometry_fixture(scale),scale)
            for key,value in [('requested_app_scale',1 if scale!=1 else 2),('mock_qwindow_dpr',0),
                              ('overlay_qwindow_dpr',float('nan')),('physical_mock_geometry_passed',1),('overlay_layout_passed',False),
                              ('overlay_compact',None)]:
                with self.subTest(scale=scale,key=key),self.assertRaises(RuntimeError):
                    native_smoke.validate_physical_geometry(dict(self.geometry_fixture(scale),**{key:value}),scale)
        for key in ('desktop_work_area_physical','mock_window_physical','clientRect','overlay_window_physical'):
            value=self.geometry_fixture();value[key]['width']=True
            with self.subTest(key=key),self.assertRaises(RuntimeError):native_smoke.validate_physical_geometry(value,1)
        for edit in (lambda d:d['clientRect'].update(width=640,height=400),
                     lambda d:d['overlay_window_physical'].update(x=11),
                     lambda d:d['mock_window_physical'].update(x=-1),
                     lambda d:d['clientRect'].update(y=19)):
            value=self.geometry_fixture();edit(value)
            with self.assertRaises(RuntimeError):native_smoke.validate_physical_geometry(value,1)

    def test_failed_native_report_exposes_only_bounded_synthetic_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'native.json'
            self.assertEqual(native_smoke.native_failure_summary(path),{'report_present':False})
            path.write_text(json.dumps({'status':'failed','error_type':'AssertionError','error':'X'*3000,
                'error_traceback':'trace'*2000,'checks':['step '+str(i) for i in range(20)],
                'capture_passed':True,'ocr_passed':'true','image_base64':'not-to-print',
                'environment':{'SECRET':'not-to-read'}}),encoding='utf-8')
            result=native_smoke.native_failure_summary(path)
            self.assertEqual(result['status'],'failed');self.assertEqual(len(result['error']),2000)
            self.assertEqual(len(result['error_traceback']),4000)
            self.assertEqual(result['last_completed_checks'],['step '+str(i) for i in range(12,20)])
            self.assertTrue(result['capture_passed']);self.assertNotIn('ocr_passed',result)
            self.assertNotIn('image_base64',result);self.assertNotIn('environment',result)
            path.write_bytes(b'X'*(128*1024+1))
            self.assertIn('128 KiB',native_smoke.native_failure_summary(path)['diagnostic_error'])
            path.write_text('{invalid',encoding='utf-8')
            self.assertIn('diagnostic_error',native_smoke.native_failure_summary(path))

    def test_spec_has_native_dpi_and_no_console(self):
        spec = (ROOT/'packaging/VGA-Aram-Helper.spec').read_text(encoding='utf-8')
        self.assertIn('console=False', spec)
        self.assertIn('hero_portraits', spec)
        self.assertIn('hero_recognition', spec)
        self.assertIn('overlay_geometry', spec)
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

    def test_genuine_report_is_counted_in_small_evidence_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'reports').mkdir()
            (root/'reports/hero-recognition-genuine.json').write_bytes(b'X' * 20_000)
            (root/'reports/champion-select-genuine.json').write_bytes(b'Y' * 10_000)
            fetch = lambda url: {'total_count': 0, 'artifacts': []}
            result = budget.check_budget(root, fetcher=fetch, evidence_only=True)
            self.assertEqual(result['proposed_upper_estimate_bytes'], 1_030_900)

    def test_artifact_budget_fails_on_unknown_repository_or_incomplete_listing(self):
        with self.assertRaises(RuntimeError):budget.check_budget(Path('.'),repository='other/repo')
        with self.assertRaises(RuntimeError):budget.check_budget(Path('.'),fetcher=lambda url:{'total_count':1,'artifacts':[]})

    def test_evidence_only_budget_does_not_count_files_not_uploaded_as_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'dist/release').mkdir(parents=True)
            with (root/'dist/release/app.exe').open('wb') as file:
                file.truncate(230_000_000)
            (root/'reports').mkdir();(root/'reports/windows-fixture.json').write_text('{}')
            fetch=lambda url:{'total_count':1,'artifacts':[{'expired':False,'size_in_bytes':360_000_000}]}
            with self.assertRaisesRegex(RuntimeError,'budget would be exceeded'):
                budget.check_budget(root,fetcher=fetch)
            report=budget.check_budget(root,fetcher=fetch,evidence_only=True)
            self.assertEqual(report['upload_scope'],'evidence-only')
            self.assertEqual(report['status'],'passed')
            self.assertLess(report['projected_bytes'],362_000_000)


if __name__ == '__main__':unittest.main()
