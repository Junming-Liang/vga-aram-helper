"""Real Qt/OCR producer-consumer checks on owned animated in-memory pixels.

Capture/session/process/compositor proofs are explicit test doubles. These
checks do not establish Windows WGC, yellow-border or actual-game behavior.
The tail gate delays a genuine LocalOCR result; it never invents OCR rows.
"""
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_animated_augment_rounds as fixture


@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class LatestCaptureRealOCRTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AnimatedAugmentRoundTests.setUpClass.__func__)
    wait = fixture.AnimatedAugmentRoundTests.wait
    dispose_window = fixture.AnimatedAugmentRoundTests.dispose_window
    record_result = fixture.AnimatedAugmentRoundTests.record_result
    record_error = fixture.AnimatedAugmentRoundTests.record_error
    start_frame = fixture.AnimatedAugmentRoundTests.start_frame
    finish_frame = fixture.AnimatedAugmentRoundTests.finish_frame
    observe = fixture.AnimatedAugmentRoundTests.observe
    assert_confirmed = fixture.AnimatedAugmentRoundTests.assert_confirmed

    def setUp(self):
        fixture.AnimatedAugmentRoundTests.setUp(self)
        from session_windows import ProcessMetadata
        from screen_capture import CapturePaused
        self.metadata = ProcessMetadata(r'C:\Owned Fixture\League of Legends.exe', 123456)
        self.process_probe = patch('session_windows.process_metadata', return_value=self.metadata)
        self.process_probe_mock = self.process_probe.start()
        self.addCleanup(self.process_probe.stop)
        real_clock = patch('native_ui.time', time)
        real_clock.start()
        self.addCleanup(real_clock.stop)
        w = self.window
        w.ocr_reuse.clock = time.monotonic
        w.capture_metadata = lambda: self.metadata
        self.capture_calls = []
        self.compositor_checks = []
        self.active_captures = 0
        self.maximum_active_captures = 0
        capture = w.capture
        capture.can_request_visible_overlay = True
        capture.visible_capture_status = 'eligible'
        capture.has_live_visible_session = True
        capture.session_epoch = 1
        capture.last_capture_diagnostic = {}
        capture.prepare_capture_mode = lambda visible: True
        self.capture_delay = .035
        capture_lock = threading.Lock()

        def retired():
            capture.has_live_visible_session = False
            capture.session_epoch += 1

        def validate(target, rect, *, allow_visible_overlay=False):
            self.assertEqual(target.identity, w.target.identity)
            self.assertEqual(rect, self.rect)
            self.assertTrue(capture.foreground(target))
            self.compositor_checks.append((target.identity, rect, allow_visible_overlay))

        def acquire(target, roi, *, cancelled, expected_metadata, **options):
            self.assertEqual(target.identity, w.target.identity)
            self.assertEqual(expected_metadata, self.metadata)
            self.assertEqual(roi, (0., 0., 1., 1.))
            self.assertTrue(options.get('allow_visible_overlay'))
            self.assertTrue(capture.has_live_visible_session)
            is_cancelled = cancelled if callable(cancelled) else cancelled.is_set
            with capture_lock:
                self.active_captures += 1
                self.maximum_active_captures = max(self.maximum_active_captures, self.active_captures)
            try:
                started = time.monotonic()
                while time.monotonic() - started < self.capture_delay:
                    if is_cancelled():
                        raise CapturePaused('Owned cancelled acquisition')
                    time.sleep(.002)
                payload = capture.payload
                self.capture_calls.append(dict(started=started, acquired=time.monotonic(),
                    payload=payload, thread=threading.get_ident(), epoch=capture.session_epoch))
                return payload, self.rect
            finally:
                with capture_lock:
                    self.active_captures -= 1

        capture.retire_session = retired
        capture.validate_compositor = validate
        capture.capture = acquire
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        self.assertEqual(self.errors, [])

    def start_held_ocr(self, phase=2):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        self.window.ocr.next_gate = (entered, release)
        previous = len(self.results)
        self.start_frame((0, 1, 2), phase)
        self.wait(lambda: entered.is_set())
        self.assertTrue(self.window.ocr_busy)
        self.assertFalse(self.window.capture_pending)
        return release, previous

    def buffered_packet(self):
        buffer = self.window.latest_capture
        with buffer._condition:
            return buffer._slot[2] if buffer._slot is not None else None

    def acquire_distinct_buffer(self, phase=3):
        from synthetic_vision import encoded
        w = self.window
        self.wait(lambda: not w.latest_capture.busy)
        w.latest_capture.clear()
        w.capture.payload = encoded(self.scene.image((0, 1, 2), phase))
        w._prefetch_last_attempt = 0.
        w.check_target()
        self.wait(lambda: not w.latest_capture.busy and self.buffered_packet() is not None)
        return self.buffered_packet()

    def test_slow_ocr_keeps_acquiring_after_display_expiry_without_renewing_it(self):
        w = self.window
        observed_at = w.last_observation
        generation, session_epoch = w.state.generation, w.capture.session_epoch
        release, previous = self.start_held_ocr()
        active_capture_at = w._current_capture_proof[2]['_capturedAt']
        calls_at_start = len(self.capture_calls)
        w.watchdog.start()
        try:
            self.wait(lambda: not w.state.confirmed, seconds=6)
            self.assertFalse(w.overlay.isVisible())
            self.assertGreaterEqual(time.monotonic() - observed_at, 4.)
            calls_at_expiry = len(self.capture_calls)
            self.wait(lambda: len(self.capture_calls) > calls_at_expiry
                      and time.monotonic() - active_capture_at > 4.1, seconds=3)
            self.assertGreaterEqual(len(self.capture_calls) - calls_at_start, 3)
            self.assertEqual(w.last_observation, observed_at)
            self.assertEqual(len(self.results), previous)
            self.assertTrue(w.ocr_busy)
            self.assertFalse(w.state.confirmed)
            self.assertFalse(w.overlay.isVisible())
        finally:
            w.watchdog.stop()
            release.set()
        self.wait(lambda: len(self.results) > previous and not w.ocr_busy
                  and not w._workers and not w.latest_capture.busy)
        self.assertGreater(self.results[-1]['_completedAt'] - self.results[-1]['_capturedAt'], 4.)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w.last_observation, observed_at)
        # The result is stale, but a still-proven capture session is not.
        # Rejection cannot replace the session or revoke the target generation.
        self.assertEqual(w.state.generation, generation)
        self.assertEqual(w.capture.session_epoch, session_epoch)
        self.assertTrue(w.capture.has_live_visible_session)
        self.assertFalse(w._capture_cancel.is_set())
        self.assertEqual(w.state.automatic_frames, 0)
        self.assertEqual(w.state.hero_stable_frames, 0)
        first = self.observe((0, 1, 2), 3)
        self.assertFalse(first['ocr_reused'])
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.automatic_frames, 1)
        self.assertEqual(w.capture.session_epoch, session_epoch)
        second = self.observe((0, 1, 2), 4)
        self.assertFalse(second['ocr_reused'])
        self.assertLess(first['_captureSerial'], second['_captureSerial'])
        self.assertLess(first['_capturedAt'], second['_capturedAt'])
        self.assert_confirmed((0, 1, 2))
        self.assertEqual(w.state.automatic_frames, 2)
        self.assertEqual(w.capture.session_epoch, session_epoch)
        self.assertTrue(w.capture.has_live_visible_session)
        self.assertEqual(self.maximum_active_captures, 1)
        self.assertEqual(self.errors, [])

    def test_consumer_preserves_buffered_capture_time_and_revalidates_process(self):
        w = self.window
        release, previous = self.start_held_ocr()
        packet = self.acquire_distinct_buffer()
        release.set()
        self.wait(lambda: len(self.results) > previous and not w.ocr_busy and not w._workers)
        self.assertTrue(w.state.confirmed)
        calls_before = len(self.capture_calls)
        self.process_probe_mock.reset_mock()
        previous = len(self.results)
        # Isolate the next consumer from producing yet another following frame.
        with patch.object(w, 'queue_latest_capture'):
            w.capture_tick()
            self.wait(lambda: len(self.results) > previous and not w.ocr_busy and not w._workers)
        result = self.results[-1]
        self.assertEqual(result['_capturedAt'], packet.captured_at)
        self.assertLess(packet.captured_at, result['_completedAt'])
        self.assertEqual(w.last_observation, packet.captured_at)
        self.assertEqual(result['_timings']['capture_ms'],
                         round((packet.acquired_at - packet.captured_at) * 1000, 1))
        self.assertEqual(len(self.capture_calls), calls_before)
        self.process_probe_mock.assert_called_with(w.target.pid)
        self.assertIn((w.target.identity, packet.rect, True), self.compositor_checks)
        self.assertFalse(result['ocr_reused'])
        self.assertTrue(w.state.confirmed)
        self.assertEqual(self.maximum_active_captures, 1)
        self.assertEqual(self.errors, [])

    def run_age_only_expiry(self, phase):
        """Advance only the controller clock; no timing-sensitive sleep race."""
        from synthetic_vision import encoded
        w = self.window
        release, previous = self.start_held_ocr()
        packet = self.acquire_distinct_buffer()
        release.set()
        self.wait(lambda: len(self.results) > previous and not w.ocr_busy and not w._workers)
        generation, epoch = w.state.generation, w.capture.session_epoch
        calls_before = len(self.capture_calls)
        previous = len(self.results)
        # It is usable when taken, then expires strictly during the selected
        # worker phase. Fresh capture uses different owned animated pixels.
        now = [packet.captured_at + .7]
        w.capture.payload = encoded(self.scene.image((0, 1, 2), 8))
        advanced = []
        original_prepare = w.ocr.prepare
        original_validate = w.capture.validate_compositor
        def prepare():
            original_prepare()
            if phase == 'prepare' and not advanced:
                now[0] += .2; advanced.append(True)
        def validate(*args, **kwargs):
            original_validate(*args, **kwargs)
            if phase == 'compositor' and not advanced:
                now[0] += .2; advanced.append(True)
        with patch('native_ui.time', SimpleNamespace(monotonic=lambda: now[0])), \
                patch.object(w.latest_capture, '_clock', lambda: now[0]), \
                patch.object(w.ocr, 'prepare', side_effect=prepare), \
                patch.object(w.capture, 'validate_compositor', side_effect=validate), \
                patch.object(w, 'queue_latest_capture'):
            w.capture_tick()
            self.wait(lambda: (len(self.results) > previous or self.errors)
                      and not w.ocr_busy and not w._workers)
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.capture_calls), calls_before + 1)
        self.assertEqual(self.capture_calls[-1]['payload'], w.capture.payload)
        result = self.results[-1]
        self.assertEqual(result['_capturedAt'], now[0])
        self.assertGreater(result['_capturedAt'], packet.captured_at)
        self.assertEqual(w.last_observation, now[0])
        self.assertTrue(w.state.confirmed)
        self.assertEqual(w.state.generation, generation)
        self.assertEqual(w.capture.session_epoch, epoch)
        self.assertTrue(w.capture.has_live_visible_session)
        self.assertEqual(self.maximum_active_captures, 1)

    def test_expiry_during_prepare_recaptures_without_resetting_session(self):
        self.run_age_only_expiry('prepare')

    def test_expiry_during_compositor_recaptures_without_resetting_session(self):
        self.run_age_only_expiry('compositor')

    def test_stop_revokes_buffered_frame_generation_and_late_recognition(self):
        w = self.window
        release, previous = self.start_held_ocr()
        self.assertIsNotNone(self.acquire_distinct_buffer())
        old_generation, old_epoch = w.state.generation, w.capture.session_epoch
        observed_at = w.last_observation
        w.stop_monitor()
        self.assertGreater(w.state.generation, old_generation)
        self.assertGreater(w.capture.session_epoch, old_epoch)
        self.assertIsNone(self.buffered_packet())
        self.assertFalse(w.capture.has_live_visible_session)
        self.assertFalse(w.state.running)
        self.assertFalse(w.overlay.isVisible())
        release.set()
        self.wait(lambda: not w._workers and not w.latest_capture.busy)
        self.assertIsNone(self.buffered_packet())
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w.last_observation, observed_at)
        self.assertEqual(self.maximum_active_captures, 1)


if __name__ == '__main__':
    unittest.main()
