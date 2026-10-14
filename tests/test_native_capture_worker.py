"""Qt thread/state integration with owned fakes; not Windows capture evidence."""
import copy
import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class NativeCaptureWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def wait(self, predicate, seconds=4):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Qt worker did not reach the expected state')

    def setUp(self):
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable, WindowInfo
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self._release_events = []
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('owned portable fixture')):
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='test', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose_window)
        self.wait(lambda: self.window.data is not None)
        self.window.watchdog.stop()
        self.window.monitor.stop()
        self.window.check_target = lambda: None
        self.window.target_allowed = lambda: True
        self.window.capture_metadata = lambda: None
        self.window.captured_frame_current = lambda value: True
        self.window.target = WindowInfo(123, 456, 'Owned mock', 'OwnedClass')
        self.window.state.start(self.window.target.identity)
        self.window.overlay.hide()
        self.main_thread = threading.get_ident()

    def dispose_window(self):
        # Qt's parentless widgets must be destroyed on their owning GUI thread,
        # not left in Python/Qt cycles for a later arbitrary GC pass. Release
        # only this fixture's waiting fakes even when an assertion failed.
        window = self.window
        if window is None:
            return
        for event in self._release_events:
            event.set()
        overlay = window.overlay
        window.capture = None
        window.close()
        self.wait(lambda: not window._workers, seconds=3)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(overlay))
        self.assertFalse(isValid(window))
        self.window = None
        gc.collect()
        self.app.processEvents()

    def test_slow_capture_is_off_gui_and_stop_discards_late_result(self):
        from screen_capture import ClientRect
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        threads = []
        class Capture:
            def capture(inner, *args, **kwargs):
                threads.append(threading.get_ident())
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('owned timeout')
                return b'owned-image', ClientRect(0, 0, 900, 600)
        self.window.capture = Capture()
        with patch('hero_recognition.recognize_frame', return_value={'automatic_candidates': [], 'candidates': []}):
            start = time.monotonic()
            self.window.capture_hidden(self.window.state.generation)
            self.assertLess(time.monotonic() - start, .25)
            self.wait(entered.is_set)
            self.assertNotEqual(threads[0], self.main_thread)
            self.window.stop_monitor()
            release.set()
            self.wait(lambda: not self.window.ocr_busy)
        self.assertFalse(self.window.state.running)
        self.assertFalse(self.window.state.confirmed)
        self.assertEqual(self.window.state.offered, ())

    def test_owned_cleanup_releases_waiting_fake_and_deletes_both_widgets(self):
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        def work():
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Owned cleanup fixture did not release worker')
        control, overlay = self.window, self.window.overlay
        control.spawn('owned-cleanup', work)
        self.wait(entered.is_set)
        self.dispose_window()
        self.assertTrue(release.is_set())
        self.assertFalse(control._workers)
        self.assertFalse(isValid(control))
        self.assertFalse(isValid(overlay))
        self.dispose_window()  # Registered cleanup remains safely idempotent.

    def test_two_independent_confirmations_before_reuse_and_fresh_capture_each_tick(self):
        from screen_capture import ClientRect
        names = list(self.window.data['augments'])[:3]
        hero = next(iter(self.window.data['heroes']))
        candidates = [{'name': name, 'recognized_text': name, 'match_method': 'exact',
                       'ocr_confidence': .99, 'box': [[x-40, 150], [x+40, 150],
                                                    [x+40, 180], [x-40, 180]]}
                      for x, name in zip((150, 450, 750), names)]
        capture_calls, infer_calls, hero_calls = [], [], []
        class Capture:
            def capture(inner, *args, **kwargs):
                capture_calls.append(time.monotonic())
                return b'owned-image', ClientRect(0, 0, 900, 600)
        class OCR:
            def recognize(inner, image, vocabulary):
                infer_calls.append(image)
                return {'automatic_candidates': copy.deepcopy(candidates),
                        'candidates': copy.deepcopy(candidates),
                        'image_size': {'width': 900, 'height': 400}}
        def recognize(image, roi, ocr, vocabulary, matcher):
            hero_calls.append(image)
            result = ocr.recognize(b'exact-title-crop', vocabulary)
            result['hero_observation'] = {'hero': hero, 'confident': True}
            return result
        self.window.capture = Capture()
        self.window.ocr = OCR()
        with patch('hero_recognition.recognize_frame', side_effect=recognize):
            for expected in (False, True, True):
                self.window.capture_hidden(self.window.state.generation)
                self.wait(lambda: not self.window.ocr_busy)
                self.assertEqual(self.window.state.confirmed, expected)
            self.assertEqual(len(capture_calls), 3)
            self.assertEqual(len(hero_calls), 3)
            self.assertEqual(len(infer_calls), 2)
            self.assertEqual(self.window.state.automatic_frames, 2)
            self.assertGreaterEqual(self.window.last_observation, capture_calls[-1] - .01)
            self.window.invalidate_scene('owned ROI/scene reset')
            self.window.capture_hidden(self.window.state.generation)
            self.wait(lambda: not self.window.ocr_busy)
            self.assertFalse(self.window.state.confirmed)
            self.assertEqual(len(infer_calls), 3)

    def test_changed_hero_cached_titles_require_two_fresh_confirmations_in_both_directions(self):
        from screen_capture import ClientRect
        names = list(self.window.data['augments'])[:3]
        heroes = list(self.window.data['heroes'])[:2]
        self.assertEqual(len(heroes), 2)
        selected = [heroes[0]]
        calls = []
        candidates = [{'name': name, 'recognized_text': name, 'match_method': 'exact',
                       'ocr_confidence': .99, 'box': [[x-40, 150], [x+40, 150],
                                                    [x+40, 180], [x-40, 180]]}
                      for x, name in zip((150, 450, 750), names)]
        class Capture:
            def capture(inner, *args, **kwargs):
                return b'owned-image', ClientRect(0, 0, 900, 600)
        class OCR:
            def recognize(inner, image, vocabulary):
                calls.append(selected[0])
                return {'automatic_candidates': copy.deepcopy(candidates),
                        'candidates': copy.deepcopy(candidates),
                        'image_size': {'width': 900, 'height': 400}}
        def recognize(image, roi, ocr, vocabulary, matcher):
            result = ocr.recognize(b'unchanged-owned-titles', vocabulary)
            result['hero_observation'] = {'hero': selected[0], 'confident': True}
            return result
        def tick():
            self.window.capture_hidden(self.window.state.generation)
            self.wait(lambda: not self.window.ocr_busy)
        self.window.capture = Capture()
        self.window.ocr = OCR()
        self.window.ocr_reuse.clock = lambda: 100.0  # Deterministic non-expired owned cache.
        with patch('hero_recognition.recognize_frame', side_effect=recognize):
            tick(); tick()
            self.assertTrue(self.window.state.confirmed)
            self.assertEqual(len(calls), 2)
            for hero in (heroes[1], heroes[0]):
                selected[0] = hero
                before = len(calls)
                tick()  # Fresh hero + reused title must revoke old confirmation.
                self.assertEqual(len(calls), before)
                self.assertEqual(self.window.state.automatic_frames, 0)
                self.assertEqual(self.window.state.hero, '')
                self.assertFalse(self.window.state.confirmed)
                self.assertFalse(self.window.overlay.isVisible())
                tick()
                self.assertEqual(len(calls), before + 1)
                self.assertEqual(self.window.state.automatic_frames, 1)
                self.assertEqual(self.window.state.hero, hero)
                self.assertFalse(self.window.state.confirmed)
                self.assertFalse(self.window.overlay.isVisible())
                tick()
                self.assertEqual(len(calls), before + 2)
                self.assertEqual(self.window.state.automatic_frames, 2)
                self.assertEqual(self.window.state.hero, hero)
                self.assertTrue(self.window.state.confirmed)

    def test_watchdog_never_restores_overlay_while_capture_worker_is_busy(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        rect = ClientRect(0, 0, 900, 600)
        class Capture:
            def rect(inner, target):return rect
            def foreground(inner, target):return True
        self.window.capture = Capture()
        self.window.state.hero = next(iter(self.window.data['heroes']))
        self.window.state.confirm(list(self.window.data['augments'])[:3], self.window.data['augments'])
        self.window.last_observation = time.monotonic()
        self.window.last_rect = rect
        self.window.overlay.cards = [{'name': 'owned synthetic card'}]
        self.window.overlay.hide()
        self.window.ocr_busy = True
        self.window.ocr_started = time.monotonic()
        ControlWindow.check_target(self.window)
        self.assertFalse(self.window.overlay.isVisible())
        self.window.ocr_busy = False
        ControlWindow.check_target(self.window)
        self.assertTrue(self.window.overlay.isVisible())

    def test_manual_process_binding_and_post_inference_geometry_fail_closed(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        rect = ClientRect(0, 0, 900, 600)
        current = [rect]
        class Capture:
            def rect(inner, target):return current[0]
            def foreground(inner, target):return True
        self.window.capture = Capture()
        self.window.manual_identity = self.window.target.identity
        self.window.manual_metadata = ProcessMetadata('c:\\owned\\fixture.exe', 111)
        with patch('session_windows.process_metadata', return_value=self.window.manual_metadata):
            self.assertTrue(ControlWindow.target_allowed(self.window))
        with patch('session_windows.process_metadata', return_value=ProcessMetadata('c:\\owned\\fixture.exe', 222)):
            self.assertFalse(ControlWindow.target_allowed(self.window))
        proof = {'_captureRect': rect, '_windowIdentity': self.window.target.identity}
        self.assertTrue(ControlWindow.captured_frame_current(self.window, proof))
        current[0] = ClientRect(1, 0, 900, 600)
        self.assertFalse(ControlWindow.captured_frame_current(self.window, proof))
        self.assertFalse(ControlWindow.captured_frame_current(self.window, {}))


if __name__ == '__main__':
    unittest.main()
