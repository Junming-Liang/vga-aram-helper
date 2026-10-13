"""Source-only automatic discovery/capture acceptance on an interactive Windows OS.

Run BEFORE freezing: python tests/windows_automatic_capture.py --reports reports
Only publisher trust for two freshly compiled, hash-checked owned executables is
injected. Discovery, HWND/PID/path/creation-time queries, Qt Start/minimization,
window recreation, z-order guards, and returned pixels use the real Windows OS.
The first HWND pixel copy is deliberately made blank to exercise the unmodified
bounded compositor fallback. It then must match an original generated PNG.

OCR's timer is slowed; stale-result payloads are explicitly synthetic. This test
proves neither real League signatures nor OCR/game/Vanguard compatibility. It
adds no production launch switch, trust bypass, or private screenshot resource.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from windows_exe_smoke import smoke_workspace
from windows_ota_smoke import Deadline, NativeJob, read_json, sha256, write_json
from windows_selection_smoke import (assert_owned_window, child_environment,
    declare_desktop, fixture_dimensions, foreground_owned)
from windows_session_fixture import CLASSES, compile_fixture, fixture_argv, validate_ready

MAX_SECONDS = 240
SOURCE_FILES = ('automatic_windows.py', 'native_ui.py', 'screen_capture.py', 'session_windows.py',
                'tests/windows_automatic_capture.py', 'tests/SessionWindowFixture.cs')
WM_RECREATE_OWNED = 0x8000 + 73
SCOPE = ('SOURCE fixture, not frozen-EXE acceptance. Real Windows HWND/process metadata, '
         'Qt lifecycle, z-order guards and bounded OS pixels. Publisher verification '
         'is injected only for exact freshly compiled owned fixture paths/hashes. '
         'First HWND copy is forced blank; compositor pixels are real. Stale OCR '
         'payloads/state are synthetic. No real League signature, real game, live-match '
         'accuracy or Vanguard compatibility claim. No private screenshots saved.')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Events:
    """Use real Qt signals/timers while keeping every wait within one deadline."""
    def __init__(self, app, budget):
        self.app, self.budget = app, budget

    def wait(self, predicate, description, seconds=12):
        end = self.budget.until(seconds)
        while time.monotonic() < end:
            self.app.processEvents()
            value = predicate()
            if value:
                return value
            time.sleep(.02)
        raise TimeoutError(description)

    def settle(self, seconds=.15):
        end = min(self.budget.end, time.monotonic() + seconds)
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        require(time.monotonic() < self.budget.end, 'Source fixture exhausted its deadline')


def make_original_png(path, size):
    """Only original colored geometry, no screenshots/photos/game assets."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', size, (21, 39, 63))
    draw = ImageDraw.Draw(image)
    width, height = size
    colors = [(229, 67, 81), (41, 194, 148), (74, 108, 239), (251, 197, 49)]
    for row in range(4):
        for column in range(6):
            x, y = column * width // 6, row * height // 4
            right, bottom = (column + 1) * width // 6, (row + 1) * height // 4
            # Keep the original 5px game-scene margins; tiny occluder cells
            # need smaller insets so every rectangle still has ordered bounds.
            pad_x, pad_y = min(5, (right - x) // 8), min(5, (bottom - y) // 8)
            draw.rectangle((x + pad_x, y + pad_y, right - pad_x - 1,
                            bottom - pad_y - 1), fill=colors[(row + column) % 4])
    draw.rectangle((width // 4, height // 4, width // 4 + 70, height // 4 + 70), fill=(239, 53, 184))
    image.save(path, format='PNG')
    return image


def assert_pixels(encoded, expected):
    from PIL import Image, ImageChops, ImageStat
    with Image.open(io.BytesIO(encoded)) as source:
        actual = source.convert('RGB')
    require(actual.size == expected.size, 'OS capture returned the wrong bounded pixel dimensions')
    error = max(ImageStat.Stat(ImageChops.difference(actual, expected)).mean)
    require(error <= 2.0, f'OS capture did not match the owned PNG (mean-channel error {error:.3f})')
    return round(error, 4)


@contextmanager
def force_first_copy_blank(capture):
    """Only blank the HWND attempt; second call must execute actual OS BitBlt."""
    from PIL import Image
    original = capture._copy_pixels
    calls = []

    def copy(source, width, height, left, top):
        calls.append({'width': width, 'height': height, 'left': left, 'top': top})
        if len(calls) == 1:
            return Image.new('RGB', (width, height), 'black')
        return original(source, width, height, left, top)

    with patch.object(capture, '_copy_pixels', side_effect=copy):
        yield calls


def assert_native_trust(fixture, work):
    """Exercise production WinVerifyTrust's native ABI without mocking it."""
    from automatic_windows import verify_authenticode_offline
    system = Path(os.environ.get('SystemRoot') or os.environ['SYSTEMROOT'])
    candidates = [system / 'System32/WindowsPowerShell/v1.0/powershell.exe',
                  fixture['compiler'], system / 'System32/WindowsPowerShell/v1.0/powershell_ise.exe']
    trusted = next((path for path in candidates if path.is_file() and verify_authenticode_offline(path)), None)
    require(trusted is not None, 'Offline WinVerifyTrust did not accept an installed Microsoft signed candidate')
    require(not verify_authenticode_offline(fixture['client_exe']),
            'Real WinVerifyTrust unexpectedly accepted the unsigned compiled fixture')
    original = trusted.read_bytes()
    require(len(original) <= 32 * 1024 * 1024 and original[:2] == b'MZ', 'Unexpected signed PE fixture')
    altered = bytearray(original)
    pe = struct.unpack_from('<I', original, 0x3c)[0]
    require(original[pe:pe + 4] == b'PE\0\0', 'Signed native fixture has no PE header')
    section_count = struct.unpack_from('<H', original, pe + 6)[0]
    optional_size = struct.unpack_from('<H', original, pe + 20)[0]
    table = pe + 24 + optional_size
    changed = None
    for index in range(section_count):
        at = table + index * 40
        require(at + 40 <= len(original), 'Truncated signed PE section table')
        size, offset = struct.unpack_from('<II', original, at + 16)
        flags = struct.unpack_from('<I', original, at + 36)[0]
        if flags & 0x20000000 and size >= 64 and offset + size <= len(original):
            changed = offset + 32
            altered[changed] ^= 1  # Change signed executable content, never checksum/certificate padding.
            break
    require(changed is not None, 'Signed native fixture has no bounded executable section')
    modified = work / 'modified-signed-never-executed.exe'
    modified.write_bytes(altered)
    require(not verify_authenticode_offline(modified), 'WinVerifyTrust accepted modified signed executable bytes')
    return {'signed_microsoft_file': trusted.name, 'signed_accepted': True,
            'unsigned_owned_fixture_rejected': True, 'modified_signed_copy_rejected': True,
            'modified_copy_executed': False, 'network_retrieval': False}


def execute(reports, result):
    require(os.name == 'nt', 'Requires an interactive Windows runner; Linux/offscreen is not OS evidence')
    require(not getattr(sys, 'frozen', False), 'Run this fixture from source before packaging')
    require(ctypes.sizeof(ctypes.c_void_p) == 8, 'Requires x64 Python on the Windows runner')
    budget = Deadline(MAX_SECONDS - 15)
    with smoke_workspace() as work:
        work = work.resolve()
        env = child_environment(os.environ, work)
        fixture = compile_fixture(work / 'fixture-root', timeout=min(45, max(.1, budget.end - time.monotonic())))
        result.update(fixture_source_sha256=fixture['source_sha256'],
                      fixture_executable_sha256=fixture['executable_sha256'])
        (reports / 'windows-automatic-compiler.log').write_text(fixture['compiler_log'], encoding='utf-8')
        result['native_authenticode'] = assert_native_trust(fixture, work)
        result['authenticode_abi_passed'] = True
        native, old_context, control, app = NativeJob(), None, None, None
        try:
            old_context = declare_desktop(native)
            # Do not inherit offscreen/minimal platform selection as successful Windows evidence.
            requested_platform = os.environ.get('QT_QPA_PLATFORM', 'windows').split(':', 1)[0]
            require(requested_platform == 'windows', 'QT_QPA_PLATFORM must use the actual Windows desktop')
            from PySide6 import QtWidgets
            from native_ui import ControlWindow
            from engine import load_data
            from screen_capture import CapturePaused, bounded_roi
            from session_windows import normalized_path, process_metadata
            import automatic_windows
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
            app.setQuitOnLastWindowClosed(False)
            require(app.platformName() == 'windows', 'Qt is not using its real Windows platform')
            result['qt_platform'] = app.platformName()
            events = Events(app, budget)
            area = W.RECT()
            require(native.u.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0), 'Cannot read work-area bounds')
            size = fixture_dimensions(area.right - area.left, area.bottom - area.top)['game']
            x, y = max(0, area.left) + 20, max(0, area.top) + 20
            png = work / 'owned-original.png'
            expected = make_original_png(png, size)
            occluder_png = work / 'owned-occluder.png'
            make_original_png(occluder_png, (64, 64))
            allowed = {normalized_path(str(fixture[role + '_exe'])) for role in ('client', 'game')}
            trust_calls = []
            real_policy = automatic_windows.AutomaticWindowPolicy

            def verifier(path):
                canonical = normalized_path(path)
                trust_calls.append(canonical)
                return canonical in allowed and sha256(path) == fixture['executable_sha256']

            def policy_factory(**kwargs):
                require('resolver' not in kwargs and 'verifier' not in kwargs, 'Unexpected discovery injection')
                return real_policy(verifier=verifier, **kwargs)

            sequence = 0
            owned = []

            def launch(role, *, executable=None, dimensions=size, position=(x, y), image=png):
                nonlocal sequence
                sequence += 1
                executable = executable or fixture[role + '_exe']
                ready = work / f'{role}-{sequence}-ready.json'
                argv = fixture_argv(executable, role, image, ready, x=position[0], y=position[1],
                                    width=dimensions[0], height=dimensions[1], lifetime=MAX_SECONDS)
                process = native.spawn(argv[0], argv[1:], env, work)
                item = {'process': process, 'exe': executable, 'role': role, 'ready': ready, 'size': dimensions}
                owned.append(item)

                def ready_window():
                    require(native.poll(process) is None, 'Owned fixture exited before readiness')
                    if not ready.is_file():
                        return None
                    value = read_json(ready)
                    window = validate_ready(value, role=role, pid=process['pid'],
                                            width=dimensions[0], height=dimensions[1])
                    assert_owned_window(native, process, executable, role, window, dimensions)
                    return window

                item['window'] = events.wait(ready_window, 'Owned fixture never painted its PNG')
                item['metadata'] = process_metadata(process['pid'])
                require(normalized_path(item['metadata'].path) == normalized_path(str(executable)), 'Wrong real executable path')
                require(item['metadata'].created > 0, 'Missing real process creation time')
                return item

            def foreground(item):
                events.wait(lambda: foreground_owned(native, item['process'], item['exe'], item['role'],
                                                      item['window'], item['size']),
                            'Owned fixture could not become foreground')
                events.settle()

            def close_owned(item):
                if native.poll(item['process']) is None:
                    assert_owned_window(native, item['process'], item['exe'], item['role'], item['window'], item['size'])
                    native.close_window(item['window'])
                    events.wait(lambda: native.poll(item['process']) is not None, 'Owned fixture did not close')
                    require(native.poll(item['process']) == 0, 'Owned fixture did not exit zero')

            def bound(item):
                def connected():
                    if not control.target or control.target.hwnd != item['window']['hwnd']:
                        return False
                    policy = control.automatic_policy
                    return (policy is not None and policy.bound is not None and
                            policy.bound.metadata.created == item['metadata'].created and control.target_allowed())
                events.wait(connected, 'Default AUTO did not connect the expected owned window')
                require(control.target.pid == item['process']['pid'], 'AUTO bound the wrong real PID')
                require(control.window_list.currentIndex() == 0 and control.window_list.currentData() is None,
                        'Automatic flow changed to a manually selected HWND')

            def capture_matches(*, fallback=False, roi=(0., 0., 1., 1.)):
                control.overlay.hide()
                events.settle(.1)
                target = control.target
                require(target is not None and control.target_allowed(), 'Capture requires a currently automatic-authorized target')
                if fallback:
                    with force_first_copy_blank(control.capture) as calls:
                        encoded, rect = control.capture.capture(target, roi)
                    require(len(calls) == 2, 'Blank HWND attempt did not make exactly one compositor copy')
                    left, top, width, height = bounded_roi(rect.width, rect.height, roi)
                    require(calls == [{'width': width, 'height': height, 'left': left, 'top': top},
                                      {'width': width, 'height': height, 'left': rect.x + left, 'top': rect.y + top}],
                            'Fallback allocated or copied beyond the authorized client ROI')
                    require(control.capture.last_backend == 'bounded-compositor', 'Real fallback backend was not used')
                else:
                    encoded, rect = control.capture.capture(target, roi)
                    left, top, width, height = bounded_roi(rect.width, rect.height, roi)
                error = assert_pixels(encoded, expected.crop((left, top, left + width, top + height)))
                return {'backend': control.capture.last_backend, 'client_size': [rect.width, rect.height],
                        'copied_size': [width, height], 'mean_channel_error': error}

            def seed_stale_state():
                # Synthetic state seed only: lifecycle must clear it; this is not OCR accuracy evidence.
                hero = next(iter(control.data['heroes']))
                names = list(control.data['augments'])[:3]
                control.state.select_hero(hero)
                control.state.confirm(names, control.data['augments'])
                control.last_observation = time.monotonic()
                from native_state import display_cards
                control.overlay.set_cards(hero, display_cards(control.data, hero, names), confirmation='Owned synthetic state')
                control.check_target()
                events.wait(lambda: control.overlay.isVisible(), 'Owned helper overlay did not become visible')
                return control.state.generation

            with patch.object(automatic_windows, 'AutomaticWindowPolicy', side_effect=policy_factory):
                control = ControlWindow(lambda: {'data': load_data(ROOT / 'fixtures/demo.json'),
                                        'status': {'state': 'demo', 'message': 'Owned fixture only'}},
                    state_dir=work / 'state', current_executable=Path(sys.executable),
                    current_version='source-fixture', frozen=False, enable_updates=False)
                # Keep production discovery/watchdog active; OCR is outside this OS mechanics test.
                control.monitor.setInterval(MAX_SECONDS * 1000)
                events.wait(lambda: control.start_button.isEnabled(), 'Source control did not load the owned demo data')
                require(control.capture is not None and control.window_list.currentIndex() == 0 and
                        control.window_list.currentData() is None and control.client_follow.isChecked() and
                        control.hero_auto.isChecked(), 'Normal default AUTO controls are not selected')
                control.start_button.click()
                events.wait(lambda: control.state.running and control.automatic_policy is not None and
                            control.isMinimized() and control.capture.u.IsIconic(int(control.winId())),
                            'Start did not minimize its real helper HWND and enable AUTO')
                events.wait(lambda: not control.discovery_busy and control.target is None,
                            'AUTO did not wait safely before the owned League-shaped windows existed')
                result['wait_without_window'] = True
                result['helper_minimized_after_start'] = True

                client = launch('client')
                bound(client)
                foreground(client)
                result['client_capture'] = capture_matches()
                game = launch('game')
                require(game['metadata'].created > control.automatic_policy.started_after,
                        'New-game fixture was not actually created after Start')
                bound(game)
                foreground(game)
                result['new_game_capture'] = capture_matches(fallback=True)
                result['bounded_roi_capture'] = capture_matches(fallback=True, roi=(.2, .2, .5, .5))
                result['wait_client_new_game'] = True
                result['hwnd_blank_fallback'] = True
                result['bounded_roi_passed'] = True

                # Observe the normal GUI capture path, not a replacement capture implementation.
                # One real local inference may run; its accuracy is outside this fixture's scope.
                seed_stale_state()
                captured = []
                real_capture = control.capture.capture

                def observe_hidden_capture(target, roi):
                    require(not control.overlay.isVisible() and
                            not control.capture.u.IsWindowVisible(int(control.overlay.winId())),
                            'GUI capture started while its own overlay HWND was visible')
                    value = real_capture(target, roi)
                    assert_pixels(value[0], expected)
                    captured.append(True)
                    return value

                with patch.object(control.capture, 'capture', side_effect=observe_hidden_capture), \
                     force_first_copy_blank(control.capture) as ui_calls:
                    control.capture_tick()
                    require(not control.overlay.isVisible(), 'capture_tick did not hide its own overlay immediately')
                    events.wait(lambda: bool(captured), 'Normal GUI capture did not produce owned pixels with overlay hidden', 30)
                    require(len(ui_calls) == 2, 'GUI capture did not exercise the real bounded fallback')
                events.wait(lambda: not control.ocr_busy and
                            not any(job.name == 'vga-ocr' for job in control._workers),
                            'Local inference did not release the GUI capture job', 35)
                result['self_overlay_hidden_before_capture'] = True

                seed_stale_state()
                native.u.ShowWindow(game['window']['hwnd'], 6)  # SW_MINIMIZE, owned window only.
                events.wait(lambda: control.capture.u.IsIconic(game['window']['hwnd']) and
                            not control.state.confirmed and not control.overlay.isVisible(),
                            'Minimize did not clear stale cards and hide the real overlay')
                require(control.state.running, 'Minimize stopped automatic monitoring instead of waiting')
                try:
                    control.capture.capture(control.target)
                except CapturePaused:
                    pass
                else:
                    raise AssertionError('Minimized target unexpectedly yielded pixels')
                native.u.ShowWindow(game['window']['hwnd'], 9)  # SW_RESTORE.
                foreground(game)
                bound(game)
                result['restored_capture'] = capture_matches(fallback=True)
                result['minimize_restore'] = True

                # Separate PID, unrelated executable basename, no policy/metadata/window-list mocks.
                foreign_exe = work / 'OwnedOccluder.exe'
                shutil.copyfile(fixture['client_exe'], foreign_exe)
                foreign = launch('client', executable=foreign_exe, dimensions=(64, 64), image=occluder_png,
                                 position=(x + size[0] // 4, y + size[1] // 4))
                require(foreign['process']['pid'] != os.getpid(), 'Occluder must belong to a foreign owned process')
                require(control.automatic_policy.inspect(control.capture.info(foreign['window']['hwnd'])) is None,
                        'Unrelated executable was recognized as League')
                foreground(game)
                require(control.capture.u.SetWindowPos(foreign['window']['hwnd'], W.HWND(-1), 0, 0, 0, 0,
                                                       0x0001 | 0x0002 | 0x0010 | 0x0040),
                        'Could not position the owned nonactivating topmost occluder')
                events.settle()
                require(control.capture.foreground(control.target), 'Foreign occluder unexpectedly changed foreground')
                control.capture.validate(control.target)  # The old nine-point check genuinely misses this overlap.
                with force_first_copy_blank(control.capture) as denied_calls:
                    try:
                        control.capture.capture(control.target)
                    except CapturePaused:
                        pass
                    else:
                        raise AssertionError('Tiny off-grid foreign overlap did not fail closed')
                require(not denied_calls, 'Occluded frame copied pixels before rejecting the foreign window')
                result['foreign_occlusion_failed_closed'] = True
                close_owned(foreign)
                foreground(game)
                result['unoccluded_capture'] = capture_matches(fallback=True)
                result['foreign_off_grid_occlusion'] = {'foreign_pid': foreign['process']['pid'],
                    'size': [64, 64], 'nine_point_check_passed': True, 'full_guard_rejected_before_copy': True}

                stale_generation = seed_stale_state()
                old_target = control.target
                old_policy = control.automatic_policy
                old_discovery = old_policy.discover(control.capture.windows())
                old_window = dict(game['window'])
                require(native.u.PostMessageW(old_window['hwnd'], WM_RECREATE_OWNED, 0, 0), 'Owned HWND recreation request failed')

                def recreated():
                    value = read_json(game['ready'])
                    if value['hwnd'] == old_window['hwnd']:
                        return None
                    replacement = validate_ready(value, role='game', pid=game['process']['pid'],
                        width=size[0], height=size[1])
                    assert_owned_window(native, game['process'], game['exe'], 'game', replacement, size)
                    return replacement

                game['window'] = events.wait(recreated, 'Same-process owned HWND was not recreated')
                require(process_metadata(game['process']['pid']) == game['metadata'],
                        'HWND recreation changed process identity instead of preserving the same PID/creation time')
                require(not control.capture.u.IsWindow(old_window['hwnd']), 'Recreated fixture left the old HWND alive')
                require(not old_policy.permits(old_target, windows=control.capture.windows()), 'Dead HWND remained permitted')
                require(not old_policy.adopt(old_discovery, windows=control.capture.windows()), 'Stale discovery adopted a dead HWND')
                bound(game)
                require(control.state.generation != stale_generation and not control.state.confirmed and
                        not control.state.offered and not control.state.hero and not control.overlay.isVisible(),
                        'Same-process HWND recreation retained stale hero/cards')
                control.task_result('ocr', {'candidates': [], '_windowIdentity': old_target.identity,
                    '_capturedAt': time.monotonic()}, stale_generation)
                require(not control.state.confirmed and not control.state.hero, 'Late old-HWND inference revived stale state')
                foreground(game)
                result['recreated_capture'] = capture_matches(fallback=True)
                result['same_process_recreation_cleared_stale'] = True
                result['same_process_hwnd_recreated'] = {'pid': game['process']['pid'],
                    'old_hwnd': old_window['hwnd'], 'new_hwnd': game['window']['hwnd'],
                    'creation_time_unchanged': True, 'stale_discovery_and_ocr_rejected': True}

                seed_stale_state()
                previous_metadata = game['metadata']
                previous_pid = game['process']['pid']
                close_owned(game)
                bound(client)
                require(not control.state.confirmed and not control.state.hero, 'Game exit retained stale game recognition')
                game = launch('game')
                require((game['process']['pid'], game['metadata'].created) != (previous_pid, previous_metadata.created),
                        'Restart fixture did not establish a new actual process lifetime')
                bound(game)
                foreground(game)
                result['restarted_capture'] = capture_matches(fallback=True)
                result['process_restart_auto_reconnected'] = True

                stopped_policy = control.automatic_policy
                stopped_scope = control.discovery_scope
                delayed = stopped_policy.discover(control.capture.windows())
                control.stop_button.click()
                require(not control.state.running and control.automatic_policy is None and not stopped_policy.active,
                        'Stop did not revoke the automatic policy')
                control.apply_discovery(delayed, stopped_scope)
                require(not control.state.running and control.automatic_policy is None,
                        'Late discovery after Stop restarted monitoring')
                # This game now really predates the next Start; no synthetic creation timestamps.
                control.showNormal()
                events.settle(.1)
                control.start_button.click()
                bound(game)
                require(game['metadata'].created < control.automatic_policy.started_after,
                        'Pre-existing-game case is not older than its new Start scope')
                require(control.isMinimized() and control.capture.u.IsIconic(int(control.winId())),
                        'Restarted Start did not minimize the helper again')
                foreground(game)
                result['preexisting_game_capture'] = capture_matches(fallback=True)
                result['preexisting_game_auto_connected'] = True
                require(control.window_list.currentIndex() == 0 and control.window_list.currentData() is None,
                        'A lifecycle case silently relied on manual HWND selection')
                result['no_manual_window_selection'] = True
                require(trust_calls and set(trust_calls) <= allowed, 'Unexpected fixture trust authorization')
                result['trust_injection'] = {'source_only': True, 'exact_paths_and_sha256_only': True,
                    'real_process_metadata_unchanged': True, 'calls': len(trust_calls)}
                control.stop_button.click()
                control.close()
                events.wait(lambda: not control._workers, 'Discovery worker remained after source control close')
                require(control.closed and not control.overlay.isVisible() and not control.hotkey_registered,
                        'Source UI cleanup retained overlay/hotkey resources')
                result['stop_close_cleanup'] = True
                for item in reversed(owned):
                    close_owned(item)
                events.wait(lambda: not native.pids(), 'Private fixture job still contained an owned process')
                result['owned_process_job_empty'] = True
        finally:
            try:
                if control is not None and not control.closed:
                    control.close()
                if app is not None:
                    app.processEvents()
            finally:
                try:
                    native.cleanup()
                finally:
                    if old_context:
                        require(native.u.SetThreadDpiAwarenessContext(old_context), 'Observer DPI context restoration failed')
        result['temporary_directory_removed'] = False
    result['temporary_directory_removed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    reports = args.reports.resolve()
    reports.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 1, 'status': 'failed', 'scope': SCOPE, 'backend': 'qtwidgets',
              'frozen': False, 'platform': sys.platform, 'checks_use_real_windows': os.name == 'nt'}
    started = time.monotonic()
    try:
        from app_version import __version__
        result['application_version'] = __version__
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                  text=True, timeout=10, check=True).stdout.strip()
        require(len(revision) == 40 and all(c in '0123456789abcdef' for c in revision), 'Invalid git source identity')
        result['source_commit'] = revision
        result['source_sha256'] = {name: sha256(ROOT / name) for name in SOURCE_FILES}
        execute(reports, result)
        require(result['source_sha256'] == {name: sha256(ROOT / name) for name in SOURCE_FILES},
                'Source files changed during Windows acceptance')
        result['status'] = 'passed'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)[:2400]
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    write_json(reports / 'windows-automatic-capture.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
