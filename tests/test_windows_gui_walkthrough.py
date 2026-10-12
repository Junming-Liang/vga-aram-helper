"""Portable safety/contract tests, not actual interactive Windows GUI evidence."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('windows_gui_walkthrough',ROOT/'tests/windows_gui_walkthrough.py')
gui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class WindowsGuiWalkthroughTests(unittest.TestCase):
    def test_exact_public_fixture_identity(self):
        self.assertEqual(gui.EXPECTED_SHA256,'40b8d2af8309278b9cf6a5eace8ca26d6a483f659578d441636b86369d66cf6e')
        self.assertEqual(gui.EXPECTED_SIZE,150155259)
        self.assertEqual(gui.FIXTURE_MANIFEST['version'],'0.3.0')

    def test_non_executable_and_changed_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'untrusted.exe';file.write_bytes(b'MZnot the public fixture')
            with self.assertRaisesRegex(AssertionError,'mismatch'):
                gui.validate_executable(file)
            with self.assertRaisesRegex(AssertionError,'exact public'):
                gui.validate_executable(file.with_suffix('.txt'))

    def test_environment_is_fresh_but_retains_normal_network(self):
        with tempfile.TemporaryDirectory() as directory:
            original={'SystemRoot':r'C:\Windows','Path':r'C:\Python312','PYTHONPATH':'outside',
                      'QT_QPA_PLATFORM':'offscreen','QT_PLUGIN_PATH':'outside','VGA_STATE_DIR':'outside',
                      'VGA_FAKE_DATA':'outside','_PYI_ARCHIVE_FILE':'outside','PYSIDE_DESIGNER_PLUGINS':'outside',
                      'HTTPS_PROXY':'http://existing-authorized-network:8000'}
            env=gui.normal_environment(original,Path(directory))
            self.assertEqual(env['VGA_STATE_DIR'],str(Path(directory)/'state'))
            self.assertEqual(env['HTTPS_PROXY'],original['HTTPS_PROXY'])
            self.assertEqual(env['PATH'],r'C:\Windows\System32;C:\Windows')
            self.assertTrue(Path(env['TEMP']).is_dir())
            for key in ('QT_QPA_PLATFORM','QT_PLUGIN_PATH','VGA_FAKE_DATA','PYTHONPATH','_PYI_ARCHIVE_FILE','PYSIDE_DESIGNER_PLUGINS'):
                self.assertNotIn(key,env)
            self.assertEqual(original['QT_QPA_PLATFORM'],'offscreen')

    def test_normal_exe_spawn_has_zero_arguments(self):
        tree=ast.parse((ROOT/'tests/windows_gui_walkthrough.py').read_text())
        launches=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                  and node.func.attr=='spawn' and node.args and isinstance(node.args[0],ast.Name) and node.args[0].id=='target']
        self.assertEqual(len(launches),1)
        self.assertIsInstance(launches[0].args[1],ast.List)
        self.assertEqual(launches[0].args[1].elts,[])

    def test_helper_uses_read_only_uia_actual_os_capture_and_normal_policy(self):
        source=(ROOT/'tests/windows_gui_walkthrough.py').read_text()
        self.assertIn('CopyFromScreen',gui.POWERSHELL_HELPER)
        self.assertIn('FromHandle',gui.POWERSHELL_HELPER)
        self.assertIn('TryGetCurrentPattern',gui.POWERSHELL_HELPER)
        self.assertIn("encoding='utf-8-sig'",source)
        self.assertIn('WindowsPowerShell/v1.0/powershell.exe',source)
        for forbidden in ('ExecutionPolicy','SetWindowDisplayAffinity(','PrintWindow','InvokePattern','SetValue(',
                          'SetWindowsHookEx','WriteProcessMemory','CreateRemoteThread','AttachThreadInput'):
            self.assertNotIn(forbidden,source)

    def test_budget_includes_bounded_cleanup_and_pngs(self):
        self.assertLessEqual(gui.MAX_SECONDS+45,300)
        self.assertLessEqual(gui.MAX_SCREENSHOT_BYTES,6*1024*1024)
        self.assertLessEqual(gui.MAX_SCREENSHOTS,5)
        self.assertEqual(gui.STAGES[1],'interactive_desktop')
        self.assertEqual(gui.STAGES[-1],'close')

    def test_stage_failure_is_explicit_and_preserves_completed_stages(self):
        report={'stages':[]}
        with gui.stage(report,'artifact'):pass
        with self.assertRaisesRegex(RuntimeError,'locked'):
            with gui.stage(report,'interactive_desktop'):
                raise RuntimeError('locked desktop')
        self.assertEqual([s['status'] for s in report['stages']],['passed','failed'])
        self.assertEqual(report['stages'][1]['error'],'locked desktop')

    def test_uia_lookup_rejects_ambiguous_or_absent_controls(self):
        node={'name':'停止','type':'ControlType.Button','value':None}
        self.assertEqual(gui.element([node],'停止','Button'),node)
        self.assertEqual(gui.text_values([node]),['停止'])
        for nodes in ([],[node,node]):
            with self.assertRaisesRegex(AssertionError,'Expected one'):
                gui.element(nodes,'停止','Button')

    def test_foreground_accepts_only_exact_window_or_same_pid_owned_popup(self):
        desktop=object.__new__(gui.Desktop)
        desktop.owned=Mock(return_value=10)
        desktop.pid=Mock(side_effect=lambda hwnd:{100:10,101:10,200:20}.get(hwnd,0))
        desktop.u=Mock()
        desktop.u.GetAncestor.return_value=100
        desktop.foreground(100)
        desktop.u.GetAncestor.return_value=101;desktop.u.GetWindow.return_value=100
        desktop.foreground(100)
        desktop.u.GetAncestor.return_value=200
        with self.assertRaisesRegex(AssertionError,'not foreground'):
            desktop.foreground(100)
        desktop.u.GetAncestor.return_value=101;desktop.u.GetWindow.return_value=0
        with self.assertRaisesRegex(AssertionError,'not foreground'):
            desktop.foreground(100)

    def test_input_guard_runs_before_every_sendinput(self):
        desktop=object.__new__(gui.Desktop)
        desktop.foreground=Mock(side_effect=AssertionError('outside owned target'))
        desktop.u=Mock()
        with self.assertRaisesRegex(AssertionError,'outside owned'):
            desktop.send(123,[])
        desktop.foreground.assert_called_once_with(123)
        desktop.u.SendInput.assert_not_called()

    def test_unknown_window_rejected_by_job_pid_guard(self):
        desktop=object.__new__(gui.Desktop)
        desktop.pid=Mock(return_value=90);desktop.job=Mock()
        desktop.job.pids.return_value={91,92}
        with self.assertRaisesRegex(AssertionError,'private test process job'):
            desktop.owned(10)

    def test_screenshot_blocked_before_capture_when_region_is_unowned(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture,desktop=Mock(),Mock()
            desktop.capture_guard.side_effect=AssertionError('unowned occluder')
            evidence=gui.Evidence(Path(directory),fixture,desktop)
            with self.assertRaisesRegex(AssertionError,'unowned'):
                evidence.capture('blocked',123)
            fixture.ask.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_screenshot_deleted_if_post_capture_guard_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture,desktop=Mock(),Mock()
            desktop.capture_guard.side_effect=[[0,0,100,100],[1,0,100,100]]
            def capture(op,**args):
                Path(args['path']).write_bytes(b'\x89PNG\r\n\x1a\nprivate-race-pixels')
                return {'method':'System.Drawing.Graphics.CopyFromScreen'}
            fixture.ask.side_effect=capture
            evidence=gui.Evidence(Path(directory),fixture,desktop)
            with self.assertRaisesRegex(AssertionError,'changed'):
                evidence.capture('moved',123)
            self.assertEqual(evidence.records,[])
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_screenshot_count_budget_fails_before_capture(self):
        evidence=gui.Evidence(Path('.'),Mock(),Mock())
        evidence.records=[{}]*gui.MAX_SCREENSHOTS
        with self.assertRaisesRegex(AssertionError,'count budget'):
            evidence.capture('excess',123)
        evidence.desktop.capture_guard.assert_not_called()

    def test_region_intersections_include_one_pixel_occlusion(self):
        self.assertTrue(gui.intersects([0,0,100,100],[99,99,10,10]))
        self.assertFalse(gui.intersects([0,0,100,100],[100,0,10,10]))

    def test_normal_startup_waits_for_source_and_button_in_one_snapshot(self):
        button={'name':'开始窗口截图监测','enabled':True}
        source={'name':'软件 0.3.0 · 来源日期 2026-09-07 · 游戏资料版本 16.17 · 本次启动已校验虎牙海斗 wiki 数据。','enabled':True}
        stale=[{'name':'正在检查公开数据，首次启动可能需要数十秒…','enabled':True},button]
        self.assertFalse(gui.normal_startup_ready(stale))
        self.assertFalse(gui.normal_startup_ready([source,dict(button,enabled=False)]))
        self.assertTrue(gui.normal_startup_ready([source,button]))
        self.assertFalse(gui.normal_startup_ready([source,source,button]))
        for invalid in ('虚构演示 软件 0.3.0 · 来源日期 2026-09-07','资料加载失败 软件 0.3.0 · 来源日期 2026-09-07'):
            self.assertFalse(gui.normal_startup_ready([dict(source,name=invalid),button]))

    def test_actual_qt_combo_value_contract_and_geometry_order(self):
        target={'name':'1 选择窗口与英雄','type':'ControlType.ComboBox','value':'请选择你要监测的游戏窗口','rect':[112,170,808,33]}
        hero={'name':'手动确认英雄','type':'ControlType.ComboBox','value':gui.HERO,'rect':[112,210,884,33]}
        self.assertEqual(gui.combo_boxes([hero,target]),[target,hero])
        self.assertEqual(gui.text_values(gui.combo_boxes([hero,target])),['请选择你要监测的游戏窗口',gui.HERO])
        with self.assertRaises(AssertionError):gui.combo_boxes([target])

    def test_stale_uia_startup_snapshot_is_retried_before_acceptance(self):
        button={'name':'开始窗口截图监测','enabled':True}
        ready=[button,{'name':'软件 0.3.0 · 来源日期 2026-09-07','enabled':True}]
        fixture=Mock();fixture.snapshot.side_effect=[[button],ready]
        observed=gui.wait_nodes(fixture,Mock(),123,gui.normal_startup_ready,gui.time.monotonic()+2,'not ready')
        self.assertEqual(observed,ready)
        self.assertEqual(fixture.snapshot.call_count,2)

    def test_clickthrough_requires_event_time_visible_owned_overlay(self):
        event={'hwnd':123,'pid':45,'visible':True,'contains_click':True,'transparent_input':True,
               'extended_style':0x00080000|0x08000000|0x80|0x8|0x20,'observed_at':'actual fixture MouseDown event'}
        self.assertTrue(gui.valid_overlay_click({'click_overlay':event},123,45))
        self.assertFalse(gui.valid_overlay_click({},123,45))
        for field,value in (('hwnd',999),('pid',99),('visible',False),('contains_click',False),
                            ('transparent_input',False),('extended_style',0x20),('observed_at','before click')):
            with self.subTest(field=field):
                self.assertFalse(gui.valid_overlay_click({'click_overlay':dict(event,**{field:value})},123,45))

    def test_both_capture_and_controller_verify_physical_dpi_context(self):
        source=(ROOT/'tests/windows_gui_walkthrough.py').read_text()
        self.assertIn('Fixture capture process is not verified per-monitor-v2 DPI aware',gui.POWERSHELL_HELPER)
        self.assertIn('Controller is not verified per-monitor-v2 DPI aware',source)
        self.assertIn('AreDpiAwarenessContextsEqual',gui.POWERSHELL_HELPER)
        self.assertIn("copy_operation='SourceCopy (0x00CC0020), without CAPTUREBLT'",gui.POWERSHELL_HELPER)

    def test_scroll_refuses_non_scrollbar_before_input(self):
        desktop=object.__new__(gui.Desktop);desktop.click=Mock()
        with self.assertRaisesRegex(AssertionError,'UIA scrollbar'):
            desktop.wheel(123,{'type':'ControlType.Spinner','offscreen':False,'enabled':True,'rect':[0,0,20,200]})
        desktop.click.assert_not_called()

    def test_nonwindows_reports_failed_and_not_run_never_passed(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(gui,'os',SimpleNamespace(name='posix',environ=os.environ)):
            code=gui.main(['--exe','missing.exe','--report-dir',directory])
            report=json.loads((Path(directory)/'windows-gui-walkthrough.json').read_text())
            self.assertEqual(code,1)
            self.assertEqual(report['status'],'failed')
            self.assertTrue(all(s['status']=='not_run' for s in report['stages']))
            self.assertEqual(report['screenshots'],[])
            self.assertIn('not Windows',report['error'])

    def test_public_cache_must_be_fresh_nondemo_and_contain_real_catalog_names(self):
        import data_updates,engine
        good={'status':{'usingCached':False,'sourceMode':'official-wiki'},'data':{}}
        normalized={'metadata':{'isDemo':False},'heroes':{gui.HERO:{}},'augments':{name:{} for name in gui.NAMES}}
        with patch.object(data_updates,'load_cached_data',return_value=good),patch.object(engine,'normalize',return_value=normalized):
            self.assertFalse(gui.validate_public_cache(Path('unused'))['usingCached'])
        for bad in (None,{'status':{'usingCached':True},'data':{}}):
            with patch.object(data_updates,'load_cached_data',return_value=bad),self.assertRaises(AssertionError):
                gui.validate_public_cache(Path('unused'))
        for field,value in (('metadata',{'isDemo':True}),('heroes',{}),('augments',{})):
            with patch.object(data_updates,'load_cached_data',return_value=good),patch.object(engine,'normalize',return_value=dict(normalized,**{field:value})),self.assertRaises(AssertionError):
                gui.validate_public_cache(Path('unused'))


if __name__=='__main__':
    unittest.main()
