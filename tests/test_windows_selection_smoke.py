"""Portable selection-harness contracts, never actual Windows handoff proof."""
import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_selection_smoke as smoke


class SelectionHarnessTests(unittest.TestCase):
    def good_report(self, *, frozen=True, scale=1):
        labels = {}
        rects = {'hero': (5, 5, 150, 20), 'tier': (170, 5, 180, 20),
                 'metadata': (5, 30, 440, 30), 'heading': (5, 65, 280, 20), 'footer': (300, 65, 145, 20)}
        for role, expected in smoke.EXPECTED_TEXT.items():
            labels[role] = {'text': expected, 'visible': True, 'minimum_width': 100,
                'required_height_at_width': 20, 'logical_rect': dict(zip(('x','y','width','height'),rects[role])),
                'accessible_name': ('当前分配英雄：星火术士（演示）' if role == 'hero'
                                    else '虚构英雄评级（演示）：T5' if role == 'tier' else '')}
        reference = {'reference': dict(smoke.EXPECTED_REFERENCE), 'assigned': '9001', 'stage': 'assigned',
            'state_hero': '星火术士（演示）', 'observation_count': 2, 'confirmed': False, 'offered': [],
            'augment_card_count': 0, 'visible': True, 'native_visible': True, 'foreground_preserved': True,
            'overlay_hwnd': 300, 'click_through_hit_hwnd': 100, 'window_style': 0x80000|0x08000000|0x20|0x8|0x80,
            'client_rect': {'x':20,'y':20,'width':964,'height':602},
            'overlay_rect': {'x':30,'y':400,'width':round(450*scale),'height':round(100*scale)},
            'logical_size': {'width':450,'height':100}, 'qt_dpr': scale, 'labels': labels}
        result = dict(schemaVersion=2, status='passed', phase='complete', backend='qtwidgets',
                    qt_platform='windows', frozen=frozen, applicationVersion='0.4.1',
                    requested_app_scale=scale, window_closed=True, foreground_recovery_start_count=2,
                    foreground_recovery_observations=2, recognizedHero='星火术士（演示）',
                    assignedHero='星火术士（演示）', recognized=['星火共鸣','晶盾回路','风步微光'],
                    provenance='client-provisional', renderedHeading='星火术士（演示） · 来自本局选人 · HUD未复核',
                    clientHwnd=100,clientPid=101,gameHwnd=200,gamePid=201,clientGeneration=2,
                    client_hero_reference=reference, client_hero_safety=dict.fromkeys(smoke.SAFETY_FIELDS,True),
                    **dict.fromkeys(smoke.FIELDS, True))
        if frozen:
            result['executable_sha256']='c'*64
        return result

    def good_aggregate(self, *, frozen=True):
        value = {'schemaVersion':2, 'status':'passed', 'frozen':frozen, 'applicationVersion':'0.4.1',
                 'source_commit':'a'*40, 'source_files':dict.fromkeys(smoke.SOURCE_FILES,'b'*64),
                 'scales':list(smoke.SCALES), 'runs':[]}
        if frozen:
            value['executable_sha256']='c'*64
            value['executable_size']=123456
        for scale in smoke.SCALES:
            row = {'app_scale':scale, 'applicationVersion':'0.4.1', 'fixture_source_sha256':'b'*64,
                   'native_report':smoke.native_report_name(frozen,scale), 'native_report_sha256':'e'*64,
                   'detail':self.good_report(frozen=frozen,scale=scale), 'process_exited':True,
                   'owned_processes_exited':True, 'game_launched_after_selection_request':True,
                   'completed_fields':list(smoke.FIELDS),
                   'client':{'hwnd':100,'pid':101,'class_name':smoke.CLASSES['client'],'client_size':[964,602]},
                   'game':{'hwnd':200,'pid':201,'class_name':smoke.CLASSES['game'],'client_size':[964,602]}}
            if frozen:
                row['executable_sha256']='c'*64
            value['runs'].append(row)
        value.update({key:copy.deepcopy(value['runs'][0][key]) for key in ('process_exited',
            'owned_processes_exited','game_launched_after_selection_request','native_report','native_report_sha256',
            'fixture_source_sha256','completed_fields','client','game')})
        return value

    def test_report_requires_every_native_identity_and_all_original_and_new_flags(self):
        smoke.validate_report(self.good_report(), '0.4.1')
        for field, value in [('status', 'running'), ('backend', 'browser'), ('qt_platform', 'offscreen'),
                             ('frozen', False), ('applicationVersion', '0.4.0'), ('error', 'problem'),
                             ('schemaVersion', True), ('window_closed', False), ('clientHwnd', True),
                             ('foreground_recovery_start_count',True),('foreground_recovery_observations',1),
                             ('requested_app_scale', True), ('requested_app_scale',1.5),
                             ('recognized',['风步微光','晶盾回路','星火共鸣']), ('provenance','hud')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        for field in smoke.FIELDS:
            for value in (False, None, 1, 'true'):
                with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                    smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        self.assertEqual(len(smoke.FIELDS), 10)
        self.assertEqual(smoke.FIELDS[:6], ('champion_select_own_row_passed','champion_select_ambiguity_passed',
            'champion_select_session_carry_passed','champion_select_stale_clear_passed',
            'champion_select_window_scope_passed','metadata_query_passed'))

    def test_native_reports_require_source_or_frozen_at_each_exact_scale(self):
        for frozen in (False,True):
            for scale in smoke.SCALES:
                value=self.good_report(frozen=frozen,scale=scale)
                smoke.validate_report(value,'0.4.1',frozen=frozen,scale=scale)
                with self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1',frozen=not frozen,scale=scale)
                with self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1',frozen=frozen,scale=scale+.5)

    def test_literal_hero_reference_and_no_augment_confirmation_are_strict(self):
        mutations=[('assigned','9002'),('stage','assigning'),('state_hero',''),('observation_count',1),
            ('observation_count',True),('observation_count',2.0),('confirmed',True),('confirmed',0),
            ('offered',['星火共鸣']),('offered',()),('augment_card_count',False),('augment_card_count',3),
            ('visible',False),('native_visible',False),('foreground_preserved',False),
            ('click_through_hit_hwnd',300),('qt_dpr',True),('qt_dpr',float('nan')),('qt_dpr',2),
            ('window_style',0),('window_style',-1),('window_style',2**32+0x080800A8),
            ('window_style',0x08080028),('overlay_hwnd',100)]
        for key,replacement in mutations:
            value=self.good_report();value['client_hero_reference'][key]=replacement
            with self.subTest(key=key,replacement=replacement),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')
        for key,replacement in [('championId','9002'),('hero','未知英雄'),('sourceTier','T1'),
            ('sourceTierLabel','虎牙公开源英雄评级'),('sourceLabel','unknown'),('sourceDataDate','2026-01-03'),
            ('sourceVersion','0.2'),('gamePatch','0.1'),('wikiDataVersion','latest'),
            ('sourceUrl','https://example.com'),('isDemo',1)]:
            value=self.good_report();value['client_hero_reference']['reference'][key]=replacement
            with self.subTest(reference=key),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')
        for key in smoke.SAFETY_FIELDS:
            value=self.good_report();del value['client_hero_safety'][key]
            with self.subTest(safety=key),self.assertRaises(AssertionError):
                smoke.validate_report(value,'0.4.1')

    def test_visible_label_and_native_geometry_forgery_is_rejected(self):
        for field in ('client_rect','overlay_rect'):
            for key,replacement in [('x',True),('width',450.0),('height',0),('width',-1)]:
                value=self.good_report();value['client_hero_reference'][field][key]=replacement
                with self.subTest(field=field,key=key),self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1')
        for role in smoke.EXPECTED_TEXT:
            for key,replacement in [('text',''),('visible',1),('minimum_width',1000),
                                    ('required_height_at_width',1000),('accessible_name','forged')]:
                value=self.good_report();value['client_hero_reference']['labels'][role][key]=replacement
                with self.subTest(role=role,key=key),self.assertRaises(AssertionError):
                    smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['overlay_rect']['height']=302
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['labels']['hero']['logical_rect']['x']=1000
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();value['client_hero_reference']['labels']['tier']['logical_rect']['x']=5
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')
        value=self.good_report();del value['client_hero_reference']['labels']['metadata']
        with self.assertRaises(AssertionError):smoke.validate_report(value,'0.4.1')

    def test_aggregate_requires_three_complete_independently_bound_runs(self):
        for frozen in (True,False):
            value=self.good_aggregate(frozen=frozen)
            smoke.validate_aggregate(value,'0.4.1',frozen=frozen,source_commit='a'*40,
                                     executable_sha256='c'*64 if frozen else None)
            for key,replacement in [('status','failed'),('schemaVersion',True),('frozen',not frozen),
                ('source_commit','d'*40),('source_files',{}),('scales',[True,1.5,2]),('scales',[1,1.5]),
                ('process_exited',1),('native_report','other.json'),('native_report_sha256','f'*64),
                ('fixture_source_sha256','f'*64),('runs',value['runs'][:2])]:
                changed=copy.deepcopy(value);changed[key]=replacement
                with self.subTest(frozen=frozen,key=key),self.assertRaises(AssertionError):
                    smoke.validate_aggregate(changed,'0.4.1',frozen=frozen,source_commit='a'*40)
            for index in range(3):
                for key,replacement in [('app_scale',True),('native_report','other.json'),('detail',{}),
                    ('process_exited',False),('owned_processes_exited',False),
                    ('game_launched_after_selection_request',False),('completed_fields',[]),
                    ('applicationVersion','9.9.9'),('fixture_source_sha256','d'*64),('native_report_sha256',''),('client',{})]:
                    changed=copy.deepcopy(value);changed['runs'][index][key]=replacement
                    with self.subTest(frozen=frozen,index=index,key=key),self.assertRaises(AssertionError):
                        smoke.validate_aggregate(changed,'0.4.1',frozen=frozen)
        for size in (None,True,0,-1,123456.0):
            value=self.good_aggregate();value['executable_size']=size
            with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate()
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True,executable_size=999)
        value=self.good_aggregate();value['runs'][2]['client']['client_size']=[964.0,602]
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['client']['hwnd']=100.0
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['runs'][2]['detail']['executable_sha256']='d'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate();value['runs'][2]['executable_sha256']='d'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=True)
        value=self.good_aggregate(frozen=False);value['executable_sha256']='c'*64
        with self.assertRaises(AssertionError):smoke.validate_aggregate(value,'0.4.1',frozen=False)

    def test_standard_runner_geometry_and_too_small_desktop(self):
        self.assertEqual(smoke.fixture_dimensions(1024, 768), {'client': (964, 602), 'game': (964, 602)})
        self.assertEqual(smoke.fixture_dimensions(1920, 1080)['game'], (964, 602))
        for bounds in ((800, 600), (1024, 650), (True, 768)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                smoke.fixture_dimensions(*bounds)

    def test_environment_removes_test_overrides_preserves_original_network(self):
        with tempfile.TemporaryDirectory() as directory:
            original = {'SystemRoot': r'C:\Windows', 'Path': r'C:\Python312', 'QT_QPA_PLATFORM': 'offscreen',
                        'VGA_FORGED_REPORT': 'yes', '_PYI_ARCHIVE_FILE': 'outside', 'PYSIDE_PLUGIN': 'outside',
                        'HTTPS_PROXY': 'http://existing-authorized-proxy:8000'}
            env = smoke.child_environment(original, Path(directory).resolve())
            self.assertEqual(env['PATH'], r'C:\Windows\System32;C:\Windows')
            self.assertEqual(env['HTTPS_PROXY'], original['HTTPS_PROXY'])
            self.assertEqual(env['VGA_STATE_DIR'], str(Path(directory).resolve() / 'state'))
            self.assertTrue(Path(env['TEMP']).is_dir())
            for key in ('QT_QPA_PLATFORM', 'VGA_FORGED_REPORT', '_PYI_ARCHIVE_FILE', 'PYSIDE_PLUGIN'):
                self.assertNotIn(key, env)
            self.assertEqual(original['QT_QPA_PLATFORM'], 'offscreen')
            self.assertEqual(env['QT_SCALE_FACTOR'], '1')

    def test_report_read_waits_for_exact_phase_or_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'report.json'
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text('{')
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text(json.dumps({'status': 'running', 'phase': 'selected'}))
            self.assertIsNone(smoke.report_when(path, 'await-game-window'))
            path.write_text(json.dumps({'status': 'running', 'phase': 'await-game-window'}))
            self.assertEqual(smoke.report_when(path, 'await-game-window')['phase'], 'await-game-window')
            self.assertIsNone(smoke.report_when(path, terminal=True))
            path.write_text(json.dumps(self.good_report()))
            self.assertEqual(smoke.report_when(path, terminal=True)['status'], 'passed')
            path.write_text(json.dumps({'status': 'failed', 'error': 'expected'}))
            with self.assertRaisesRegex(AssertionError, 'expected'):
                smoke.report_when(path, terminal=True)

    def test_mismatched_owned_pid_blocks_before_foreground(self):
        native = Mock()
        native.poll.return_value = None
        native.windows.return_value = [{'hwnd': 100, 'pid': 200}]
        with self.assertRaisesRegex(AssertionError, 'exact owned'):
            smoke.foreground_owned(native, {'pid': 201}, Path('own.exe'), 'client',
                                   {'hwnd': 100, 'pid': 200}, (960, 540))
        native.u.ShowWindow.assert_not_called()
        native.u.SetForegroundWindow.assert_not_called()

    def test_exited_owned_fixture_blocks_before_window_mutation(self):
        native = Mock()
        native.poll.return_value = 0
        with self.assertRaisesRegex(AssertionError, 'exited'):
            smoke.foreground_owned(native, {'pid': 201}, Path('own.exe'), 'client',
                                   {'hwnd': 100, 'pid': 201}, (960, 540))
        native.windows.assert_not_called()
        native.u.SetForegroundWindow.assert_not_called()

    def test_logs_are_bounded_no_png_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve() / 'work'; reports = Path(directory).resolve() / 'reports'
            logs = work / 'state' / 'logs'; logs.mkdir(parents=True); reports.mkdir()
            (logs / 'diagnostic.txt').write_text('original test')
            (logs / 'screen.png').write_bytes(b'never collect screenshots')
            (work / 'client-ready.json.error.txt').write_text('original error')
            self.assertEqual(smoke.collect_logs(work, reports),
                             ['windows-selection-diagnostic.txt', 'windows-selection-client-ready.json.error.txt'])
            (logs / 'large.txt').write_bytes(b'x' * (smoke.MAX_LOG_BYTES + 1))
            with self.assertRaisesRegex(AssertionError, 'bound'):
                smoke.collect_logs(work, reports)

    def test_lifecycle_contract_launches_new_game_only_after_app_request(self):
        source = Path(smoke.__file__).read_text()
        self.assertLess(source.index("Deadline.wait(awaiting_game"), source.index("game = native.spawn"))
        self.assertIn("'scope': 'owned-synthetic-only'", source)
        self.assertIn("native.wait_exit(app", source)
        self.assertIn('native.close_window(window)', source)
        self.assertIn('lambda: not native.pids()', source)
        self.assertIn('native.cleanup()', source)
        self.assertIn('work = work.resolve()', source)
        self.assertIn('handoff_path = work / native_report_name(frozen, scale)', source)
        self.assertIn('for scale in SCALES:', source)
        self.assertIn("current.get('phase') != 'testing-client-foreground-loss'",source)
        self.assertIn('print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)', source)
        self.assertLessEqual(smoke.MAX_SECONDS + smoke.DIRECTORY_CLEANUP_SECONDS, 270)
        self.assertEqual(smoke.JOB_CLEANUP_SECONDS, 15)
        for forbidden in ('SendInput', 'AttachThreadInput', 'SetWindowsHookEx', 'ReadProcessMemory',
                          'WriteProcessMemory', 'resolver=', 'taskkill', 'TerminateProcess(', 'ChangeDisplaySettings'):
            self.assertNotIn(forbidden, source)
        self.assertIn('synthetic policy', source.replace('\n', ' '))

    def test_source_imports_no_production_identity_stubs(self):
        tree = ast.parse(Path(smoke.__file__).read_text())
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn('session_windows', modules)
        self.assertNotIn('unittest.mock', modules)
        self.assertIn('windows_ota_smoke', modules)


if __name__ == '__main__':
    unittest.main()
