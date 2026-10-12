"""Real Windows client-to-new-game handoff using exclusively owned PNG windows.

Primary selection/carry uses actual OS pixels and process path/creation metadata.
Ambiguity/expiry cases in the application diagnostic are separate synthetic policy
checks. Neither is real game, Vanguard, or live-match compatibility evidence.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import isolated_windows_environment, smoke_workspace
from windows_ota_smoke import Deadline, NativeJob, read_json, sha256, write_json
sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_session_fixture import CLASSES, TITLES, compile_fixture, fixture_argv, validate_ready

CLIENT_PNG = ROOT / 'fixtures' / 'champselect-synthetic.png'
GAME_PNG = ROOT / 'fixtures' / 'auto-scene.png'
MAX_SECONDS = 240
JOB_CLEANUP_SECONDS = 15  # NativeJob.cleanup's existing bound, reserved inside MAX_SECONDS.
DIRECTORY_CLEANUP_SECONDS = 30  # smoke_workspace's existing post-job directory removal bound.
MAX_LOG_BYTES = 64 * 1024
MAX_TOTAL_LOG_BYTES = 256 * 1024
FIELDS = ('champion_select_own_row_passed', 'champion_select_ambiguity_passed',
          'champion_select_session_carry_passed', 'champion_select_stale_clear_passed',
          'champion_select_window_scope_passed', 'metadata_query_passed')
SCOPE = ('Owned original synthetic windows only. Primary client-to-new-game carry uses actual '
         'Windows pixels and real executable metadata; ambiguity/expiry are separate synthetic '
         'policy checks. No real game, Vanguard, live-match accuracy or compatibility claim.')


def child_environment(environ, work):
    env = isolated_windows_environment(environ, work)
    for key in tuple(env):
        if key.startswith(('_PYI_', 'QT_', 'PYSIDE_', 'VGA_')):
            env.pop(key)
    temporary = Path(work) / 'temporary'
    temporary.mkdir()
    env.update(TEMP=str(temporary), TMP=str(temporary), VGA_STATE_DIR=str(Path(work) / 'state'),
               PYINSTALLER_RESET_ENVIRONMENT='1')
    return env


def fixture_dimensions(work_width, work_height):
    """Both original scenes fit a 1024x768 runner without desktop settings edits."""
    if type(work_width) is not int or type(work_height) is not int:
        raise ValueError('Work-area dimensions must be integers')
    game_width = min(964, work_width - 60)
    game_height = min(602, work_height - 60)
    if game_height < 600 or game_width / game_height < 1.55:
        raise ValueError('Interactive desktop cannot fit the supported owned game fixture')
    return {'client': (game_width, game_height), 'game': (game_width, game_height)}


def declare_desktop(native):
    u = native.u
    declarations = {
        'GetClassNameW': ([W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
        'GetClientRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
        'GetForegroundWindow': ([], W.HWND),
        'SetForegroundWindow': ([W.HWND], W.BOOL),
        'ShowWindow': ([W.HWND, ctypes.c_int], W.BOOL),
        'SystemParametersInfoW': ([W.UINT, W.UINT, ctypes.c_void_p, W.UINT], W.BOOL),
        'SetThreadDpiAwarenessContext': ([ctypes.c_void_p], ctypes.c_void_p),
        'GetThreadDpiAwarenessContext': ([], ctypes.c_void_p),
        'AreDpiAwarenessContextsEqual': ([ctypes.c_void_p, ctypes.c_void_p], W.BOOL),
    }
    for name, (args, result) in declarations.items():
        function = getattr(u, name)
        function.argtypes, function.restype = args, result
    # This observer thread only; restore in finally. No system display setting is modified.
    old_context = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not old_context or not u.AreDpiAwarenessContextsEqual(u.GetThreadDpiAwarenessContext(), ctypes.c_void_p(-4)):
        raise RuntimeError('Owned-fixture observer thread could not establish PMv2 DPI awareness')
    return old_context


def assert_owned_window(native, process, executable, role, window, dimensions):
    if native.poll(process) is not None:
        raise AssertionError('Owned fixture exited before its requested close')
    windows = native.windows(executable, title=TITLES[role])
    if windows != [window] or window['pid'] != process['pid']:
        raise AssertionError('Fixture window/image/PID is not the exact owned process')
    cls = ctypes.create_unicode_buffer(256)
    if not native.u.GetClassNameW(window['hwnd'], cls, len(cls)) or cls.value != CLASSES[role]:
        raise AssertionError('Owned fixture Win32 class is not the expected class')
    rect = W.RECT()
    if not native.u.GetClientRect(window['hwnd'], ctypes.byref(rect)):
        raise AssertionError('Owned fixture client bounds are unavailable')
    if (rect.right - rect.left, rect.bottom - rect.top) != dimensions:
        raise AssertionError('Owned fixture client dimensions changed')


def foreground_owned(native, process, executable, role, window, dimensions):
    assert_owned_window(native, process, executable, role, window, dimensions)
    if int(native.u.GetForegroundWindow() or 0) != window['hwnd']:
        native.u.ShowWindow(window['hwnd'], 5)
        native.u.SetForegroundWindow(window['hwnd'])
    return int(native.u.GetForegroundWindow() or 0) == window['hwnd']


def wait_fixture(native, process, executable, role, ready_path, dimensions, budget):
    def ready():
        if native.poll(process) is not None:
            raise AssertionError('Owned fixture failed before readiness')
        if not ready_path.is_file():
            return None
        value = read_json(ready_path)
        window = validate_ready(value, role=role, pid=process['pid'], width=dimensions[0], height=dimensions[1])
        assert_owned_window(native, process, executable, role, window, dimensions)
        return window
    return Deadline.wait(ready, budget.until(20), 'Owned fixture readiness timed out')


def report_when(path, phase=None, *, terminal=False):
    if not path.is_file():
        return None
    try:
        value = read_json(path)
    except json.JSONDecodeError:
        return None  # The app may still be replacing/writing its bounded diagnostic report.
    if not isinstance(value, dict):
        raise AssertionError('Selection handoff report is not a JSON object')
    if value.get('status') == 'failed' or 'error' in value:
        raise AssertionError('Selection handoff failed: ' + str(value.get('error', 'unknown error'))[:1800])
    if terminal:
        return value if value.get('status') == 'passed' else None
    return value if value.get('phase') == phase else None


def validate_report(value, version):
    if not isinstance(value, dict) or value.get('status') != 'passed' or 'error' in value:
        raise AssertionError('Selection handoff did not pass')
    for name, expected in (('backend', 'qtwidgets'), ('qt_platform', 'windows'), ('applicationVersion', version)):
        if value.get(name) != expected:
            raise AssertionError('Selection handoff identity mismatch: ' + name)
    if value.get('frozen') is not True:
        raise AssertionError('Selection handoff is not from the actual frozen executable')
    for name in FIELDS:
        if value.get(name) is not True:
            raise AssertionError('Selection handoff evidence missing: ' + name)


def collect_logs(work, reports):
    sources = list(sorted((Path(work) / 'state' / 'logs').glob('*.txt')))
    sources += list(sorted(Path(work).glob('*.error.txt')))
    if len(sources) > 12:
        raise AssertionError('Selection log count exceeds its evidence bound')
    total, names = 0, []
    for path in sources:
        size = path.stat().st_size
        total += size
        if size > MAX_LOG_BYTES or total > MAX_TOTAL_LOG_BYTES:
            raise AssertionError('Selection logs exceed their small-evidence bound')
        target = Path(reports) / ('windows-selection-' + path.name)
        if target.name in names:
            raise AssertionError('Selection log names collide')
        shutil.copyfile(path, target)
        names.append(target.name)
    return names


def execute(original, reports, result):
    # Reserve existing NativeJob failure-cleanup time inside the 240-second bound.
    budget = Deadline(MAX_SECONDS - JOB_CLEANUP_SECONDS)
    with smoke_workspace() as work:
        work = work.resolve()  # Canonicalize Windows short-name TEMP aliases before identity checks.
        target = work / 'VGA-Aram-Helper.exe'
        shutil.copyfile(original, target)
        if sha256(target) != result['executable_sha256']:
            raise AssertionError('Target executable copy changed bytes')
        env = child_environment(os.environ, work)
        fixture = compile_fixture(work / 'fixture-root', timeout=max(.1, min(45, budget.end - time.monotonic())))
        result['fixture_source_sha256'] = fixture['source_sha256']
        (reports / 'windows-selection-compiler.log').write_text(fixture['compiler_log'], encoding='utf-8')
        native = NativeJob()
        old_context = None
        try:
            old_context = declare_desktop(native)
            work_area = W.RECT()
            if not native.u.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0):  # SPI_GETWORKAREA only
                raise RuntimeError('Interactive work-area bounds are unavailable')
            sizes = fixture_dimensions(work_area.right - work_area.left, work_area.bottom - work_area.top)
            x, y = max(0, work_area.left) + 20, max(0, work_area.top) + 20
            version_file = work / 'version.json'
            version_process = native.spawn(target, ['--version-file', str(version_file)], env, work)
            if native.wait_exit(version_process, budget.until(60)) != 0:
                raise AssertionError('Frozen executable version command failed')
            version_info = read_json(version_file)
            version = version_info.get('applicationVersion')
            if not isinstance(version, str) or not version or version_info.get('frozen') is not True:
                raise AssertionError('Frozen executable version evidence is invalid')
            result['applicationVersion'] = version
            client_ready = work / 'client-ready.json'
            argv = fixture_argv(fixture['client_exe'], 'client', CLIENT_PNG, client_ready,
                                x=x, y=y, width=sizes['client'][0], height=sizes['client'][1])
            client = native.spawn(argv[0], argv[1:], env, work)
            client_window = wait_fixture(native, client, fixture['client_exe'], 'client', client_ready, sizes['client'], budget)
            input_path = work / 'selection-input.json'
            write_json(input_path, {'schemaVersion': 1, 'scope': 'owned-synthetic-only', 'client': client_window})
            handoff_path = work / 'windows-selection-handoff.json'
            if handoff_path.exists():
                raise AssertionError('Selection handoff report must be fresh for this exact run')
            app = native.spawn(target, ['--selection-smoke-input', str(input_path),
                                        '--selection-smoke-report', str(handoff_path)], env, work)

            def awaiting_game():
                if native.poll(app) is not None:
                    raise AssertionError('Application exited before its real game-window request')
                value = report_when(handoff_path, 'await-game-window')
                if value:
                    return value
                foreground_owned(native, client, fixture['client_exe'], 'client', client_window, sizes['client'])
                return None

            Deadline.wait(awaiting_game, budget.until(95), 'Application did not confirm selection before game launch')
            result['game_launched_after_selection_request'] = True
            result['client'] = dict(client_window, class_name=CLASSES['client'], client_size=list(sizes['client']))
            # The real game fixture process does not exist until the app's explicit session has started.
            game_ready = work / 'game-ready.json'
            argv = fixture_argv(fixture['game_exe'], 'game', GAME_PNG, game_ready,
                                x=x, y=y, width=sizes['game'][0], height=sizes['game'][1])
            game = native.spawn(argv[0], argv[1:], env, work)
            game_window = wait_fixture(native, game, fixture['game_exe'], 'game', game_ready, sizes['game'], budget)
            result['game'] = dict(game_window, class_name=CLASSES['game'], client_size=list(sizes['game']))
            Deadline.wait(lambda: foreground_owned(native, game, fixture['game_exe'], 'game', game_window, sizes['game']),
                          budget.until(10), 'Owned new game fixture could not become foreground')

            def completed():
                value = report_when(handoff_path, terminal=True)
                if value:
                    return value
                if native.poll(app) is not None:
                    raise AssertionError('Application exited without a passed handoff report')
                return None

            handoff = Deadline.wait(completed, budget.until(90), 'Real selection handoff did not finish before its deadline')
            validate_report(handoff, version)
            if native.wait_exit(app, budget.until(20)) != 0:
                raise AssertionError('Selection diagnostic executable did not exit with code zero')
            result['process_exited'] = True
            for role, process, window in (('game', game, game_window), ('client', client, client_window)):
                assert_owned_window(native, process, fixture[role + '_exe'], role, window, sizes[role])
                native.close_window(window)
            for process in (game, client):
                if native.wait_exit(process, budget.until(10)) != 0:
                    raise AssertionError('Owned fixture did not exit cleanly after WM_CLOSE')
            Deadline.wait(lambda: not native.pids(), budget.until(10), 'Private selection job still contains owned processes')
            result.update(owned_processes_exited=True, native_report=handoff_path.name,
                          completed_fields=list(FIELDS), cleanup='Both fixtures exited 0 after WM_CLOSE; private job empty')
        finally:
            try:
                native.cleanup()  # A cleanup error propagates; status cannot become passed.
            finally:
                if old_context:
                    if not native.u.SetThreadDpiAwarenessContext(old_context):
                        raise RuntimeError('Observer thread DPI context restoration failed')
                # Read only the current run's unique temporary report; preserve it as small evidence.
                current_handoff = work / 'windows-selection-handoff.json'
                if current_handoff.is_file():
                    if current_handoff.stat().st_size > MAX_LOG_BYTES:
                        raise AssertionError('Selection handoff report exceeds 64 KiB')
                    shutil.copyfile(current_handoff, reports / current_handoff.name)
                result['logs'] = collect_logs(work, reports)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Selection smoke requires the real Windows executable and interactive Windows desktop')
    original, reports = args.exe.resolve(strict=True), args.report_dir.resolve()
    if original.suffix.lower() != '.exe':
        raise SystemExit('Selection smoke requires a Windows .exe')
    reports.mkdir(parents=True, exist_ok=True)
    result = {'status': 'failed', 'scope': SCOPE, 'executable_sha256': sha256(original),
              'process_exited': False, 'owned_processes_exited': False}
    try:
        execute(original, reports, result)
        result['status'] = 'passed'
    except Exception as error:
        result['error'] = repr(error)[:2000]
        raise
    finally:
        write_json(reports / 'windows-selection-smoke.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
