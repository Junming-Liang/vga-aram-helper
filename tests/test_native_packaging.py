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


def overlay_duty_fixture():
    """Complete synthetic validator input; not observed Windows evidence."""
    contract = native_smoke.validate_overlay_duty.__globals__
    report = {'overlay_duty_cycle_passed': True,
        'overlay_duty_cycle': {'schema_version': 1, 'scope': contract['SCOPE'],
            'artificial_hold_target_ms': 350, 'cases': []}}
    for kind in contract['CASES']:
        before = dict(last_observation=100., automatic_frames=2, hero_stable_frames=2,
                      stable_frames=2, generation=3, accepted_observed_at=100.)
        restored = kind in ('unchanged', 'stop_late')
        phases=[]
        for name in ('before_match', 'before_ocr'):
            phases.append(dict(name=name, restored=restored, qt_visible=restored, native_visible=restored,
                state_unchanged=True, current_identity_geometry_focus=True, helper_cleanup_complete=True,
                compositor_checked_after_capture=True, state_before=copy.deepcopy(before), state_at_phase=copy.deepcopy(before),
                window_identity=[100, 200, 'Owned fixture'], current_window_identity=[100, 200, 'Owned fixture'],
                capture_rect=dict(x=20,y=20,width=960,height=600), current_rect=dict(x=20,y=20,width=960,height=600),
                candidate_roi_sha256=('f' if kind=='changed_roi' else 'a')*64, accepted_candidate_roi_sha256='a'*64,
                hud_input_sha256=('b' if kind in ('unchanged','changed_roi','stop_late') else 'c')*64, accepted_hud_input_sha256='b'*64,
                vocabulary_sha256='d'*64, source_metadata_sha256='e'*64, scope_matches_accepted=True,
                matcher_instance_matches_accepted=True, matcher_type='PortraitMatcher', matcher_configuration=[.88,.07],
                roi=[.15,.25,.7,.35], capture_serial=10, captured_at=100.1,
                emitted_ms=21. if name=='before_match' else 380.,applied_ms=22. if name=='before_match' else 381.,
                compositor_validated_ms=21.5 if name=='before_match' else 380.5))
        row=dict(name=kind,status='passed',timings_ms=dict(capture_start=5.,capture_return=20.,before_match_emitted=21.,
                before_match_applied=22.,before_ocr_emitted=380.,before_ocr_applied=381.,gui_compositor_validated=380.5,final=740.),
            total_ms=740.,sampled_hidden_ms=(22. if kind=='unchanged' else 27.) if restored else 740.,sampled_visible_ms=(718. if kind=='unchanged' else 713.) if restored else 0.,
            sampled_inference_visible_ms=(718. if kind=='unchanged' else 713.) if restored else 0., max_sample_gap_ms=20.,native_visibility_samples=80,
            capture_samples=3,capture_visible_samples=0,qt_show_events_during_capture=0,capture_count=1,max_capture_concurrency=1,held_state_unchanged_samples=50,
            sampled_visibility_transitions=[{'at_ms':0.,'visible':True},{'at_ms':.001,'visible':False}] + ([{'at_ms':22.,'visible':True}] if restored else [{'at_ms':740.,'visible':True}] if kind=='changed_roi' else []) + ([{'at_ms':735.,'visible':False}] if kind=='stop_late' else []),
            artificial_holds_ms={'before_match':350.,'before_ocr':350.},old_hide_until_final_policy_counterfactual_ms=740.,
            comparison_scope=contract['COMPARISON_SCOPE'],capture_backend='windows-graphics-capture',helper_count=1,
            helper_exit_codes=[0],helper_cleanup_complete_before_phase=True,phases=phases,
            final_confirmed=kind in ('unchanged','changed_roi'),final_running=kind!='stop_late',final_qt_visible=kind in ('unchanged','changed_roi'),
            final_native_visible=kind in ('unchanged','changed_roi'),final_result_generation=3,final_state_generation=3 if kind in ('unchanged','changed_roi') else 4,
            final_captured_at=100.1,final_last_observation=100. if kind=='stop_late' else 100.1,
            final_candidate_names=['星火共鸣','晶盾回路','风步微光'],
            final_hero_observation={'hero':None if kind=='unknown_hud' else '磐石守卫（演示）' if kind=='changed_hud' else '星火术士（演示）',
                                    'confident':kind!='unknown_hud'})
        if kind=='changed_roi':row['fixture_change']='Original 12x12 non-text patch inside candidate ROI, above title band; synthetic animation analogue, not actual gameplay measurement'
        if kind=='stop_late':row.update(stop_return_ms=1.,late_final_discarded=True);row['timings_ms']['stop']=735.
        report['overlay_duty_cycle']['cases'].append(row)
    return report


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
                 'card_names_rendered':['星火共鸣','晶盾回路','风步微光'],
                       'source_tier_rendered':['T1','T2','T3'],
                 'source_tier_accessible':['虚构源评级（演示）：T1','虚构源评级（演示）：T2','虚构源评级（演示）：T3'],
                 'source_attribution_rendered':'虚构演示 · 非 Riot 评级/批准', 'source_details_reachable':True}
        valid.update(dict.fromkeys(native_smoke.NATIVE_AUTOMATION_FIELDS, True))
        valid.update(self.geometry_fixture())
        valid.update(overlay_duty_fixture())
        native_smoke.validate_report(valid, '0.4.2')
        for field in native_smoke.NATIVE_AUTOMATION_FIELDS:
            for bad in (False, None, 1, 'true'):
                with self.subTest(field=field, value=bad), self.assertRaises(RuntimeError):
                    native_smoke.validate_report(dict(valid, **{field: bad}), '0.4.2')
        for key, value in [('qt_platform','offscreen'),('backend','browser'),('frozen',False),('ocr_passed',False),
                           ('capture_passed',False),('click_through_passed',False),('window_closed',False),('error','failure'),
                           ('source_tier_display_passed',False),('source_tier_hero_specific',False),
                           ('source_tier_missing_passed',False),('source_tier_screen_order_preserved',False),
                           ('source_tier_no_winrate_display',False),('source_tier_rendered',[]),('card_names_rendered',[]),
                           ('source_attribution_rendered',None),('source_attribution_rendered','虎牙公开源'),('source_tier_accessible',['T1','T2','T3']),('source_details_reachable',False)]:
            result = dict(valid, **{key:value})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                native_smoke.validate_report(result, '0.4.2')

    def test_duty_contract_rejects_missing_forged_or_unbounded_observations(self):
        native_smoke.validate_overlay_duty(overlay_duty_fixture())
        mutations = [lambda d:d.update(overlay_duty_cycle_passed=1),
            lambda d:d.pop('overlay_duty_cycle'),
            lambda d:d['overlay_duty_cycle'].update(schema_version=True),
            lambda d:d['overlay_duty_cycle'].update(scope='Live game benchmark'),
            lambda d:d['overlay_duty_cycle'].update(artificial_hold_target_ms=0),
            lambda d:d['overlay_duty_cycle']['cases'].pop()]
        for mutation in mutations:
            value=overlay_duty_fixture();mutation(value)
            with self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
        for index in range(5):
            for key,bad in [('capture_count',2),('qt_show_events_during_capture',1),('qt_show_events_during_capture',False),('capture_count',True),('max_capture_concurrency',2),
                ('capture_backend','hwnd-gdi'),('helper_count',0),('helper_exit_codes',[None]),
                ('helper_exit_codes',[False]),('helper_cleanup_complete_before_phase',1),
                ('capture_visible_samples',1),('capture_visible_samples',False),('native_visibility_samples',0),
                ('final_captured_at',99.),('final_result_generation',999),('final_native_visible','true')]:
                value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][index][key]=bad
                with self.subTest(case=index,key=key),self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
            for key in ('total_ms','sampled_hidden_ms','sampled_visible_ms','sampled_inference_visible_ms','max_sample_gap_ms'):
                for bad in (None,True,-1,float('nan'),float('inf'),'700'):
                    value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][index][key]=bad
                    with self.subTest(case=index,key=key,bad=bad),self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
            for key in ('capture_start','capture_return','before_match_emitted','before_match_applied','before_ocr_emitted','before_ocr_applied','final'):
                value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][index]['timings_ms'][key]=float('nan')
                with self.subTest(case=index,timing=key),self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)

    def test_duty_contract_rejects_forged_restoration_ttl_scope_and_stop(self):
        for index in range(5):
            for phase_index in range(2):
                mutations=[lambda p:p.update(state_unchanged=1),lambda p:p['state_at_phase'].update(last_observation=100.1),
                    lambda p:p['state_at_phase'].update(automatic_frames=3),lambda p:p.update(restored=not p['restored']),
                    lambda p:p.update(native_visible=not p['native_visible']),lambda p:p.update(helper_cleanup_complete=False),
                    lambda p:p.update(scope_matches_accepted=False),lambda p:p.update(matcher_instance_matches_accepted=False),
                    lambda p:p.update(captured_at=99.),lambda p:p.update(capture_serial=True),
                    lambda p:p.update(current_window_identity=[101,200,'Owned fixture']),
                    lambda p:p.update(current_window_identity=[100.0,200,'Owned fixture']),
                    lambda p:p.update(current_window_identity=[100,200.0,'Owned fixture']),
                    lambda p:p['current_rect'].update(width=959),lambda p:p.update(hud_input_sha256='x'),
                    lambda p:p.update(candidate_roi_sha256='0'*64),lambda p:p.update(matcher_configuration=[.01,.01]),
                    lambda p:p.update(roi=[True,.25,.7,.35]),lambda p:p.update(compositor_checked_after_capture=False)]
                for mutate in mutations:
                    value=overlay_duty_fixture();mutate(value['overlay_duty_cycle']['cases'][index]['phases'][phase_index])
                    with self.subTest(case=index,phase=phase_index),self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
        for index,key,bad in [(0,'sampled_inference_visible_ms',499),(1,'sampled_inference_visible_ms',1),
                             (3,'sampled_inference_visible_ms',1),(4,'late_final_discarded',1),
                             (4,'stop_return_ms',250),(4,'final_last_observation',100.1),(4,'final_state_generation',3)]:
            value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][index][key]=bad
            with self.subTest(case=index,key=key),self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
        value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][0]['artificial_holds_ms']['before_match']=349
        with self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)
        value=overlay_duty_fixture();value['overlay_duty_cycle']['cases'][4]['timings_ms']['stop']=741
        with self.assertRaises(RuntimeError):native_smoke.validate_overlay_duty(value)

    def test_duty_freshness_cannot_be_forged_with_coherent_stale_snapshots(self):
        for captured in (105.,103.9):
            value=overlay_duty_fixture();row=value['overlay_duty_cycle']['cases'][0]
            for phase in row['phases']:phase['captured_at']=captured
            row.update(final_captured_at=captured,final_last_observation=captured)
            with self.subTest(captured=captured),self.assertRaisesRegex(RuntimeError,'stale|freshness'):
                native_smoke.validate_overlay_duty(value)
        value=overlay_duty_fixture();row=value['overlay_duty_cycle']['cases'][0]
        for phase in row['phases']:
            for field in ('state_before','state_at_phase'):phase[field]['accepted_observed_at']=99.9
        with self.assertRaisesRegex(RuntimeError,'previously accepted'):
            native_smoke.validate_overlay_duty(value)

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

    def test_native_overlay_cannot_cover_over_half_the_client(self):
        value=self.geometry_fixture()
        value['overlay_window_physical'].update(y=30,height=301)
        with self.assertRaisesRegex(RuntimeError,'half'):
            native_smoke.validate_physical_geometry(value,1)

    def test_failed_native_report_exposes_only_bounded_synthetic_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'native.json'
            self.assertEqual(native_smoke.native_failure_summary(path),{'report_present':False})
            path.write_text(json.dumps({'status':'failed','error_type':'AssertionError','error':'X'*3000,
                'error_traceback':'trace'*2000,'checks':['step '+str(i) for i in range(20)],
                'capture_passed':True,'ocr_passed':'true','image_base64':'not-to-print',
                'environment':{'SECRET':'not-to-read'}, 'overlay_duty_cycle':{'cases':[{
                    'name':'X'*200,'capture_count':1,'total_ms':float('nan'),'capture_backend':'windows-graphics-capture',
                    'final_running':False,'private':'not-to-print'}]*9}}),encoding='utf-8')
            result=native_smoke.native_failure_summary(path)
            self.assertEqual(result['status'],'failed');self.assertEqual(len(result['error']),2000)
            self.assertEqual(len(result['error_traceback']),4000)
            self.assertEqual(result['last_completed_checks'],['step '+str(i) for i in range(12,20)])
            self.assertTrue(result['capture_passed']);self.assertNotIn('ocr_passed',result)
            self.assertNotIn('image_base64',result);self.assertNotIn('environment',result)
            self.assertEqual(len(result['native_report_sha256']),64)
            self.assertEqual(result['duty_case_count'],9);self.assertEqual(len(result['duty_cases']),5)
            self.assertEqual(len(result['duty_cases'][0]['name']),80)
            self.assertNotIn('total_ms',result['duty_cases'][0]);self.assertNotIn('private',result['duty_cases'][0])
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
