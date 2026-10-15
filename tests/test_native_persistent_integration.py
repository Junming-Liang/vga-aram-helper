"""Real Qt lifecycle checks with owned fakes; no Windows capture claim."""
import gc
import os
from pathlib import Path
import tempfile
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
class NativePersistentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def pump(self, predicate=lambda: True):
        until = time.monotonic() + 4
        while time.monotonic() < until:
            self.app.processEvents()
            if predicate(): return
            time.sleep(.005)
        self.fail('Owned Qt lifecycle did not settle')

    def setUp(self):
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('Owned portable fixture')):
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='test', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose)
        self.pump(lambda: self.window.data is not None)
        self.window.watchdog.stop(); self.window.monitor.stop()
        self.events = []
        events = self.events
        class Capture:
            def retire_session(self): events.append('retire')
            def close(self): events.append('close')
            def set_interactive_overlay(self, enabled):events.append(('interactive-mode',enabled))
            def configure_overlay(self, hwnd, click_through, *, opaque=False):
                events.append(('configure', hwnd, click_through, opaque))
        self.capture = Capture()
        self.window.capture = self.capture
        self.window.overlay.capture = self.capture

    def dispose(self):
        window = self.window
        overlay = window.overlay
        window.capture = None; overlay.capture = None
        window.close()
        self.pump(lambda: not window._workers)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(window)); self.assertFalse(isValid(overlay))
        self.window = None; gc.collect(); self.app.processEvents()

    def test_renderer_is_opaque_before_first_native_registration(self):
        overlay = self.window.overlay
        self.assertFalse(overlay.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(overlay.testAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent))
        self.assertEqual(overlay.windowOpacity(), 1.)
        overlay.configure()
        self.assertEqual(self.events, [('configure', int(overlay.winId()), True, True)])
        overlay.show()
        for width,height in ((820,100),(420,160),(900,90)):
            overlay.resize(width,height);self.app.processEvents()
            pixels = overlay.grab().toImage()
            for x, y in ((0, 0), (pixels.width()-1, 0), (0, pixels.height()-1),
                         (pixels.width()-1,pixels.height()-1)):
                self.assertEqual(pixels.pixelColor(x,y).getRgb(),(250,252,255,255))

    def test_click_through_change_retires_before_qt_hwnd_style_change(self):
        overlay = self.window.overlay
        original = overlay.setWindowFlag
        def change(*args):
            self.events.append('qt-style-change'); return original(*args)
        with patch.object(overlay, 'setWindowFlag', side_effect=change):
            overlay.set_click_through(False)
        self.assertEqual(self.events[:2], [('interactive-mode',True), 'qt-style-change'])
        self.assertEqual(self.events[-1], ('configure', int(overlay.winId()), False, True))
        self.assertFalse(overlay.isVisible())

    def test_authorization_and_user_edits_retire_without_reconfirming(self):
        w = self.window
        hero = next(iter(w.data['heroes']))
        for action in (lambda: w.invalidate_scene('Owned permission loss'),
                       lambda: w.roi_changed(), lambda: w.edit_changed(),
                       lambda: w.hero_changed(hero), lambda: w.hero_mode_changed(True),
                       lambda: w.stop_monitor()):
            with self.subTest(action=action):
                self.events.clear(); w._accepted_frame = {'owned': True}
                action()
                self.assertIn('retire', self.events)
                self.assertIsNone(w._accepted_frame)
                self.assertFalse(w.state.confirmed)
                self.assertFalse(w.overlay.isVisible())

    def test_close_revokes_before_overlay_destruction(self):
        overlay = self.window.overlay
        original = overlay.close
        def close_overlay():
            self.events.append('overlay-close'); return original()
        with patch.object(overlay, 'close', side_effect=close_overlay):
            self.window.close()
        self.assertLess(self.events.index('close'), self.events.index('overlay-close'))

    def test_pure_move_retires_fixed_geometry_but_preserves_fresh_cards(self):
        from screen_capture import ClientRect, WindowInfo
        w = self.window; target = WindowInfo(123, 456, 'Owned fixture', 'OwnedClass')
        before = ClientRect(10, 20, 1000, 700); after = ClientRect(17, 25, 1000, 700)
        w.target = target; w.state.start(target.identity)
        w.state.hero = next(iter(w.data['heroes'])); w.state.confirmed = True
        w.last_observation = time.monotonic(); w.last_rect = before
        w._accepted_frame = {'owned': True}; w._restore_while_ocr = True
        w.queue_discovery = lambda: None; w.advance_session_window = lambda: None
        w.target_allowed = lambda: True; w.client_strength_reference = lambda: None
        self.capture.rect = lambda _: after; self.capture.foreground = lambda _: True
        with patch.object(w.overlay, 'show_at') as show:
            w.check_target()
        self.assertIn('retire', self.events)
        self.assertTrue(w.state.confirmed)
        self.assertIsNone(w._accepted_frame); self.assertFalse(w._restore_while_ocr)
        self.assertTrue(w._capture_cancel.is_set())
        show.assert_called_once_with(after, target)

    def test_capture_tick_hides_but_does_not_retire_authorized_session(self):
        from screen_capture import WindowInfo
        w = self.window; w.target = WindowInfo(123, 456, 'Owned fixture', 'OwnedClass')
        w.state.start(w.target.identity); self.capture.foreground = lambda _: True
        w.overlay.show(); self.app.processEvents()
        with patch.object(QtCore.QTimer, 'singleShot') as delayed:
            w.capture_tick()
        self.assertFalse(w.overlay.isVisible()); self.assertTrue(w.capture_pending)
        self.assertNotIn('retire', self.events)
        self.assertEqual(delayed.call_args.args[0], 60)


if __name__ == '__main__':
    unittest.main()
