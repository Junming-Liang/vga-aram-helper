"""Portable fixture-image regressions; these do not claim Windows OS coverage."""
import ast
import gc
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_automatic_capture import (Events, MAX_SECONDS, assert_pixels,
    make_original_png, make_hidden_capture_observer, force_first_copy_blank,
    require_capture_idle, start_with_explicit_capture)
from windows_ota_smoke import Deadline
from windows_session_fixture import validate_png


class AutomaticCaptureFixtureTests(unittest.TestCase):
    def test_actual_occluder_and_game_dimensions_produce_valid_nonblank_pngs(self):
        for dimensions in ((64, 64), (964, 602)):
            with self.subTest(dimensions=dimensions), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'owned-original.png'
                expected = make_original_png(path, dimensions)
                self.assertEqual(validate_png(path), path.resolve())
                with Image.open(io.BytesIO(path.read_bytes())) as decoded:
                    self.assertEqual(decoded.format, 'PNG')
                    self.assertEqual(decoded.size, dimensions)
                    self.assertEqual(decoded.convert('RGB').tobytes(), expected.tobytes())
                self.assertEqual(assert_pixels(path.read_bytes(), expected), 0)
                colors = {color for _, color in expected.getcolors(dimensions[0] * dimensions[1])}
                self.assertTrue({(229, 67, 81), (41, 194, 148), (74, 108, 239),
                                 (251, 197, 49), (239, 53, 184)} <= colors)

    def test_normal_game_fixture_pixels_remain_exactly_unchanged(self):
        # The old geometry is valid at the normal game size. Keep those pixels
        # identical while fixing only the minimum-size occluder's invalid inset.
        width, height = 964, 602
        reference = Image.new('RGB', (width, height), (21, 39, 63))
        draw = ImageDraw.Draw(reference)
        colors = [(229, 67, 81), (41, 194, 148), (74, 108, 239), (251, 197, 49)]
        for row in range(4):
            for column in range(6):
                x, y = column * width // 6, row * height // 4
                draw.rectangle((x + 5, y + 5, (column + 1) * width // 6 - 6,
                                (row + 1) * height // 4 - 6), fill=colors[(row + column) % 4])
        draw.rectangle((width // 4, height // 4, width // 4 + 70, height // 4 + 70), fill=(239, 53, 184))
        with tempfile.TemporaryDirectory() as directory:
            actual = make_original_png(Path(directory) / 'owned-original.png', (width, height))
            self.assertEqual(actual.tobytes(), reference.tobytes())


class WorkerCaptureObserverTests(unittest.TestCase):
    def fixture(self):
        expected = Image.new('RGB', (64, 64), (229, 67, 81))
        stream = io.BytesIO(); expected.save(stream, format='PNG')
        result = (stream.getvalue(), object())
        capture = Mock(return_value=result)
        exists, visible = Mock(return_value=True), Mock(return_value=False)
        observed = []
        observer = make_hidden_capture_observer(capture, exists, visible, 123,
            expected, observed, threading.get_ident())
        return observer, capture, exists, visible, observed, result

    def call_worker(self, observer, *args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(observer, *args, **kwargs).result(timeout=3)

    def test_exact_cancellation_and_metadata_options_reach_real_capture(self):
        observer, capture, exists, visible, observed, result = self.fixture()
        target, roi, cancelled, metadata = object(), (0.,0.,1.,1.), threading.Event(), object()
        actual = self.call_worker(observer, target, roi, cancelled=cancelled, expected_metadata=metadata)
        self.assertIs(actual, result)
        capture.assert_called_once_with(target, roi, cancelled=cancelled, expected_metadata=metadata)
        exists.assert_called_once_with(123); visible.assert_called_once_with(123)
        self.assertEqual(observed, [True])

    def test_gui_thread_cannot_pass_the_worker_observation(self):
        observer, capture, *_ = self.fixture()
        with self.assertRaisesRegex(AssertionError, 'worker'):
            observer(object(), (0.,0.,1.,1.))
        capture.assert_not_called()

    def test_destroyed_or_visible_overlay_cannot_capture(self):
        for is_window, is_visible in ((False,False), (True,True)):
            observer, capture, exists, visible, observed, _ = self.fixture()
            exists.return_value = is_window; visible.return_value = is_visible
            with self.assertRaisesRegex(AssertionError, 'hidden overlay'):
                self.call_worker(observer, object(), (0.,0.,1.,1.))
            capture.assert_not_called(); self.assertFalse(observed)

    def test_capture_failures_propagate_without_success_evidence(self):
        observer, capture, _, _, observed, _ = self.fixture()
        capture.side_effect = RuntimeError('owned capture rejection')
        with self.assertRaisesRegex(RuntimeError, 'owned capture rejection'):
            self.call_worker(observer, object(), (0.,0.,1.,1.))
        self.assertFalse(observed)


    def test_wrong_pixels_still_fail(self):
        observer, capture, _, _, observed, _ = self.fixture()
        stream = io.BytesIO(); Image.new('RGB', (64,64), 'black').save(stream,format='PNG')
        capture.return_value = (stream.getvalue(), object())
        with self.assertRaisesRegex(AssertionError, 'did not match'):
            self.call_worker(observer, object(), (0.,0.,1.,1.))
        self.assertFalse(observed)


class LegacyGdiFixtureIsolationTests(unittest.TestCase):
    def fixture(self):
        events=[]
        class Capture:
            _persistent=object();_wgc=object();cleanup_pending=False
            def retire_session(self):events.append('retire')
            def _copy_pixels(self,*args):
                events.append('actual-copy');return Image.new('RGB',(64,64),'white')
        return Capture(),events

    def test_retirement_precedes_explicit_legacy_backend_and_restores_it(self):
        capture,events=self.fixture();persistent,one_shot=capture._persistent,capture._wgc
        with force_first_copy_blank(capture) as calls:
            self.assertEqual(events,['retire'])
            self.assertIsNone(capture._persistent);self.assertIsNone(capture._wgc)
            self.assertEqual(capture._copy_pixels(1,64,64,0,0).getpixel((0,0)),(0,0,0))
            self.assertEqual(capture._copy_pixels(1,64,64,0,0).getpixel((0,0)),(255,255,255))
            self.assertEqual(len(calls),2)
        self.assertIs(capture._persistent,persistent);self.assertIs(capture._wgc,one_shot)
        self.assertEqual(events,['retire','actual-copy'])

    def test_pending_session_cannot_be_bypassed_to_force_gdi(self):
        capture,events=self.fixture();capture.cleanup_pending=True;persistent=capture._persistent
        with patch('windows_automatic_capture.time.monotonic',side_effect=[0,4]):
            with self.assertRaisesRegex(RuntimeError,'cleanup'):
                with force_first_copy_blank(capture):self.fail('Unclosed session entered GDI fixture')
        self.assertIs(capture._persistent,persistent);self.assertEqual(events,['retire'])


class ControlledCaptureIdleTests(unittest.TestCase):
    def test_pending_timer_capture_inference_or_worker_is_never_disguised_as_idle(self):
        for field in ('timer', 'capture_pending', 'ocr_busy', 'vga-ocr', 'vga-selection'):
            with self.subTest(field=field):
                control = SimpleNamespace(monitor=Mock(isActive=lambda: field == 'timer'),
                    capture_pending=field == 'capture_pending', ocr_busy=field == 'ocr_busy',
                    _workers=[SimpleNamespace(name=field)] if field.startswith('vga-') else [])
                before = (control.capture_pending, control.ocr_busy, list(control._workers))
                with self.assertRaisesRegex(AssertionError, 'idle capture pipeline'):
                    require_capture_idle(control)
                self.assertEqual((control.capture_pending, control.ocr_busy, control._workers), before)
                control.monitor.stop.assert_not_called()

    def test_windows_fixture_uses_controlled_start_both_times_and_checks_before_seeding(self):
        source = Path(__file__).with_name('windows_automatic_capture.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        execute = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'execute')
        starts = [node for node in ast.walk(execute) if isinstance(node, ast.Call) and
                  isinstance(node.func, ast.Name) and node.func.id == 'start_with_explicit_capture']
        self.assertEqual(len(starts), 2)
        self.assertNotIn('control.start_button.click()', ast.get_source_segment(source, execute))
        seed = next(node for node in ast.walk(execute) if isinstance(node, ast.FunctionDef) and node.name == 'seed_stale_state')
        self.assertEqual(ast.unparse(seed.body[0]), 'require_capture_idle(control)')


os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class ControlledCaptureCadenceQtTests(unittest.TestCase):
    """Real Qt timers, Start, discovery, worker and completion; owned OS/OCR fakes."""
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        from automatic_windows import AutomaticWindowPolicy
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable, ClientRect, WindowInfo
        from session_windows import ProcessMetadata
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.events = Events(self.app, Deadline(20))
        self.game = WindowInfo(123, 456, 'Owned Qt fixture', 'RiotWindowClass')
        self.metadata = ProcessMetadata(r'C:\owned\League of Legends\Game\League of Legends.exe', 123456)
        self.available = []
        self.discovery_threads, self.capture_calls, self.inference_calls = [], [], []
        self.watchdog_ticks, self.monitor_ticks = [], []
        self.capture_entered, self.capture_release = threading.Event(), threading.Event()
        self.capture_release.set()
        self.capture_error = None
        self.overlay_visible = threading.Event()
        self.main_thread = threading.get_ident()
        self.rect = ClientRect(0, 0, 964, 602)
        png = Path(self.directory.name) / 'owned.png'
        self.expected = make_original_png(png, (self.rect.width, self.rect.height))
        self.encoded = png.read_bytes()

        def windows():
            self.discovery_threads.append(threading.get_ident())
            return list(self.available)

        def capture(target, roi, **options):
            self.capture_calls.append((threading.get_ident(), target, roi, options))
            self.capture_entered.set()
            if not self.capture_release.wait(3):
                raise RuntimeError('Owned Qt capture release timed out')
            if self.capture_error:
                raise self.capture_error
            return self.encoded, self.rect

        self.hidden_captures = []
        observer = make_hidden_capture_observer(capture, lambda hwnd: True,
            lambda hwnd: self.overlay_visible.is_set(), 123, self.expected,
            self.hidden_captures, self.main_thread)
        self.capture = SimpleNamespace(windows=windows, rect=lambda target: self.rect,
            foreground=lambda target: True, capture=observer)
        policy = patch('automatic_windows.AutomaticWindowPolicy', side_effect=lambda **kwargs:
            AutomaticWindowPolicy(resolver=lambda pid: self.metadata, verifier=lambda path: True, **kwargs))
        policy.start(); self.addCleanup(policy.stop)

        def recognize(image, *args, **kwargs):
            self.inference_calls.append(threading.get_ident())
            assert_pixels(image, self.expected)
            return {'candidates': [], 'automatic_candidates': []}

        recognition = patch('hero_recognition.recognize_frame', side_effect=recognize)
        recognition.start(); self.addCleanup(recognition.stop)
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('Owned portable fixture')):
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='fixture-test', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose)
        self.window.capture = self.capture
        self.window.ocr = object()  # Recognition is synthetic; the serialized worker is real.
        self.window.refresh_windows()
        visible = self.overlay_visible

        class VisibilityObserver(QtCore.QObject):
            def eventFilter(self, watched, event):
                if event.type() == QtCore.QEvent.Type.Show:
                    visible.set()
                elif event.type() == QtCore.QEvent.Type.Hide:
                    visible.clear()
                return False

        self.visibility_observer = VisibilityObserver(self.window)
        self.window.overlay.installEventFilter(self.visibility_observer)
        self.window.watchdog.timeout.connect(lambda: self.watchdog_ticks.append(True))
        self.window.monitor.timeout.connect(lambda: self.monitor_ticks.append(True))
        self.events.wait(lambda: self.window.start_button.isEnabled(), 'Qt fixture did not load')

    def dispose(self):
        self.capture_release.set()
        window, overlay = self.window, self.window.overlay
        window.close()
        self.events.wait(lambda: not window._workers, 'Owned Qt workers did not exit', 4)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(window)); self.assertFalse(isValid(overlay))
        self.window = None
        gc.collect(); self.app.processEvents()

    def wait_idle(self):
        self.events.wait(lambda: not self.window.ocr_busy and not self.window.capture_pending and
            not any(job.name in ('vga-ocr', 'vga-selection') for job in self.window._workers),
            'Owned capture did not complete')

    def seed(self):
        from native_state import display_cards
        w = self.window
        require_capture_idle(w)
        hero, names = next(iter(w.data['heroes'])), list(w.data['augments'])[:3]
        w.state.select_hero(hero); w.state.confirm(names, w.data['augments'])
        w.last_observation = time.monotonic()
        w.overlay.set_cards(hero, display_cards(w.data, hero, names), confirmation='Owned synthetic state')
        w.check_target()
        self.assertTrue(w.overlay.isVisible())

    def test_both_starts_keep_discovery_and_watchdog_but_only_explicit_capture_runs(self):
        w = self.window
        for index in range(2):
            with self.subTest(start=index):
                start_with_explicit_capture(w)
                self.assertTrue(w.state.running); self.assertTrue(w.isMinimized())
                self.assertTrue(w.watchdog.isActive())
                require_capture_idle(w)
                if index == 0:
                    self.events.wait(lambda: not w.discovery_busy, 'Initial discovery did not complete')
                    self.assertIsNone(w.target)
                    self.available.append(self.game)
                self.events.wait(lambda: w.target == self.game and not w.discovery_busy,
                                 'Unmodified watchdog/discovery did not bind owned game')
                self.seed()
                watchdog_before = len(self.watchdog_ticks)
                self.events.settle(.35)
                self.assertGreater(len(self.watchdog_ticks), watchdog_before)
                self.assertTrue(w.overlay.isVisible())
                self.assertEqual(len(self.capture_calls), index)
                self.assertEqual(self.monitor_ticks, [])
                self.capture_entered.clear(); self.capture_release.clear()
                w.capture_tick()
                self.assertFalse(w.overlay.isVisible()); self.assertTrue(w.capture_pending)
                with self.assertRaisesRegex(AssertionError, 'idle capture pipeline'):
                    require_capture_idle(w)
                self.events.wait(self.capture_entered.is_set, 'Explicit worker never started')
                self.assertTrue(w.ocr_busy); self.assertTrue(w.capture_pending)
                with self.assertRaisesRegex(AssertionError, 'idle capture pipeline'):
                    require_capture_idle(w)
                self.assertTrue(w.ocr_busy); self.assertTrue(w.capture_pending)
                self.capture_release.set()
                self.events.wait(lambda: len(self.inference_calls) == index + 1, 'Explicit inference never ran')
                self.wait_idle()
                require_capture_idle(w)
                self.assertEqual(len(self.hidden_captures), index + 1)
                self.events.settle(.35)  # Exceeds the production 200 ms completion cadence.
                self.assertEqual(len(self.capture_calls), index + 1)
                self.assertEqual(self.monitor_ticks, [])
                self.seed()
                w.stop_button.click()
                self.assertFalse(w.state.running); self.assertIsNone(w.automatic_policy)
                w.showNormal()
        self.assertTrue(any(thread != self.main_thread for thread in self.discovery_threads))
        self.assertTrue(all(call[0] != self.main_thread for call in self.capture_calls))
        self.assertTrue(all(thread != self.main_thread for thread in self.inference_calls))
        for _, target, roi, options in self.capture_calls:
            self.assertEqual(target, self.game); self.assertEqual(roi, (0., 0., 1., 1.))
            self.assertEqual(options['expected_metadata'].created, self.metadata.created)
            self.assertIsInstance(options['cancelled'], threading.Event)

    def test_error_completion_cannot_rearm_automatic_capture(self):
        self.available.append(self.game)
        w = self.window
        start_with_explicit_capture(w)
        self.events.wait(lambda: w.target == self.game, 'Owned game did not bind')
        self.capture_error = RuntimeError('Owned capture failure')
        w.capture_tick()
        self.events.wait(self.capture_entered.is_set, 'Explicit failed capture never ran')
        self.wait_idle()
        require_capture_idle(w)
        self.events.settle(1.1)  # Exceeds the production 1000 ms error retry.
        self.assertEqual(len(self.capture_calls), 1)
        self.assertFalse(self.inference_calls); self.assertFalse(self.monitor_ticks)
        self.assertTrue(w.watchdog.isActive())

    def test_original_long_interval_is_overridden_on_each_start_and_on_completion(self):
        w = self.window
        self.available.append(self.game)
        w.monitor.setInterval(MAX_SECONDS * 1000)
        for index in range(2):
            with self.subTest(start=index):
                w.start_button.click()  # Original fixture behavior, deliberately uncontrolled.
                self.assertTrue(w.monitor.isActive()); self.assertEqual(w.monitor.interval(), 0)
                with self.assertRaisesRegex(AssertionError, 'idle capture pipeline'):
                    require_capture_idle(w)
                self.events.wait(lambda: len(self.inference_calls) >= index + 1,
                                 'Original timer failed to launch unsolicited inference')
                self.wait_idle()
                self.assertTrue(w.monitor.isActive())
                self.assertLessEqual(w.monitor.interval(), 200)
                w.stop_button.click()
                w.showNormal()



if __name__ == '__main__':
    unittest.main()
