"""Platform-neutral checks for packaging contracts; not Windows execution proof."""
from contextlib import redirect_stdout
import ast
import inspect
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launcher
import model_inventory
spec = importlib.util.spec_from_file_location('build_windows', ROOT / 'scripts' / 'build_windows.py')
build_windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_windows)
smoke_spec = importlib.util.spec_from_file_location('windows_exe_smoke', ROOT / 'tests' / 'windows_exe_smoke.py')
windows_exe_smoke = importlib.util.module_from_spec(smoke_spec)
smoke_spec.loader.exec_module(windows_exe_smoke)


class PackagingTests(unittest.TestCase):
    def test_smoke_cleanup_retries_transient_windows_image_lock(self):
        with patch.object(windows_exe_smoke.shutil, 'rmtree', side_effect=[PermissionError('image locked'), PermissionError('scanner'), None]) as remove, \
             patch.object(windows_exe_smoke.time, 'sleep') as sleep:
            windows_exe_smoke.remove_smoke_directory(Path('temporary'))
        self.assertEqual(remove.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_smoke_cleanup_permanent_failure_is_not_ignored(self):
        with patch.object(windows_exe_smoke.shutil, 'rmtree', side_effect=PermissionError('still locked')), \
             patch.object(windows_exe_smoke.time, 'monotonic', side_effect=[0, 31]), \
             patch.object(windows_exe_smoke.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                windows_exe_smoke.remove_smoke_directory(Path('temporary'), timeout=30)
            sleep.assert_not_called()

    def test_smoke_windows_shutdown_waits_for_process_tree_command(self):
        process = Mock(pid=123, poll=lambda: None)
        with patch.object(windows_exe_smoke.os, 'name', 'nt'), \
             patch.object(windows_exe_smoke.subprocess, 'run', return_value=Mock(returncode=0)) as kill:
            windows_exe_smoke.terminate_tree(process)
        self.assertEqual(kill.call_args.args[0], ['taskkill', '/PID', '123', '/T', '/F'])
        process.wait.assert_called_once_with(timeout=20)

    def test_smoke_shutdown_failure_is_not_silently_accepted(self):
        process = Mock(pid=123, poll=lambda: None)
        with patch.object(windows_exe_smoke.os, 'name', 'nt'), \
             patch.object(windows_exe_smoke.subprocess, 'run', return_value=Mock(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, 'process-tree shutdown'):
                windows_exe_smoke.terminate_tree(process)
        process.kill.assert_called_once()

    def test_smoke_cleanup_failure_keeps_report_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exe = root / 'fixture.exe'
            exe.write_bytes(b'test fixture, not a runnable EXE')
            @windows_exe_smoke.contextmanager
            def failing_workspace():
                raise PermissionError('cleanup blocked')
                yield root
            with patch.object(windows_exe_smoke.os, 'name', 'nt'), \
                 patch.object(windows_exe_smoke, 'smoke_workspace', failing_workspace), \
                 patch.object(windows_exe_smoke.argparse.ArgumentParser, 'parse_args', return_value=Mock(exe=exe, report_dir=root, browser=False)), \
                 redirect_stdout(io.StringIO()):
                with self.assertRaises(PermissionError):
                    windows_exe_smoke.main()
            report = json.loads((root / 'windows-exe-smoke.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'failed')
            self.assertIn('cleanup blocked', report['error'])

    def test_smoke_pass_status_is_outside_cleanup_contexts(self):
        tree = ast.parse(inspect.getsource(windows_exe_smoke.main))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                       and isinstance(node.value, ast.Constant) and node.value.value == 'passed']
        self.assertEqual(len(assignments), 1)
        node = assignments[0]
        while node in parents:
            node = parents[node]
            self.assertNotIsInstance(node, ast.With, 'Passing cannot be recorded before cleanup contexts exit')

    def test_smoke_shutdown_command_timeout_fails_and_reaps_parent(self):
        process = Mock(pid=123, poll=lambda: None)
        with patch.object(windows_exe_smoke.os, 'name', 'nt'), \
             patch.object(windows_exe_smoke.subprocess, 'run', side_effect=windows_exe_smoke.subprocess.TimeoutExpired('taskkill', 20)):
            with self.assertRaisesRegex(RuntimeError, 'command timed out'):
                windows_exe_smoke.terminate_tree(process)
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)

    def test_smoke_environment_handles_uppercase_systemroot(self):
        original = {'SYSTEMROOT': r'C:\Windows', 'PATH': r'C:\Python312', 'TEMP': r'C:\Temp'}
        result = windows_exe_smoke.isolated_windows_environment(original, Path('work'))
        self.assertEqual(result['PATH'], r'C:\Windows\System32;C:\Windows')
        self.assertEqual(result['SYSTEMROOT'], r'C:\Windows')
        self.assertEqual(result['TEMP'], r'C:\Temp')
        self.assertEqual(original['PATH'], r'C:\Python312')

    def test_smoke_environment_removes_python_regardless_of_case(self):
        original = {'SystemRoot': r'C:\Windows', 'Path': r'C:\Python312', 'PythonHome': 'bad',
                    'PythonPath': 'bad', 'virtual_env': 'bad', 'conda_prefix': 'bad', 'LocalAppData': 'old'}
        result = windows_exe_smoke.isolated_windows_environment(original, Path('work'))
        self.assertEqual(result['PATH'], r'C:\Windows\System32;C:\Windows')
        self.assertEqual(result['LOCALAPPDATA'], str(Path('work') / 'local-appdata'))
        self.assertEqual(result['VGA_STATE_DIR'], str(Path('work') / 'state'))
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
            self.assertNotIn(key, result)
        self.assertTrue(all(key == key.upper() for key in result))

    def test_smoke_environment_accepts_windir_or_fails_closed(self):
        result = windows_exe_smoke.isolated_windows_environment({'windir': r'D:\Windows'}, Path('work'))
        self.assertEqual(result['SYSTEMROOT'], r'D:\Windows')
        self.assertEqual(result['PATH'], r'D:\Windows\System32;D:\Windows')
        for environ in ({}, {'SYSTEMROOT': 'relative'}):
            with self.subTest(environ=environ), self.assertRaises(RuntimeError):
                windows_exe_smoke.isolated_windows_environment(environ, Path('work'))

    def test_version_command_has_no_ocr_or_update_dependency(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as result:
            launcher.main(['--version'])
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), launcher.__version__)

    def test_json_ready_record_atomic_and_unicode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '目录' / 'ready.json'
            launcher.write_json(path, {'application': 'VGA乱斗助手'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['application'], 'VGA乱斗助手')
            self.assertFalse(path.with_name('ready.json.tmp').exists())

    def test_missing_model_fails_without_downloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, '缺少'):
                model_inventory.verify_models(temporary)

    def test_changed_model_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            name = next(iter(model_inventory.EXPECTED_MODELS))
            (Path(temporary) / name).write_bytes(b'wrong model')
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                model_inventory.verify_models(temporary)

    def test_verified_model_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = b'unit-test model bytes'
            (Path(temporary) / 'fixture.onnx').write_bytes(raw)
            with patch.dict(model_inventory.EXPECTED_MODELS, {'fixture.onnx': hashlib.sha256(raw).hexdigest()}, clear=True):
                result = model_inventory.verify_models(temporary)
            self.assertEqual(result[0]['size'], len(raw))
            self.assertEqual(result[0]['name'], 'fixture.onnx')

    def test_manifest_hashes_actual_file_and_pins_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            exe = Path(temporary) / 'file.exe'
            exe.write_bytes(b'unit-test EXE placeholder, not executable')
            result = build_windows.release_manifest(exe, '0.3.0')
            self.assertEqual(result['schema_version'], 1)
            self.assertEqual(result['platform'], 'windows-x64')
            self.assertEqual(result['sha256'], hashlib.sha256(exe.read_bytes()).hexdigest())
            self.assertEqual(result['size'], exe.stat().st_size)
            self.assertEqual(result['url'], 'https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.0/vga-aram-helper-0.3.0-windows-x64.exe')

    def test_apply_update_dispatch(self):
        import types
        updates = types.ModuleType('updates')
        updates.apply_update = lambda path: 7 if path == Path('plan.json') else 2
        with patch.dict(sys.modules, {'updates': updates}):
            self.assertEqual(launcher.main(['--apply-update', 'plan.json']), 7)

    def test_self_test_report_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / 'self-test.json'
            with patch.object(launcher, 'bundled_self_test', return_value={'status': 'passed'}), redirect_stdout(io.StringIO()):
                self.assertEqual(launcher.main(['--self-test', '--report', str(report)]), 0)
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')), {'status': 'passed'})

    def test_ota_health_requires_ocr_then_http_before_marker(self):
        events = []
        opener = Mock()
        opener.open.side_effect = lambda *args, **kwargs: (events.append('http') or io.StringIO('{"status":"ok"}'))
        with patch.object(launcher, 'bundled_self_test', side_effect=lambda: (events.append('ocr') or {'status':'passed'})), \
             patch.object(launcher, 'build_opener', return_value=opener), \
             patch('updates.mark_update_healthy', side_effect=lambda path: events.append('marker')), redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.complete_startup_health('http://127.0.0.1:1234', Path('health.json'))['status'], 'ok')
        self.assertEqual(events, ['ocr', 'http', 'marker'])

    def test_ota_health_missing_model_never_writes_marker(self):
        with patch.object(launcher, 'bundled_self_test', side_effect=RuntimeError('missing model')), \
             patch.object(launcher, 'build_opener') as opener, \
             patch('updates.mark_update_healthy') as marker, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'missing model'):
                launcher.complete_startup_health('http://127.0.0.1:1234', Path('health.json'))
            opener.assert_not_called()
            marker.assert_not_called()

    def test_ota_health_bad_http_never_writes_marker(self):
        opener = Mock()
        opener.open.return_value = io.StringIO('{"status":"failed"}')
        with patch.object(launcher, 'bundled_self_test', return_value={'status':'passed'}), \
             patch.object(launcher, 'build_opener', return_value=opener), \
             patch('updates.mark_update_healthy') as marker, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'HTTP readiness'):
                launcher.complete_startup_health('http://127.0.0.1:1234', Path('health.json'))
            marker.assert_not_called()

    def test_ordinary_startup_does_not_run_ota_selftest(self):
        opener = Mock()
        opener.open.return_value = io.StringIO('{"status":"ok"}')
        with patch.object(launcher, 'bundled_self_test') as test, patch.object(launcher, 'build_opener', return_value=opener):
            launcher.complete_startup_health('http://127.0.0.1:1234')
            test.assert_not_called()

    def test_windows_file_version_from_single_version_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'version.txt'
            build_windows.write_version_resource(path, '2.3.4')
            source = path.read_text(encoding='utf-8')
            self.assertIn('filevers=(2, 3, 4, 0)', source)
            self.assertIn('VGA乱斗助手', source)
            compile(source, str(path), 'exec')

    def test_archive_inventory_rejects_ci_only_runtime_dependency(self):
        with self.assertRaisesRegex(RuntimeError, 'msvcp140.dll'):
            build_windows.assert_archive_inventory(['python312.dll'])

    def test_unused_tuio_input_plugin_is_excluded_and_rejected(self):
        source = (ROOT / 'packaging' / 'VGA-Aram-Helper.spec').read_text(encoding='utf-8')
        self.assertIn("'qtuiotouchplugin.dll'", source)
        with self.assertRaisesRegex(RuntimeError, 'TUIO network input'):
            build_windows.assert_archive_inventory(['PySide6/plugins/generic/qtuiotouchplugin.dll'])

    def test_spec_contains_onefile_and_actual_icon(self):
        source = (ROOT / 'packaging' / 'VGA-Aram-Helper.spec').read_text(encoding='utf-8')
        self.assertIn('a.binaries, a.datas', source)
        self.assertNotIn('COLLECT(', source)
        self.assertIn("'vga.ico'", source)
        self.assertTrue((ROOT / 'assets' / 'branding' / 'vga.ico').is_file())


if __name__ == '__main__':
    unittest.main()
