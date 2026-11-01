"""Owned Qt display-lifecycle checks for the recognition box blinking report.

One strict-hidden pixel recheck withdraws the overlay, and the box must return as
soon as that frame's pixels are already in hand rather than after the whole local
inference. These are synthetic fixtures: no Windows capture, WGC session, real
League client or live game is exercised here.
"""
import unittest
from unittest.mock import patch

from tests import test_client_feedback as fixtures
from tests.test_badge_effective_placement import OwnedCapture


def hide_observer(overlay):
    from PySide6 import QtCore
    events = []

    class Observer(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Type.Hide:
                events.append(1)
            return False

    return events, Observer(overlay)


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class ClientStripRestoreTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ClientDisplayTests.setUpClass.__func__)
    setUp = fixtures.ClientDisplayTests.setUp
    pump = fixtures.ClientDisplayTests.pump
    dispose = fixtures.ClientDisplayTests.dispose
    prepare_client = fixtures.ClientDisplayTests.prepare_client
    deliver = fixtures.ClientDisplayTests.deliver

    def start_strict_hidden_recheck(self, captured_at):
        w = self.window
        w._visible_previous = False
        w.monitor.stop()
        w.capture_pending = True
        w.ocr_busy = True
        w.ocr_started = captured_at - .1
        w._capture_serial += 1
        w.overlay.hide('capture_pending')
        self.assertFalse(w.overlay.isVisible())
        return dict(_capturedAt=captured_at, _captureSerial=w._capture_serial,
                    _windowIdentity=w.target.identity, _captureRect=self.proof['rect'])

    def test_unchanged_client_strip_returns_as_soon_as_pixels_are_acquired(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        self.assertTrue(w.overlay.isVisible())
        revision = w.overlay._layout_revision
        observation = w.last_observation
        proof = self.start_strict_hidden_recheck(101.3)
        events, observer = hide_observer(w.overlay)
        with patch('native_ui.time.monotonic', return_value=101.4):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertTrue(w.overlay.isVisible())
        # Presentation only: inference is still running, no new observation and
        # no structural rebuild happened on the way back.
        self.assertTrue(w.ocr_busy)
        self.assertFalse(w.capture_pending)
        self.assertEqual(w.overlay._layout_revision, revision)
        self.assertEqual(w.last_observation, observation)
        self.assertEqual(events, [])

    def test_a_strip_whose_client_authority_aged_out_is_not_brought_back(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        proof = self.start_strict_hidden_recheck(101.3)
        with patch('native_ui.time.monotonic', return_value=106.):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertFalse(w.client_strip_current())
        self.assertFalse(w._restore_while_ocr)
        self.assertFalse(w.overlay.isVisible())

    def test_card_badges_still_need_their_own_frame_proof_to_return(self):
        self.window.lcu_toggle.setChecked(True)
        w = self.prepare_client()
        self.deliver(100., 100.1)
        self.deliver(101., 101.1)
        # An accepted card display carries no client-authoritative strip, so the
        # pixel proof alone decides whether the old grades may be shown.
        w.overlay.reference = None
        w.overlay.cards = [dict(slot=1, name='候选', sourceTier='T1', sourceTierLabel='来源评级')]
        proof = self.start_strict_hidden_recheck(101.3)
        with patch('native_ui.time.monotonic', return_value=101.4):
            w.task_result('capture-proof', proof, w.state.generation)
        self.assertFalse(w._restore_while_ocr)
        self.assertFalse(w.overlay.isVisible())


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt/PIL runtime is not installed')
class NativeReassertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (fixtures.QtWidgets.QApplication.instance()
                   or fixtures.QtWidgets.QApplication([]))
        cls.app.setQuitOnLastWindowClosed(False)

    def overlay(self, capture):
        from native_ui import Overlay
        widget = Overlay(capture=capture)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_configure_skips_the_native_reassert_while_enrollment_still_matches(self):
        calls = []

        class Stateful:
            def __init__(self, current):
                self.current = current

            def overlay_state_current(self, hwnd):
                return self.current

            def configure_overlay(self, *args, **kwargs):
                calls.append((args, kwargs))

        widget = self.overlay(Stateful(True))
        widget.configure()
        self.assertEqual(calls, [])
        widget.capture = Stateful(False)
        widget.configure()
        self.assertEqual(len(calls), 1)

    def test_a_stale_badge_placement_key_never_survives_leaving_the_badges(self):
        from types import SimpleNamespace
        from screen_capture import ClientRect
        capture = OwnedCapture()
        widget = self.overlay(capture)
        cards = [dict(slot=i + 1, name=f'候选{i + 1}', sourceTier=f'T{i + 1}',
                      sourceTierLabel='虎牙公开源评级') for i in range(3)]
        candidates = [dict(name=f'候选{i + 1}',
                           box=[[90 + i * 270, 230], [180 + i * 270, 230],
                                [180 + i * 270, 260], [90 + i * 270, 260]]) for i in range(3)]
        geometry = SimpleNamespace(rects=((.05, .3, .25, .6), (.35, .3, .25, .6), (.65, .3, .25, .6)),
                                   size=(900, 600), space='frame')
        widget.set_cards('阿萝拉', cards, '2026-09-07', '26.21', '自动识别')
        widget.set_candidate_geometry(candidates, {'width': 900, 'height': 600}, (0, 0, 1, 1), geometry)
        with patch('card_badges.native_region', return_value=True):
            widget.show_at(ClientRect(0, 0, 1600, 900), None)
        self.assertIsNotNone(widget._placed_key)
        widget._leave_badges()
        self.assertIsNone(widget._placed_key)
        self.assertIsNone(widget._expired_badge_placement)


if __name__ == '__main__':
    unittest.main()
