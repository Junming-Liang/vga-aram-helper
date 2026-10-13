"""Portable fixture compiler/contract regressions; not Windows execution proof."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_session_fixture as fixture


def png_header(width=960, height=540):
    # Only a validator input; this is intentionally never displayed/executed.
    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', width, height) + b'\x00' * 9


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
        for forbidden in ('OpenProcess(', 'ReadProcessMemory', 'WriteProcessMemory', 'SendInput', 'SetWindowsHookEx',
                          'AttachThreadInput', 'System.Net', 'HttpClient', 'Process.Start', 'Process.GetProcesses',
                          'SystemParametersInfo', 'ChangeDisplaySettings', 'WM_RELOAD'):
            self.assertNotIn(forbidden, source)
        self.assertEqual(source.count('CreateWindowExW(exStyle,'), 1)


if __name__ == '__main__':
    unittest.main()
