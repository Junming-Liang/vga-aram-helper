"""First-card recovery audit with original synthetic pixels and real local OCR.

No Windows/game capture or flicker evidence. The Qt worker, native result
handlers, local OCR, portrait matcher, and title/card geometry are production
code. Explicit gates and a controlled native_ui clock inject startup latency;
they do not measure model performance or change freshness/anti-flicker guards.
"""
import threading
import unittest
from unittest.mock import patch

from tests import test_animated_augment_rounds as fixture


@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class FirstCardRecoveryAuditTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp = fixture.AnimatedAugmentRoundTests.setUp
    wait = fixture.AnimatedAugmentRoundTests.wait
    dispose_window = fixture.AnimatedAugmentRoundTests.dispose_window
    record_result = fixture.AnimatedAugmentRoundTests.record_result
    record_error = fixture.AnimatedAugmentRoundTests.record_error
    start_frame = fixture.AnimatedAugmentRoundTests.start_frame
    finish_frame = fixture.AnimatedAugmentRoundTests.finish_frame
    observe = fixture.AnimatedAugmentRoundTests.observe
    assert_confirmed = fixture.AnimatedAugmentRoundTests.assert_confirmed
    assert_unconfirmed = fixture.AnimatedAugmentRoundTests.assert_unconfirmed

    def start_cold_frame(self, *, phase=0):
        """Block before first real model initialization, leaving Qt responsive."""
        w = self.window
        self.assertIsNone(w.ocr._engine)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = w.ocr.recognize

        def cold(*args):
            entered.set()
            if not release.wait(15):
                raise RuntimeError('Owned cold-start gate was not released')
            return original(*args)

        gate = patch.object(w.ocr, 'recognize', side_effect=cold)
        gate.start()
        self.addCleanup(gate.stop)
        previous = len(self.results)
        self.start_frame((0, 1, 2), phase)
        self.wait(entered.is_set)
        # The independent HUD proof must have finished before an injected
        # timeout cancels its generation; otherwise it may legitimately raise.
        if w.hero_matcher is not None:
            self.wait(lambda: bool(w._current_capture_proof and
                w._current_capture_proof[2].get('hero_observation', {}).get('confident')))
        self.assertTrue(w.ocr_busy)
        self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.ocr._engine)
        return previous, self.now, release, gate

    def drain_rejected_frame(self, previous, release, gate):
        release.set()
        self.wait(lambda: len(self.results) > previous or bool(self.errors))
        self.wait(lambda: not self.window.ocr_busy and not self.window.capture_pending
                  and not self.window._workers)
        gate.stop()
        self.assertEqual(self.errors, [])
        self.assertIsNotNone(self.window.ocr._engine)
        self.assertFalse(self.window.frame_inference_worker._busy)
        self.assert_unconfirmed()
        self.assertEqual(self.window.state.automatic_frames, 0)
        self.assertEqual(self.window.state.hero_stable_frames, 0)

    def recover_in_two_independent_frames(self, phase=1):
        first = self.observe((0, 1, 2), phase)
        self.assert_unconfirmed()
        self.assertEqual(self.window.state.automatic_frames, 1)
        second = self.observe((0, 1, 2), phase + 1)
        self.assert_confirmed((0, 1, 2))
        self.assertLess(first['_captureSerial'], second['_captureSerial'])
        self.assertLess(first['_capturedAt'], second['_capturedAt'])
        self.assertEqual(self.window.state.automatic_frames, 2)
        self.assertEqual(self.window.ocr_reuse.hits, 0)
        return first, second

    def test_cold_first_result_over_four_seconds_is_discarded_then_recovers(self):
        from native_ui import ControlWindow
        previous, captured, release, gate = self.start_cold_frame()
        w = self.window
        calls = len(w.capture.calls)
        w.capture_tick()
        self.assertEqual(len(w.capture.calls), calls)  # No overlapping capture.
        self.now = captured + 4.001
        self.drain_rejected_frame(previous, release, gate)
        self.assertEqual(w.last_observation, 0.)
        self.assertIn('过期', w.status.text())
        ControlWindow.schedule_capture(w)
        self.assertTrue(w.monitor.isActive())
        self.assertEqual(w.monitor.interval(), 200)
        w.monitor.stop()
        self.recover_in_two_independent_frames()

    def test_cold_first_timeout_releases_worker_lease_then_recovers(self):
        from native_ui import ControlWindow
        previous, captured, release, gate = self.start_cold_frame()
        w = self.window
        generation = w.state.generation
        self.now = captured + 8.001
        w.check_target()
        self.assertTrue(w.ocr_timed_out)
        self.assertTrue(w._capture_cancel.is_set())
        self.assertNotEqual(w.state.generation, generation)
        self.assertTrue(w.ocr_busy)  # Worker must drain before a retry starts.
        calls = len(w.capture.calls)
        w.capture_tick()
        self.assertEqual(len(w.capture.calls), calls)
        self.drain_rejected_frame(previous, release, gate)
        self.assertIsNone(w._active_capture_generation)
        ControlWindow.schedule_capture(w)
        self.assertTrue(w.monitor.isActive())
        w.monitor.stop()
        self.recover_in_two_independent_frames()
        self.assertFalse(w.ocr_timed_out)

    def test_fresh_delayed_cold_frame_counts_once_and_next_frame_confirms(self):
        previous, captured, release, gate = self.start_cold_frame()
        self.now = captured + 3.7
        release.set()
        first = self.finish_frame(previous)
        gate.stop()
        self.assert_unconfirmed()
        self.assertEqual(self.window.state.automatic_frames, 1)
        self.assertEqual(self.window.last_observation, captured)
        second = self.observe((0, 1, 2), 1, advance=.1)
        self.assertLess(second['_capturedAt'] - first['_capturedAt'], 4.)
        self.assert_confirmed((0, 1, 2))
        self.assertEqual(self.window.state.automatic_frames, 2)
        self.assertEqual(self.window.ocr_reuse.hits, 0)

    def test_initial_card_free_frames_do_not_latch_out_later_valid_cards(self):
        for phase in range(3):
            result = self.observe(None, phase)
            self.assertEqual(result['automatic_candidates'], [])
            self.assert_unconfirmed()
            self.assertEqual(self.window.state.automatic_frames, 0)
        self.recover_in_two_independent_frames(3)

    def test_initial_unknown_middle_becomes_full_without_restarting(self):
        w = self.window
        w.data['augments'].pop(fixture.NAMES[3])
        for phase in range(2):
            self.observe((0, 3, 2), phase)
            self.assertFalse(w.state.confirmed)
        self.assertEqual(w.current_partial_names(),
                         (fixture.NAMES[0], '', fixture.NAMES[2]))
        self.assertTrue(w.overlay.isVisible())
        self.assertFalse(w.overlay._badge_widgets[1].isVisibleTo(w.overlay))
        self.observe((0, 1, 2), 2)
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.current_partial_names(),
                         (fixture.NAMES[0], '', fixture.NAMES[2]))
        self.observe((0, 1, 2), 3)
        self.assert_confirmed((0, 1, 2))
        self.assertEqual(w.ocr_reuse.hits, 0)

    def test_initial_unavailable_templates_recover_when_matcher_arrives(self):
        w = self.window
        matcher = w.hero_matcher
        w.hero_matcher = None
        first = self.observe((0, 1, 2), 0)
        self.assertFalse(first['hero_observation']['confident'])
        self.assertEqual(first['hero_observation']['hudOutcome'], 'templates_unavailable')
        self.assertEqual(tuple(row['name'] for row in first['automatic_candidates']),
                         fixture.NAMES[:3])
        self.assert_unconfirmed()
        self.assertEqual(w.state.hero, '')
        w.hero_matcher = matcher
        self.recover_in_two_independent_frames()

    def test_templates_arriving_during_cold_inference_discard_old_scope_and_recover(self):
        w = self.window
        matcher = w.hero_matcher
        w.hero_matcher = None
        previous, _, release, gate = self.start_cold_frame()
        generation = w.state.generation
        w.hero_matcher = matcher
        self.drain_rejected_frame(previous, release, gate)
        self.assertGreater(w.state.generation, generation)
        self.assertIn('范围变化', w.status.text())
        self.recover_in_two_independent_frames()


if __name__ == '__main__':
    unittest.main()
