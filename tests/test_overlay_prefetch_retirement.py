"""Own session cancellation must not revoke the replacement badge result.

Real Qt placement, the production controller and the real latest-frame worker
are used together. The same owned Win32 boundary double belongs to the overlay
and controller. This is a concurrency regression, not native Windows evidence.
"""
import threading
import time
import unittest

from latest_capture_frame import CapturedFrame
from screen_capture import CapturePaused
from tests import test_native_capture_worker as fixture
from tests.test_badge_effective_placement import OwnedCapture


@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime is not installed')
class OverlayPrefetchRetirementTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    wait = fixture.NativeCaptureWorkerTests.wait
    dispose_window = fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture = fixture.NativeCaptureWorkerTests.accepted_proof_fixture

    def setUp(self):
        fixture.NativeCaptureWorkerTests.setUp(self)
        self.value, self.hero, self.names = self.accepted_proof_fixture()
        self.rect = self.value['_captureRect']
        w = self.window
        self.capture = OwnedCapture()
        self.capture.rect = lambda target: self.rect
        self.capture.foreground = lambda target: True
        # One owner: replacement layout actually retires the same session that
        # the production latest-frame producer would be using.
        w.capture = w.overlay.capture = self.capture
        w.overlay.show_at(self.rect, w.target)
        self.app.processEvents()
        self.assertTrue(w.overlay.isVisible())
        self.generation = w.state.generation
        self.observed_at = w.last_observation

    def pending_capture(self, *, fail=False):
        w = self.window
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        self.revoked_when_native_retired = []
        real_retire = self.capture.retire_session

        def acquire(cancelled):
            self.cancelled = cancelled
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Owned producer was not released')
            if fail or self.capture.session is None:
                raise CapturePaused('Owned session closed')
            now = time.monotonic()
            return CapturedFrame(b'owned frame', self.rect, now, now)

        def retire():
            self.revoked_when_native_retired.append(self.cancelled())
            real_retire()
            release.set()

        self.capture.session = object()
        self.capture.retire_session = retire
        self.scope = (self.generation, 'owned prefetch')
        self.assertTrue(w.latest_capture.submit(self.scope, acquire))
        self.wait(entered.is_set)
        return release

    def replace_layout(self):
        from tests.badge_fixture import seed_badge_geometry
        w = self.window
        # Expiry/requalification resets placement, even when the new accepted
        # cards occupy the same physical regions. Exercise that actual route.
        w.overlay.clear_candidate_geometry()
        seed_badge_geometry(w.overlay, self.names)
        w.overlay.show_at(self.rect, w.target)

    def test_layout_retirement_waits_for_producer_before_closing_native_session(self):
        w = self.window
        release = self.pending_capture()
        self.replace_layout()
        self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.overlay._placed_key)
        self.assertTrue(w.overlay._capture_retirement_pending)
        self.assertTrue(w.latest_capture.busy)
        self.assertEqual(self.revoked_when_native_retired, [])
        self.assertFalse(self.cancelled())
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        w.check_target()
        self.assertEqual(self.revoked_when_native_retired, [True])
        self.assertTrue(w.state.confirmed)
        self.assertTrue(w.overlay.isVisible())
        self.assertFalse(w.overlay._capture_retirement_pending)
        self.assertEqual(w.state.generation, self.generation)
        self.assertEqual(w.last_observation, self.observed_at)
        self.assertIsNone(w.latest_capture.take(self.scope))
        self.assertIsNone(w.latest_capture.take_failure())

    def test_uncoordinated_old_retirement_invalidates_just_shown_result(self):
        w = self.window
        # Reproduce the old direct capture.retire_session route, which closed
        # the helper without revoking the producer epoch first.
        w.overlay._before_capture_retirement = None
        self.pending_capture()
        self.replace_layout()
        self.wait(lambda: not w.latest_capture.busy)
        self.assertTrue(w.overlay.isVisible())
        self.assertEqual(self.revoked_when_native_retired, [False])
        w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertNotEqual(w.state.generation, self.generation)

    def test_failure_while_waiting_for_layout_revokes_new_result(self):
        w = self.window
        release = self.pending_capture(fail=True)
        self.replace_layout()
        self.assertFalse(w.overlay.isVisible())
        self.assertFalse(self.cancelled())
        self.assertEqual(self.revoked_when_native_retired, [])
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertNotEqual(w.state.generation, self.generation)

    def test_completed_failure_is_not_erased_by_replacement_layout(self):
        w = self.window
        release = self.pending_capture(fail=True)
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        self.replace_layout()
        self.assertFalse(w.overlay.isVisible())
        self.assertEqual(self.revoked_when_native_retired, [])
        w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertNotEqual(w.state.generation, self.generation)

    def test_identical_placement_keeps_producer_and_session(self):
        w = self.window
        release = self.pending_capture()
        session = self.capture.session
        w.overlay._capture_retirement_pending = True
        w.overlay.show_at(self.rect, w.target)
        self.assertFalse(w.overlay._capture_retirement_pending)
        self.assertEqual(self.revoked_when_native_retired, [])
        self.assertIs(self.capture.session, session)
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        self.assertIsNotNone(w.latest_capture.take(self.scope))
        w.check_target()
        self.assertTrue(w.state.confirmed)
        self.assertTrue(w.overlay.isVisible())

    def test_watchdog_does_not_start_another_producer_ahead_of_waiting_layout(self):
        w = self.window
        release = self.pending_capture()
        self.replace_layout()
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        self.capture.has_live_visible_session = True
        self.capture.session_epoch = 9
        self.capture.last_capture_diagnostic = {}
        second_entered, second_release = threading.Event(), threading.Event()
        self._release_events.append(second_release)

        def capture(*args, **kwargs):
            second_entered.set()
            if not second_release.wait(3):
                raise RuntimeError('Owned second producer was not released')
            return b'owned replacement frame', self.rect

        self.capture.capture = capture
        w.ocr_busy = True
        w._restore_while_ocr = True
        w._current_capture_proof = (w.state.generation, w._capture_serial, self.value)
        w._prefetch_last_attempt = 0.
        # Production checks queue_latest_capture BEFORE show_at. A completed
        # producer must not be immediately replaced ahead of the drain retry.
        w.check_target()
        self.assertFalse(w.latest_capture.busy)
        self.assertFalse(second_entered.is_set())
        self.assertTrue(w.overlay.isVisible())
        self.assertFalse(w.overlay._capture_retirement_pending)
        self.assertEqual(self.revoked_when_native_retired, [True])
        # Finishing placement releases only this scheduling hold. New work is
        # still possible once a session is independently enrolled again.
        self.capture.session = object()
        w.queue_latest_capture(time.monotonic(), self.rect)
        self.wait(second_entered.is_set)
        second_release.set()
        self.wait(lambda: not w.latest_capture.busy)
        self.assertIsNone(w.latest_capture.take_failure())

    def test_clear_geometry_and_stop_release_pending_placement(self):
        w = self.window
        w.overlay._capture_retirement_pending = True
        w.overlay.clear_candidate_geometry()
        self.assertFalse(w.overlay._capture_retirement_pending)
        w.overlay._capture_retirement_pending = True
        w.stop_monitor()
        self.assertFalse(w.overlay._capture_retirement_pending)

    def test_waiting_for_layout_does_not_extend_display_deadline(self):
        from unittest.mock import patch
        w = self.window
        release = self.pending_capture()
        self.replace_layout()
        with patch('native_ui.time.monotonic', return_value=self.observed_at + 4.01):
            w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        release.set()
        self.wait(lambda: not w.latest_capture.busy)
        w.check_target()
        self.assertFalse(w.overlay.isVisible())
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.last_observation, self.observed_at)
        self.assertEqual(self.revoked_when_native_retired, [])
        self.assertIsNone(w.latest_capture.take_failure())


if __name__ == '__main__':
    unittest.main()
