"""Fixture contracts plus Windows-only real readiness file-sharing regressions."""
import ast
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_session_fixture as fixture
import owned_diagnostic_json as polling
import windows_automatic_capture as automatic
import windows_ota_smoke as ota
import windows_selection_smoke as selection


def png_header(width=960, height=540):
    # Only a validator input; this is intentionally never displayed/executed.
    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', width, height) + b'\x00' * 9


def read_error(code=None, *, number=errno.EACCES):
    error = PermissionError(number, 'Synthetic owned readiness read denial')
    if code is not None:
        error.winerror = code
    return error


def ready_payload(**changes):
    return dict(dict(protocol=1, pid=101, hwnd=200, role='game',
                     class_name='RiotWindowClass', width=964, height=602,
                     paint_count=1, per_monitor_v2=True), **changes)


def source_tree(name):
    return ast.parse(Path(__file__).with_name(name).read_text(encoding='utf-8'))


def source_function(name, function):
    matches = [node for node in ast.walk(source_tree(name))
               if isinstance(node, ast.FunctionDef) and node.name == function]
    if len(matches) != 1:
        raise AssertionError('Expected one source function: ' + function)
    return matches[0]


def extracted_function(name, function, namespace):
    """Execute the real nested callback without launching any native fixture."""
    tree = ast.Module(body=[source_function(name, function)], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), name, 'exec'), namespace)
    return namespace[function]


@contextmanager
def windows_deny_read_handle(path):
    """Own a real handle allowing write/delete sharing, but denying reads."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x2 | 0x4, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    closed = False

    def release():
        nonlocal closed
        if not closed:
            if not kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            closed = True
    try:
        yield release
    finally:
        release()


class FixtureEntrypointImportTests(unittest.TestCase):
    def run_isolated(self, *arguments):
        # A fresh interpreter cannot inherit the unit runner's imported modules
        # or checkout path; the empty cwd cannot supply the shared root module.
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() != 'PYTHONPATH'}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(list(Path(directory).iterdir()), [])
            completed = subprocess.run(
                [sys.executable, '-I', '-B', *map(str, arguments)],
                cwd=directory, env=environment, capture_output=True,
                text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stderr, '')
        return completed.stdout

    def test_direct_fixture_import_bootstraps_exact_checkout_and_shared_poller(self):
        tests = Path(__file__).resolve().parent
        program = '''
from pathlib import Path
import os
import sys
tests = Path(sys.argv[1]).resolve()
root = tests.parent
assert 'PYTHONPATH' not in {key.upper() for key in os.environ}
assert not list(Path.cwd().iterdir())
assert root not in [Path(entry).resolve() for entry in sys.path]
assert 'windows_session_fixture' not in sys.modules
assert 'owned_diagnostic_json' not in sys.modules
sys.path.insert(0, str(tests))
import windows_session_fixture as fixture
import owned_diagnostic_json as polling
assert fixture.ROOT == root
assert Path(fixture.__file__).resolve() == tests / 'windows_session_fixture.py'
assert Path(polling.__file__).resolve() == root / 'owned_diagnostic_json.py'
assert fixture.poll_owned_json is polling.poll_owned_json
assert fixture.poll_owned_json.__module__ == 'owned_diagnostic_json'
print('exact checkout import and shared poller identity verified')
'''
        self.assertEqual(self.run_isolated('-c', program, tests).strip(),
                         'exact checkout import and shared poller identity verified')

    def test_consumer_help_entrypoints_import_from_empty_cwd(self):
        # Each main parses --help before native work or report creation.
        for filename in ('windows_selection_smoke.py', 'windows_exe_smoke.py',
                         'windows_ota_smoke.py', 'windows_automatic_capture.py',
                         'windows_wgc_visible_overlay.py'):
            with self.subTest(filename=filename):
                output = self.run_isolated(Path(__file__).with_name(filename).resolve(), '--help')
                self.assertIn('usage:', output)
                self.assertIn(filename, output)
                self.assertIn('--help', output)


class OwnedJsonPollingTests(unittest.TestCase):
    def test_one_attempt_each_for_missing_denial_then_exact_success(self):
        path = Path('owned-ready.json')
        value = ready_payload(note='完整的就绪证据')
        reader = Mock(side_effect=[FileNotFoundError(errno.ENOENT, 'Not yet'), read_error(), value])
        with patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
            for index, expected in enumerate((None, None, value), 1):
                self.assertIs(fixture.poll_owned_json(path, reader), expected)
                self.assertEqual(reader.call_count, index)
        self.assertEqual(reader.call_args_list, [call(path)] * 3)

    def test_only_windows_allowlisted_denials_are_pending(self):
        for error in (read_error(5), read_error(32), read_error(33), read_error()):
            with self.subTest(winerror=getattr(error, 'winerror', None)):
                reader = Mock(side_effect=error)
                with patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
                    self.assertIsNone(fixture.poll_owned_json('owned', reader))
                reader.assert_called_once_with('owned')

    def test_windows_native_error_allowlist_requires_integer_codes(self):
        for code in (True, False, 5.0, 32.0, 33.0, '5', '32', '33'):
            with self.subTest(code=code):
                error = read_error(code)
                reader = Mock(side_effect=error)
                with patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
                    with self.assertRaises(PermissionError) as caught:
                        fixture.poll_owned_json('owned', reader)
                self.assertIs(caught.exception, error)
                reader.assert_called_once_with('owned')

    def test_a_previous_success_is_never_returned_during_later_denial(self):
        old, new = ready_payload(hwnd=199), ready_payload(hwnd=200)
        reader = Mock(side_effect=[old, read_error(32), FileNotFoundError(), new])
        with patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
            self.assertIs(fixture.poll_owned_json('owned', reader), old)
            self.assertIsNone(fixture.poll_owned_json('owned', reader))
            self.assertIsNone(fixture.poll_owned_json('owned', reader))
            self.assertIs(fixture.poll_owned_json('owned', reader), new)
        self.assertEqual(reader.call_count, 4)

    def test_posix_denials_and_unrelated_windows_errors_propagate_unchanged(self):
        for platform, errors in (
                ('linux', (read_error(), read_error(5), read_error(32), read_error(33))),
                ('win32', (read_error(2), read_error(87), read_error(number=errno.EPERM),
                           OSError(errno.EIO, 'I/O failure'), OSError(errno.ENOSPC, 'Disk full')))):
            for error in errors:
                with self.subTest(platform=platform, error=error, winerror=getattr(error, 'winerror', None)):
                    reader = Mock(side_effect=error)
                    with patch.object(polling, 'sys', SimpleNamespace(platform=platform)):
                        with self.assertRaises(OSError) as caught:
                            fixture.poll_owned_json('owned', reader)
                    self.assertIs(caught.exception, error)
                    reader.assert_called_once_with('owned')

    def test_real_reader_missing_malformed_oversized_and_nonobject_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ready.json'
            self.assertIsNone(fixture.poll_owned_json(path, ota.read_json))
            for payload, error in ((b'{"pid":', json.JSONDecodeError),
                                   (b'{"text":"' + b'x' * ota.MAX_JSON + b'"}', AssertionError),
                                   (b'[]', AssertionError), (b'null', AssertionError),
                                   (b'1', AssertionError), (b'"text"', AssertionError)):
                with self.subTest(payload=payload[:16]):
                    path.write_bytes(payload)
                    with self.assertRaises(error):
                        fixture.poll_owned_json(path, ota.read_json)
            path.write_text(json.dumps(ready_payload()), encoding='utf-8')
            self.assertEqual(fixture.poll_owned_json(path, ota.read_json), ready_payload())

    def test_no_nonobject_or_dict_subclass_is_accepted_as_ready(self):
        class DictSubclass(dict):
            pass
        for value in (None, False, [], 1, 'text', DictSubclass(ready_payload())):
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError, 'not an object'):
                fixture.poll_owned_json('owned', lambda path: value)

    def test_generic_final_artifact_reader_remains_strict_and_unwrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'final-report.json'
            with self.assertRaises(FileNotFoundError):
                ota.read_json(path)
            path.write_text('[]', encoding='utf-8')
            self.assertEqual(ota.read_json(path), [])  # Object policy belongs only to live polling.
            error = read_error(32)
            with patch.object(polling, 'sys', SimpleNamespace(platform='win32')), \
                 patch.object(Path, 'open', side_effect=error):
                with self.assertRaises(PermissionError) as caught:
                    ota.read_json(path)
            self.assertIs(caught.exception, error)
        self.assertNotIn('poll_owned_json', ast.unparse(source_function('windows_ota_smoke.py', 'read_json')))


class ReadinessConsumerTests(unittest.TestCase):
    def automatic_callback(self, name, reader):
        process = {'pid': 101}
        path, executable = Path('game-2-ready.json'), Path('owned-game.exe')
        native = SimpleNamespace(poll=Mock(return_value=None),
                                 u=SimpleNamespace(GetForegroundWindow=Mock(return_value=900)))
        namespace = dict(native=native, process=process, ready=path, executable=executable,
                         role='game', dimensions=(964, 602), size=(964, 602),
                         no_activate=False, foreground_before=900,
                         game={'process': process, 'ready': path, 'exe': executable},
                         old_window={'hwnd': 199, 'pid': 101}, require=automatic.require,
                         poll_owned_json=Mock(wraps=fixture.poll_owned_json), read_json=reader,
                         validate_ready=Mock(wraps=fixture.validate_ready), assert_owned_window=Mock())
        return extracted_function('windows_automatic_capture.py', name, namespace), namespace

    def test_initial_and_recreated_callbacks_pending_then_validate_exact_new_window(self):
        for name in ('ready_window', 'recreated'):
            with self.subTest(callback=name):
                value = ready_payload()
                reader = Mock(side_effect=[FileNotFoundError(), read_error(), value])
                predicate, namespace = self.automatic_callback(name, reader)
                with patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
                    self.assertIsNone(predicate())
                    self.assertIsNone(predicate())
                    namespace['validate_ready'].assert_not_called()
                    namespace['assert_owned_window'].assert_not_called()
                    self.assertEqual(predicate(), {'hwnd': 200, 'pid': 101})
                self.assertEqual(namespace['poll_owned_json'].call_args_list,
                                 [call(namespace['ready'], reader)] * 3)
                self.assertEqual(namespace['native'].poll.call_count, 3)
                namespace['validate_ready'].assert_called_once_with(value, role='game', pid=101, width=964, height=602)
                namespace['assert_owned_window'].assert_called_once_with(
                    namespace['native'], namespace['process'], namespace['executable'],
                    'game', {'hwnd': 200, 'pid': 101}, (964, 602))

    def test_actual_validator_still_rejects_wrong_pid_and_invalid_ready_payloads(self):
        for name in ('ready_window', 'recreated'):
            for changes in ({'pid': 102}, {'hwnd': True}, {'class_name': 'other'},
                            {'paint_count': 0}, {'per_monitor_v2': False}, {'width': 963}, {'height': 601}):
                with self.subTest(callback=name, changes=changes):
                    predicate, namespace = self.automatic_callback(name, Mock(return_value=ready_payload(**changes)))
                    with self.assertRaises(AssertionError):
                        predicate()
                    namespace['validate_ready'].assert_called_once()
                    namespace['assert_owned_window'].assert_not_called()

    def test_recreated_old_hwnd_remains_pending_and_new_hwnd_requires_native_ownership(self):
        predicate, namespace = self.automatic_callback('recreated', Mock(side_effect=[ready_payload(hwnd=199), ready_payload()]))
        self.assertIsNone(predicate())
        namespace['validate_ready'].assert_not_called()
        namespace['assert_owned_window'].assert_not_called()
        namespace['assert_owned_window'].side_effect = AssertionError('Wrong native ownership')
        with self.assertRaisesRegex(AssertionError, 'Wrong native ownership'):
            predicate()
        namespace['validate_ready'].assert_called_once()

    def test_initial_and_recreated_process_exit_fails_before_attempting_json_read(self):
        for name in ('ready_window', 'recreated'):
            with self.subTest(callback=name):
                reader = Mock(side_effect=read_error())
                predicate, namespace = self.automatic_callback(name, reader)
                namespace['native'].poll.return_value = 1
                with self.assertRaisesRegex(AssertionError, 'exited'):
                    predicate()
                reader.assert_not_called()
                namespace['poll_owned_json'].assert_not_called()

    def test_initial_nonactivating_foreground_guard_still_precedes_read(self):
        predicate, namespace = self.automatic_callback('ready_window', Mock(return_value=ready_payload()))
        namespace['no_activate'] = True
        namespace['native'].u.GetForegroundWindow.return_value = 901
        with self.assertRaisesRegex(AssertionError, 'changed foreground'):
            predicate()
        namespace['poll_owned_json'].assert_not_called()

    def test_permanent_denial_uses_one_existing_events_deadline_not_a_retry_budget(self):
        for name in ('ready_window', 'recreated'):
            for overall, seconds in ((.05, 12), (1, .05)):
                with self.subTest(callback=name, overall=overall, seconds=seconds):
                    now, sleeps = [100.], []
                    def sleep(interval):
                        sleeps.append(interval)
                        now[0] += interval
                    clock = SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
                    reader = Mock(side_effect=read_error())
                    predicate, namespace = self.automatic_callback(name, reader)
                    app = SimpleNamespace(processEvents=Mock())
                    with patch.object(automatic, 'time', clock), patch.object(ota, 'time', clock), \
                         patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
                        budget = ota.Deadline(overall)
                        original_end = budget.end
                        with patch.object(budget, 'until', wraps=budget.until) as until:
                            with self.assertRaisesRegex(TimeoutError, '^Original readiness timeout$'):
                                automatic.Events(app, budget).wait(predicate, 'Original readiness timeout', seconds=seconds)
                            until.assert_called_once_with(seconds)
                    self.assertEqual(budget.end, original_end)
                    self.assertEqual(sleeps, [.02] * 3)
                    self.assertAlmostEqual(now[0], 100.06)
                    self.assertEqual(reader.call_count, 3)
                    self.assertEqual(namespace['native'].poll.call_count, 3)
                    self.assertEqual(app.processEvents.call_count, 3)
                    namespace['validate_ready'].assert_not_called()

    def test_selection_live_reports_retry_denials_but_keep_phase_failure_and_object_checks(self):
        for value in ({'phase': 'await-game-window'}, {'status': 'passed'}):
            reader = Mock(side_effect=[read_error(32), value])
            with patch.object(selection, 'read_json', reader), \
                 patch.object(polling, 'sys', SimpleNamespace(platform='win32')):
                terminal = value.get('status') == 'passed'
                self.assertIsNone(selection.report_when('owned', 'await-game-window', terminal=terminal))
                self.assertIs(selection.report_when('owned', 'await-game-window', terminal=terminal), value)
        for value in ([], {'status': 'failed', 'error': 'original failure'}):
            with patch.object(selection, 'read_json', return_value=value), self.assertRaises(AssertionError):
                selection.report_when('owned', 'await-game-window')
        with patch.object(selection, 'read_json', return_value={'phase': 'other'}):
            self.assertIsNone(selection.report_when('owned', 'await-game-window'))

    def test_consumer_wiring_preserves_original_waits_liveness_and_validation(self):
        # Structural checks supplement executed callbacks; no GUI or download is needed.
        expected = {
            'windows_automatic_capture.py': (
                "events.wait(ready_window, 'Owned fixture never painted its PNG: ' + role)",
                "events.wait(recreated, 'Same-process owned HWND was not recreated')"),
            'windows_selection_smoke.py': (
                "Deadline.wait(ready, budget.until(20), 'Owned fixture readiness timed out')",
                "Deadline.wait(awaiting_game, budget.until(135), 'Application did not confirm selection before game launch')"),
            'windows_ota_smoke.py': (
                "Deadline.wait(old_ready, budget.until(60), 'Old native application readiness timed out')",
                'validate_old_ready(ready, version)'),
        }
        for filename, calls in expected.items():
            actual = {ast.unparse(node) for node in ast.walk(source_tree(filename)) if isinstance(node, ast.Call)}
            for expression in calls:
                with self.subTest(filename=filename, expression=expression):
                    self.assertIn(expression, actual)
        for filename, name, expression in (
                ('windows_selection_smoke.py', 'ready', 'poll_owned_json(ready_path, read_json)'),
                ('windows_selection_smoke.py', 'awaiting_game', 'poll_owned_json(handoff_path, read_json)'),
                ('windows_ota_smoke.py', 'old_ready', 'poll_owned_json(ready_path, read_json)')):
            node = source_function(filename, name)
            calls = [ast.unparse(item) for item in ast.walk(node) if isinstance(item, ast.Call)]
            self.assertIn(expression, calls)
            self.assertTrue(any(item.startswith('native.poll(') for item in calls))
            self.assertFalse(any(isinstance(item, (ast.For, ast.While)) for item in ast.walk(node)))
        selection_ready = ast.unparse(source_function('windows_selection_smoke.py', 'ready'))
        self.assertIn("validate_ready(value, role=role, pid=process['pid'], width=dimensions[0], height=dimensions[1])", selection_ready)
        self.assertIn('assert_owned_window(native, process, executable, role, window, dimensions)', selection_ready)
        exe = ast.unparse(source_tree('windows_exe_smoke.py'))
        self.assertIn('deadline = time.monotonic() + 90', exe)
        self.assertIn('while info is None:', exe)
        self.assertIn('assert process.poll() is None', exe)
        self.assertIn('if time.monotonic() > deadline:', exe)
        self.assertIn("poll_owned_json(ready, lambda path: json.loads(path.read_text(encoding='utf-8')))", exe)
        self.assertIn('time.sleep(0.25)', exe)
        self.assertIn("assert info['frozen'] is True", exe)
        wait = source_function('windows_automatic_capture.py', 'wait')
        self.assertEqual(ast.unparse(wait.args.defaults[0]), '12')


@unittest.skipUnless(os.name == 'nt', 'Requires actual Windows deny-read sharing semantics')
class WindowsOwnedJsonPollingTests(unittest.TestCase):
    def test_real_deny_read_handle_is_pending_then_exact_json_is_validated_after_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game-2-ready.json'
            value = ready_payload(note='原始完整证据')
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            path.write_bytes(raw)
            reader = Mock(wraps=ota.read_json)
            with windows_deny_read_handle(path) as release:
                with self.assertRaises(PermissionError):
                    ota.read_json(path)
                self.assertIsNone(fixture.poll_owned_json(path, reader))
                reader.assert_called_once_with(path)
                release()
                actual = fixture.poll_owned_json(path, reader)
                self.assertEqual(actual, value)
                self.assertEqual(fixture.validate_ready(actual, role='game', pid=101, width=964, height=602),
                                 {'hwnd': 200, 'pid': 101})
            self.assertEqual(path.read_bytes(), raw)

    def test_real_persistent_deny_read_times_out_with_existing_events_budget_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game-2-ready.json'
            path.write_text(json.dumps(ready_payload()), encoding='utf-8')
            reader = Mock(wraps=ota.read_json)
            app = SimpleNamespace(processEvents=Mock())
            with self.assertRaisesRegex(TimeoutError, '^Owned readiness remained denied$'):
                with windows_deny_read_handle(path):
                    budget = ota.Deadline(.08)
                    original_end = budget.end
                    started = time.monotonic()
                    try:
                        automatic.Events(app, budget).wait(
                            lambda: fixture.poll_owned_json(path, reader), 'Owned readiness remained denied')
                    finally:
                        self.assertGreater(reader.call_count, 0)
                        self.assertGreaterEqual(time.monotonic(), original_end)
                        self.assertLess(time.monotonic() - started, 2.)
                        self.assertEqual(budget.end, original_end)
                        with self.assertRaises(PermissionError):
                            ota.read_json(path)  # The lock stayed held until the deadline.
            # Exceptional timeout cleanup closed the handle and preserved the complete object.
            self.assertEqual(fixture.poll_owned_json(path, ota.read_json), ready_payload())
            path.unlink()


class SessionFixtureTests(unittest.TestCase):
    def system_files(self, root):
        framework = root / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319'
        framework.mkdir(parents=True)
        for name in ('csc.exe', 'mscorlib.dll', 'System.dll', 'System.Drawing.dll'):
            (framework / name).write_bytes(b'Offline placeholder, never executed')
        return framework

    def test_compiler_is_existing_framework64_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            framework = self.system_files(root)
            compiler, references = fixture.compiler_files(root)
            self.assertEqual(compiler, framework / 'csc.exe')
            self.assertEqual([p.name for p in references], ['mscorlib.dll', 'System.dll', 'System.Drawing.dll'])
            (framework / 'csc.exe').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'no installation'):
                fixture.compiler_files(root)

    def test_missing_reference_fails_instead_of_fetching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (self.system_files(root) / 'System.Drawing.dll').unlink()
            with self.assertRaisesRegex(FileNotFoundError, 'reference is missing'):
                fixture.compiler_files(root)

    def test_reference_fallback_stays_under_system_framework(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            framework = self.system_files(root)
            other = root / 'Microsoft.NET' / 'Framework' / 'v4.0.30319'
            other.mkdir(parents=True)
            (framework / 'System.Drawing.dll').replace(other / 'System.Drawing.dll')
            self.assertEqual(fixture.compiler_files(root)[1][-1], other / 'System.Drawing.dll')

    def test_compilation_command_and_copies_are_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.system_files(root / 'Windows')
            output_root = root / 'fixture-root'
            def simulated_compiler(command, **kwargs):
                self.assertIn('/platform:x64', command)
                self.assertIn('/target:winexe', command)
                self.assertIn('/noconfig', command)
                self.assertEqual(command[-1], str(fixture.SOURCE.resolve()))
                self.assertEqual(kwargs['timeout'], 45)
                output = next(value[5:] for value in command if value.startswith('/out:'))
                Path(output).write_bytes(b'MZoffline synthetic placeholder; never executed')
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            with patch.object(fixture, 'os', SimpleNamespace(name='nt', environ={'SystemRoot': str(root / 'Windows')})), \
                 patch.object(fixture.subprocess, 'run', side_effect=simulated_compiler):
                result = fixture.compile_fixture(output_root)
            self.assertEqual(result['client_exe'], output_root / 'LeagueClientUx.exe')
            self.assertEqual(result['game_exe'], output_root / 'Game' / 'League of Legends.exe')
            self.assertEqual(result['client_exe'].read_bytes(), result['game_exe'].read_bytes())
            self.assertEqual(result['source_sha256'], hashlib.sha256(fixture.SOURCE.read_bytes()).hexdigest())

    def test_compile_refuses_non_windows_without_running(self):
        with patch.object(fixture, 'os', SimpleNamespace(name='posix')), patch.object(fixture.subprocess, 'run') as run:
            with self.assertRaisesRegex(OSError, 'Windows'):
                fixture.compile_fixture('irrelevant')
            run.assert_not_called()

    def test_argv_is_unicode_safe_and_geometry_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            png = root / 'original 选英雄.png'; png.write_bytes(png_header())
            command = fixture.fixture_argv(root / 'LeagueClientUx.exe', 'client', png, root / 'ready.json', width=960, height=540)
            self.assertEqual(command[1:4], ['client', str(png.resolve()), str((root / 'ready.json').resolve())])
            self.assertEqual(command[4:], ['20', '20', '960', '540', '240'])
            for kwargs in ({'x': -1}, {'width': 1601}, {'height': 1001}, {'lifetime': 601}, {'width': True}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    fixture.fixture_argv(command[0], 'client', png, root / 'ready.json', **kwargs)

    def test_noactivate_is_explicit_test_only_and_preserves_default_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            png = root / 'original.png'; png.write_bytes(png_header())
            arguments = (root / 'OwnedOccluder.exe', 'client', png, root / 'ready.json')
            normal = fixture.fixture_argv(*arguments)
            self.assertEqual(len(normal), 9)  # EXE plus the unchanged eight fixture arguments.
            self.assertEqual(fixture.fixture_argv(*arguments, no_activate=False), normal)
            self.assertEqual(fixture.fixture_argv(*arguments, no_activate=True), normal + ['noactivate'])
            for invalid in (1, 0, 'yes', None):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'boolean'):
                    fixture.fixture_argv(*arguments, no_activate=invalid)

    def test_csharp_nonactivating_mode_skips_only_owned_activation(self):
        source = fixture.SOURCE.read_text()
        for expected in ('args.Length != 8 && args.Length != 9', 'args[8] != "noactivate"',
                         'noActivate = args.Length == 9;',
                         'uint exStyle = noActivate ? 0x08000080u : 0u;',
                         'ShowWindow(window, noActivate ? 4 : 5);',
                         'if (!noActivate) SetForegroundWindow(window);'):
            self.assertIn(expected, source)
        # The opt-in changes the owned test window, never OS foreground policy/input.
        for forbidden in ('AllowSetForegroundWindow', 'LockSetForegroundWindow', 'SendInput',
                          'AttachThreadInput', 'keybd_event', 'mouse_event'):
            self.assertNotIn(forbidden, source)

    def test_focus_sink_protocol_is_exact_and_separate_from_game_identity(self):
        self.assertEqual(fixture.WM_FOCUS_OWNED_SINK, 0x804A)
        self.assertEqual(fixture.WM_RETURN_OWNED_CLIENT, 0x804B)
        self.assertEqual(fixture.FOCUS_SINK_CLASS, 'VGAOwnedFocusSink')
        self.assertEqual(fixture.FOCUS_SINK_TITLE, 'VGA owned focus sink')
        self.assertEqual(fixture.FOCUS_SINK_BOUNDS, (0, 0, 160, 96))
        self.assertNotIn(fixture.FOCUS_SINK_CLASS, fixture.CLASSES.values())
        self.assertNotIn(fixture.FOCUS_SINK_TITLE, fixture.TITLES.values())
        source = fixture.SOURCE.read_text()
        for expected in ('WM_FOCUS_OWNED_SINK = 0x8000 + 74;',
                         'WM_RETURN_OWNED_CLIENT = 0x8000 + 75;',
                         'FocusSinkClass = "' + fixture.FOCUS_SINK_CLASS + '";',
                         'FocusSinkTitle = "' + fixture.FOCUS_SINK_TITLE + '";'):
            self.assertIn(expected, source)

    def test_focus_commands_require_exact_activating_client_and_no_parameters(self):
        source = fixture.SOURCE.read_text()
        opened = source.split('case WM_FOCUS_OWNED_SINK:', 1)[1].split('case WM_RETURN_OWNED_CLIENT:', 1)[0]
        returned = source.split('case WM_RETURN_OWNED_CLIENT:', 1)[1].split('case WM_TIMER:', 1)[0]
        for command in (opened, returned):
            self.assertIn('hwnd != window || role != "client" || noActivate ||', command)
            self.assertIn('wParam != UIntPtr.Zero || lParam != IntPtr.Zero', command)
            # Focus-only commands cannot mutate the original PNG client state.
            self.assertNotRegex(command, r'\bwindow\s*=(?!=)')
            for forbidden in ('DestroyWindow(window)', 'ShowWindow(window',
                              'ShowOwnedWindow(', 'CreateOwnedWindow(', 'Ready(',
                              'SetWindowPos', 'MoveWindow', 'bitmap', 'width =', 'height ='):
                self.assertNotIn(forbidden, command)
        self.assertIn('if (focusSink == IntPtr.Zero)', opened)
        self.assertEqual(opened.count('CreateWindowExW('), 1)
        self.assertIn('CreateWindowExW(0, FocusSinkClass, FocusSinkTitle, 0x00C80000u,', opened)
        self.assertIn('0, 0, 160, 96, IntPtr.Zero, IntPtr.Zero, GetModuleHandleW(null), IntPtr.Zero)', opened)
        self.assertIn('ShowWindow(focusSink, 5)', opened)
        self.assertIn('SetForegroundWindow(focusSink);', opened)
        self.assertIn('return focusSink;', opened)
        self.assertIn('focusSink == IntPtr.Zero) return IntPtr.Zero;', returned)
        self.assertLess(returned.index('SetForegroundWindow(window);'), returned.index('CloseOwnedFocusSink();'))
        self.assertIn('return window == hwnd && focusSink == IntPtr.Zero && GetForegroundWindow() == hwnd ? new IntPtr(1) : IntPtr.Zero;', returned)

    def test_focus_sink_dispatch_cannot_quit_or_paint_the_main_fixture(self):
        source = fixture.SOURCE.read_text()
        sink = source.split('private static IntPtr DispatchFocusSink(', 1)[1].split('private static void CloseOwnedFocusSink()', 1)[0]
        self.assertIn('if (message == WM_DESTROY)', sink)
        self.assertIn('if (hwnd == focusSink) focusSink = IntPtr.Zero;', sink)
        self.assertIn('return DefWindowProcW(hwnd, message, wParam, lParam);', sink)
        for forbidden in ('PostQuitMessage', 'RecordError(', 'bitmap', 'WM_TIMER', 'CreateOwnedWindow(',
                          'Ready(', 'SetForegroundWindow(', 'case WM_RECREATE_OWNED:'):
            self.assertNotIn(forbidden, sink)
        self.assertIn('if (role == "client" && !noActivate)', source)
        self.assertIn('wc.lpfnWndProc = FocusSinkProcedure; wc.lpszClassName = FocusSinkClass;', source)
        self.assertIn('wc.hbrBackground = new IntPtr(6);', source)

    def test_focus_sink_cleanup_covers_recreation_and_unconditional_finally(self):
        source = fixture.SOURCE.read_text()
        recreate = source.split('case WM_RECREATE_OWNED:', 1)[1].split('case WM_FOCUS_OWNED_SINK:', 1)[0]
        self.assertLess(recreate.index('CloseOwnedFocusSink();'), recreate.index('CreateOwnedWindow();'))
        close = source.split('private static void CloseOwnedFocusSink()', 1)[1].split('private static IntPtr CreateOwnedWindow()', 1)[0]
        self.assertIn('if (focusSink != IntPtr.Zero && !DestroyWindow(focusSink))', close)
        final = source.split('catch (Exception error) { RecordError(error); return 1; }', 1)[1]
        self.assertIn('finally', final)
        self.assertLess(final.index('DestroyWindow(focusSink)'), final.index('DestroyWindow(window)'))
        self.assertIn('GC.KeepAlive(FocusSinkProcedure);', final)

    def test_ready_path_must_be_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            png = root / 'original.png'; png.write_bytes(png_header())
            ready = root / 'ready.json'; ready.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'fresh'):
                fixture.fixture_argv(root / 'fixture.exe', 'client', png, ready)

    def test_png_guards_reject_wrong_type_and_unbounded_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory).resolve() / 'test.png'
            for content in (b'not a PNG' * 10, png_header(0, 540), png_header(5000, 540)):
                png.write_bytes(content)
                with self.assertRaises(ValueError):
                    fixture.validate_png(png)
            png.write_bytes(png_header())
            self.assertEqual(fixture.validate_png(png), png.resolve())

    def test_ready_requires_exact_pid_class_paint_and_dpi(self):
        valid = dict(protocol=1, pid=101, hwnd=200, role='game', class_name='RiotWindowClass',
                     width=964, height=602, paint_count=1, per_monitor_v2=True)
        self.assertEqual(fixture.validate_ready(valid, role='game', pid=101, width=964, height=602), {'hwnd': 200, 'pid': 101})
        for name, value in (('pid', 102), ('hwnd', True), ('class_name', 'other'), ('paint_count', 0),
                            ('per_monitor_v2', False), ('protocol', True), ('width', 963)):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                fixture.validate_ready(dict(valid, **{name: value}), role='game', pid=101, width=964, height=602)

    def test_csharp_declares_x64_unicode_abi_and_local_only_behavior(self):
        source = fixture.SOURCE.read_text()
        for expected in ('Marshal.SizeOf(typeof(WindowClass)) != 80', 'Marshal.SizeOf(typeof(Message)) != 48',
                         'Marshal.SizeOf(typeof(Paint)) != 72', 'ExactSpelling = true', 'RegisterClassExW',
                         'SetProcessDpiAwarenessContext(new IntPtr(-4))', 'AreDpiAwarenessContextsEqual',
                         'case WM_CLOSE:', 'DestroyWindow(hwnd)', 'GetCurrentProcessId()', 'GraphicsUnit.Pixel'):
            self.assertIn(expected, source)
        self.assertEqual(source.count('OpenProcess('), 2)  # declaration plus one literal limited-metadata call
        self.assertIn('OpenProcess(0x1000, false, pid)', source)
        for forbidden in ('ReadProcessMemory', 'WriteProcessMemory', 'SendInput', 'SetWindowsHookEx',
                          'AttachThreadInput', 'System.Net', 'HttpClient', 'Process.Start', 'Process.GetProcesses',
                          'Process.MainModule', 'PROCESS_VM_', 'SystemParametersInfo', 'ChangeDisplaySettings', 'WM_RELOAD'):
            self.assertNotIn(forbidden, source)
        self.assertEqual(source.count('CreateWindowExW(exStyle,'), 1)

    def test_owned_game_focus_command_pins_current_job_canonical_image_and_creation(self):
        source=fixture.SOURCE.read_text()
        self.assertEqual(fixture.WM_FOCUS_OWNED_GAME,0x804C)
        self.assertEqual(fixture.WM_FOCUS_OWNED_PAIR_CLIENT,0x804D)
        self.assertNotIn('created <= ownCreated',source)
        self.assertIn('FocusOwnedSibling(hwnd, wParam, lParam, false)',source)
        command=source.split('private static IntPtr FocusOwnedSibling(',1)[1].split('private static int Number(',1)[0]
        for required in ('IntPtr.Size != 8','role != (gameTarget ? "client" : "game")',
                'expectedCreated.ToInt64() <= 0','targetValue.ToUInt64() > Int64.MaxValue',
                'GetForegroundWindow() != window','GetAncestor(target, 2) != target',
                '!IsWindowVisible(target) || IsIconic(target)','cls.ToString() != (gameTarget ? "RiotWindowClass" : "RCLIENT")',
                '!SameOwnedJob(pid)','created != expectedCreated.ToInt64()',
                'repeatedPid != pid','String.Equals(actual, sibling, StringComparison.OrdinalIgnoreCase)',
                '"Game", "League of Legends.exe"', 'bool accepted = SetForegroundWindow(target)',
                '!accepted ? 2 : GetForegroundWindow() == target ? 1 : 3'):
            self.assertIn(required,command)
        self.assertEqual(command.count('SetForegroundWindow(target)'),1)
        self.assertLess(command.rindex('GetForegroundWindow() != window'),command.index('SetForegroundWindow(target)'))
        for required in ('QueryInformationJobObject(IntPtr.Zero, 3, information, bytes, out returned)',
                'count > 128 || assigned != count','return self && target;', 'Marshal.FreeHGlobal(information)',
                'CreateFileW(path, 0x80, 7, IntPtr.Zero, 3, 0, IntPtr.Zero)',
                'GetFinalPathNameByHandleW(handle, value, 32768, 0)', 'finally { CloseHandle(handle); }'):
            self.assertIn(required,source)
        self.assertNotIn('IsProcessInJob',source)


class ClientWindowClassContractTests(unittest.TestCase):
    def test_owned_windows_gate_exercises_documented_rclient_class(self):
        self.assertEqual(fixture.CLASSES,{'client':'RCLIENT','game':'RiotWindowClass'})
        source=fixture.SOURCE.read_text(encoding='utf-8')
        self.assertIn('className = role == "game" ? "RiotWindowClass" : "RCLIENT";',source)
        from automatic_windows import CLIENT_CLASSES
        self.assertIn(fixture.CLASSES['client'],CLIENT_CLASSES)


if __name__ == '__main__':
    unittest.main()
