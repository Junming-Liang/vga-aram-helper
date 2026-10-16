"""Portable harness regressions; these tests are not actual Windows OTA proof."""
import importlib.util
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('windows_ota_smoke', ROOT / 'tests' / 'windows_ota_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
import updates


class WindowsOtaHarnessTests(unittest.TestCase):
    def test_control_title_is_exact_and_bound_to_known_release(self):
        import inspect
        self.assertEqual(smoke.CONTROL_TITLE, 'VGA乱斗助手 · 原生控制台')
        for version in ('0.3.0', '0.4.0', '0.4.1', '0.4.2', '0.4.3', '0.4.4', '0.4.5', '0.4.6'):
            self.assertEqual(smoke.control_title_for_version(version), smoke.CONTROL_TITLE)
        self.assertEqual(smoke.control_title_for_version('0.4.7'), 'VGA乱斗助手')
        self.assertEqual(smoke.control_title_for_version('0.4.8'), 'VGA乱斗助手')
        self.assertEqual(smoke.control_title_for_version('0.4.9'), 'VGA乱斗助手')
        self.assertEqual(inspect.signature(smoke.NativeJob.windows).parameters['title'].default, smoke.CONTROL_TITLE)
        self.assertEqual(inspect.signature(smoke.NativeJob.close_application).parameters['title'].default, smoke.CONTROL_TITLE)

    def test_control_title_rejects_unknown_and_noncanonical_versions(self):
        for version in ('', '0.3', 'v0.4.7', '0.4.07', '0.4.7-rc1', '0.4.10', '99.0.0', None, True):
            with self.subTest(version=version), self.assertRaises(AssertionError):
                smoke.control_title_for_version(version)

    def test_graceful_close_keeps_selected_exact_title_and_uniqueness(self):
        native = smoke.NativeJob.__new__(smoke.NativeJob)
        window = {'hwnd': 101, 'pid': 202}
        native.windows = Mock(return_value=[window])
        native.close_window = Mock()
        native.image_pids = Mock(return_value=set())
        native.close_application('owned.exe', time.monotonic() + 1, title=smoke.LIGHT_CONTROL_TITLE)
        native.windows.assert_called_once_with('owned.exe', smoke.LIGHT_CONTROL_TITLE)
        native.close_window.assert_called_once_with(window)
        native.image_pids.assert_called_once_with('owned.exe')
        for windows in ([], [window, dict(hwnd=102, pid=202)]):
            native.windows = Mock(return_value=windows)
            native.close_window.reset_mock()
            with self.assertRaisesRegex(AssertionError, 'exactly one'):
                native.close_application('owned.exe', time.monotonic() + 1, title=smoke.LIGHT_CONTROL_TITLE)
            native.close_window.assert_not_called()

    def test_pinned_release_identity(self):
        self.assertEqual(smoke.EXPECTED_SHA256, '40b8d2af8309278b9cf6a5eace8ca26d6a483f659578d441636b86369d66cf6e')
        self.assertEqual(smoke.EXPECTED_SIZE, 150155259)

    def test_mismatch_version_is_valid_and_different(self):
        for version in ('0.3.0', '0.3', '99999.99999.99999', '01.02.00001'):
            changed = smoke.different_version(version)
            self.assertNotEqual(updates._version(changed), updates._version(version))

    def test_malformed_versions_are_rejected(self):
        for version in ('', 'v0.3.0', '0.3.0.1', '0.3.0-rc1', '0..1', '100000.0.0', '０.３.０', '-1.0.0'):
            with self.subTest(version=version), self.assertRaises(AssertionError):
                smoke.different_version(version)

    def test_plan_uses_exact_local_copies_and_real_parent_pid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()  # Match production canonicalization of Windows 8.3 TEMP aliases.
            exe = root / 'VGA-Aram-Helper.exe'
            exe.write_bytes(b'MZlocal unchanged fake fixture; never executed')
            digest = smoke.sha256(exe)
            path, value = smoke.prepare_fixture_plan(exe, root / 'state', 'first', os.getpid(), '0.3.0', digest)
            parsed, job, target = updates._read_plan(path)
            self.assertEqual(parsed, value)
            self.assertEqual(target, exe)
            self.assertEqual(value['parent_pid'], os.getpid())
            self.assertEqual(value['original_sha256'], digest)
            self.assertEqual(value['manifest']['sha256'], digest)
            self.assertEqual((job / 'updater.exe').read_bytes(), exe.read_bytes())
            self.assertEqual((job / 'candidate.bin').read_bytes(), exe.read_bytes())
            self.assertFalse((job / 'health.json').exists())
            self.assertFalse((job / 'result.json').exists())

    def test_mismatch_changes_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'VGA-Aram-Helper.exe'
            exe.write_bytes(b'MZlocal fixture, not an executable')
            digest = smoke.sha256(exe)
            first, a = smoke.prepare_fixture_plan(exe, root / 'state', 'a', 1234, '0.3.0', digest)
            second, b = smoke.prepare_fixture_plan(exe, root / 'state', 'b', 1234, '0.3.1', digest)
            self.assertNotEqual(a['manifest']['version'], b['manifest']['version'])
            self.assertNotEqual(a['health_token'], b['health_token'])
            self.assertEqual(len(a['health_token']), 48)
            self.assertEqual(a['manifest']['sha256'], b['manifest']['sha256'])
            self.assertEqual((first.parent / 'candidate.bin').read_bytes(), (second.parent / 'candidate.bin').read_bytes())

    def test_fixture_copy_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / 'VGA-Aram-Helper.exe'
            exe.write_bytes(b'fixture')
            with self.assertRaisesRegex(AssertionError, 'differs'):
                smoke.prepare_fixture_plan(exe, root / 'state', 'first', 1234, '0.3.0', '0' * 64)

    def test_native_ready_contract_rejects_fakes(self):
        valid = {'applicationVersion': '0.3.0', 'frozen': True, 'mode': 'native-overlay', 'pid': 1234}
        smoke.validate_old_ready(valid, '0.3.0')
        for field, value in (('frozen', False), ('mode', 'http'), ('pid', True), ('pid', 0), ('applicationVersion', '0.2.0')):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                smoke.validate_old_ready(dict(valid, **{field: value}), '0.3.0')

    def test_child_environment_is_isolated_and_proxy_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            original = {'SystemRoot': r'C:\Windows', 'Path': r'C:\Python312', 'PYTHONPATH': 'secret-source',
                        'QT_QPA_PLATFORM': 'offscreen', 'Qt_Plugin_Path': 'outside', '_PYI_ARCHIVE_FILE': 'outside'}
            env = smoke.child_environment(original, Path(directory), 'http://127.0.0.1:12345')
            self.assertEqual(original['QT_QPA_PLATFORM'], 'offscreen')
            self.assertEqual(env['PATH'], r'C:\Windows\System32;C:\Windows')
            self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:12345')
            self.assertEqual(env['NO_PROXY'], '127.0.0.1,localhost')
            self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
            self.assertNotIn('PYTHONPATH', env)
            self.assertNotIn('QT_QPA_PLATFORM', env)
            self.assertNotIn('QT_PLUGIN_PATH', env)
            self.assertNotIn('_PYI_ARCHIVE_FILE', env)
            self.assertTrue(Path(env['TMP']).is_dir())

    def test_bounded_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'report.json'
            value = {'status': 'passed', 'message': '原生窗口'}
            smoke.write_json(path, value)
            self.assertEqual(smoke.read_json(path), value)
            with self.assertRaises(AssertionError):
                smoke.read_json(path, limit=1)
            with self.assertRaises(AssertionError):
                smoke.write_json(path, {'oversized': 'x' * smoke.MAX_JSON})

    def test_local_proxy_rejects_without_forwarding(self):
        from urllib.parse import urlsplit
        with smoke.rejecting_proxy() as (url, counts):
            parsed = urlsplit(url)
            for method, target in (('CONNECT', 'must-never-resolve.invalid:443'), ('GET', 'http://must-never-resolve.invalid/')):
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
                try:
                    connection.request(method, target)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 403)
                    self.assertEqual(response.read(), b'')
                finally:
                    connection.close()
            self.assertEqual(counts['rejected_requests'], 2)

    def test_observer_records_actual_replace_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'target'
            replacement = Path(directory) / 'replacement'
            path.write_bytes(b'same')
            replacement.write_bytes(b'same')
            observer = smoke.TargetObserver(path)
            observer.thread.start()
            try:
                smoke.Deadline.wait(lambda: observer.samples >= 1, time.monotonic() + 2, 'observer did not start')
                replacement.replace(path)
                smoke.Deadline.wait(lambda: len(observer.identities) == 2, time.monotonic() + 2, 'replacement not observed')
            finally:
                result = observer.finish()
            self.assertEqual(result['missing_or_unreadable_samples'], 0)
            self.assertEqual([size for _, size in result['identities_and_sizes']], [4, 4])
            self.assertNotEqual(result['identities_and_sizes'][0][0], result['identities_and_sizes'][1][0])

    def test_observer_missing_target_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = smoke.TargetObserver(Path(directory) / 'missing')
            observer.thread.start()
            observer.thread.join(timeout=2)
            with self.assertRaisesRegex(AssertionError, 'continuity'):
                observer.finish()

    def test_deadline_never_exceeds_suite_limit(self):
        deadline = smoke.Deadline(1)
        self.assertLessEqual(deadline.until(100), deadline.end)
        self.assertLessEqual(deadline.until(100, deadline.end - .5), deadline.end - .5)
        self.assertEqual(smoke.Deadline.wait(lambda: 'ready', deadline.end, 'not ready'), 'ready')
        with self.assertRaises(TimeoutError):
            smoke.Deadline.wait(lambda: False, time.monotonic() - 1, 'expired')

    def test_logs_are_bounded_and_copied_as_small_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs, reports = root / 'state' / 'logs', root / 'reports'
            logs.mkdir(parents=True)
            reports.mkdir()
            (logs / 'native-ready-error.txt').write_text('expected version mismatch', encoding='utf-8')
            self.assertEqual(smoke.collect_logs(root / 'state', reports, 'rollback'), ['windows-ota-rollback-native-ready-error.txt'])
            (logs / 'oversized.txt').write_bytes(b'x' * (smoke.MAX_JSON + 1))
            with self.assertRaisesRegex(AssertionError, '64 KiB'):
                smoke.collect_logs(root / 'state', reports, 'rollback')


if __name__ == '__main__':
    unittest.main()
