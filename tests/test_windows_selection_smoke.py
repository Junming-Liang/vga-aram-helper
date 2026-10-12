"""Portable selection-harness contracts, never actual Windows handoff proof."""
import ast
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
    def good_report(self):
        return dict(status='passed', backend='qtwidgets', qt_platform='windows', frozen=True,
                    applicationVersion='0.4.1', **dict.fromkeys(smoke.FIELDS, True))

    def test_report_requires_every_native_identity_and_six_flags(self):
        smoke.validate_report(self.good_report(), '0.4.1')
        for field, value in [('status', 'running'), ('backend', 'browser'), ('qt_platform', 'offscreen'),
                             ('frozen', False), ('applicationVersion', '0.4.0'), ('error', 'problem')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        for field in smoke.FIELDS:
            for value in (False, None, 1, 'true'):
                with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                    smoke.validate_report(dict(self.good_report(), **{field: value}), '0.4.1')
        self.assertEqual(len(smoke.FIELDS), 6)

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
        self.assertIn("handoff_path = work / 'windows-selection-handoff.json'", source)
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
