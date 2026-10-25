"""Fresh requalification after TTL with real Qt and owned native boundaries.

These tests do not establish actual WGC or game behavior. Expired data must
stay hidden; only a separately accepted fresh result may reuse installed mask
metadata, after current native bounds/region checks.
"""
import unittest
from unittest.mock import patch
from tests import test_semantic_title_recheck as semantic
from tests import test_native_capture_worker as fixture
from tests.test_badge_effective_placement import OwnedCapture


@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime is not installed')
class ExpiredBadgePlacementTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = fixture.NativeCaptureWorkerTests.setUp
    wait = fixture.NativeCaptureWorkerTests.wait
    dispose_window = fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture = fixture.NativeCaptureWorkerTests.accepted_proof_fixture
    scene = semantic.SemanticTitleRecheckTests.scene

    def expire_scene(self):
        value, hero, names = self.scene()
        w = self.window; rect = value['_captureRect']
        capture = OwnedCapture()
        capture.rect = lambda target: rect
        capture.foreground = lambda target: True
        w.capture = w.overlay.capture = capture
        w.overlay.show_at(rect, w.target)
        self.placement = (w.overlay._badge_bounds, w.overlay._badge_regions)
        self.key = w.overlay._placed_key
        capture.session = object(); self.session = capture.session
        self.retires = capture.retirements
        w.last_observation = w._accepted_frame['observed_at'] = 100.
        w.state.automatic_observed = w.state.observed = names
        w.state.automatic_frames = w.state.stable_frames = 2
        w.ocr_started = 102.7; w.ocr_busy = True; w.capture_pending = False
        with patch('native_ui.time.monotonic', return_value=104.01):
            w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.overlay._badge_anchors)
        self.assertIsNone(w.overlay._placed_key)
        self.assertIsNone(w._accepted_frame)
        self.assertIsNone(w._accepted_partial_frame)
        self.assertIs(capture.session, self.session)
        self.assertEqual(capture.retirements, self.retires)
        return dict(value, _capturedAt=102.7,
                    hero_observation={'hero': hero, 'confident': True})

    def test_fresh_same_layout_requalifies_without_retiring_healthy_session(self):
        fresh = self.expire_scene(); w = self.window
        calls = []
        def native(hwnd, regions, *, verify_only=False):
            calls.append((hwnd, regions, verify_only))
            self.assertEqual(regions, self.placement[1])
        with patch('native_ui.time.monotonic', return_value=104.7), \
                patch.object(w.overlay, 'setMask', wraps=w.overlay.setMask) as mask, \
                patch('card_badges.native_region', side_effect=native):
            w.task_result('ocr', fresh, w.state.generation)
        self.assertTrue(w.state.confirmed)
        self.assertTrue(w.overlay.isVisible())
        self.assertEqual(w.last_observation, 102.7)
        self.assertEqual(w.overlay._placed_key, self.key)
        self.assertEqual((w.overlay._badge_bounds, w.overlay._badge_regions), self.placement)
        self.assertEqual(w.capture.retirements, self.retires)
        self.assertIs(w.capture.session, self.session)
        self.assertTrue(calls)
        self.assertTrue(all(call[2] for call in calls))
        self.assertTrue(w.capture.reads)
        mask.assert_not_called()

    def test_old_pixels_cannot_redisplay_from_installed_layout_metadata(self):
        fresh = self.expire_scene(); w = self.window
        hint = w.overlay._expired_badge_placement
        with patch('native_ui.time.monotonic', return_value=107.01):
            w.task_result('ocr', fresh, w.state.generation)
            w.check_target()
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.overlay._badge_anchors)
        self.assertIsNone(w.overlay._placed_key)
        self.assertEqual(w.last_observation, 100.)
        self.assertEqual(w.overlay._expired_badge_placement, hint)

    def assert_two_new_frames_recover_without_retirement(self, fresh):
        w = self.window
        for index, captured_at in enumerate((107.1, 107.4)):
            w._capture_serial += 1
            w.ocr_busy = True; w._active_capture_generation = w.state.generation
            current = dict(fresh, _capturedAt=captured_at, _captureSerial=w._capture_serial)
            with patch('native_ui.time.monotonic', return_value=captured_at+.1):
                w.task_result('ocr', current, w.state.generation)
            self.assertIs(w.state.confirmed, index == 1)
            self.assertIs(w.overlay.isVisible(), index == 1)
        self.assertEqual(w.capture.retirements, self.retires)
        self.assertIs(w.capture.session, self.session)
        self.assertEqual((w.overlay._badge_bounds, w.overlay._badge_regions), self.placement)

    def test_stale_callback_then_two_new_frames_keeps_only_physical_hint(self):
        fresh = self.expire_scene(); w = self.window
        hint = w.overlay._expired_badge_placement
        with patch('native_ui.time.monotonic', return_value=107.01):
            w.task_result('ocr', fresh, w.state.generation)
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.automatic_frames, 0)
        self.assertEqual(w.state.hero_stable_frames, 0)
        self.assertEqual(w.overlay._expired_badge_placement, hint)
        self.assert_two_new_frames_recover_without_retirement(fresh)

    def test_long_observation_gap_reconfirms_without_losing_physical_hint(self):
        self.assert_two_new_frames_recover_without_retirement(self.expire_scene())

    def test_regular_invalidation_discards_installed_expiry_hint(self):
        self.expire_scene(); w = self.window
        self.assertIsNotNone(w.overlay._expired_badge_placement)
        w.overlay.clear_candidate_geometry()
        self.assertIsNone(w.overlay._expired_badge_placement)
        self.assertIsNone(w.overlay._placed_key)
        self.assertFalse(w.overlay.isVisible())

    def test_changed_hwnd_does_not_reuse_expiry_hint(self):
        fresh = self.expire_scene(); w = self.window
        hwnd, key = w.overlay._expired_badge_placement
        w.overlay._expired_badge_placement = (hwnd + 1, key)
        with patch('native_ui.time.monotonic', return_value=104.7):
            w.task_result('ocr', fresh, w.state.generation)
        self.assertTrue(w.state.confirmed)
        self.assertEqual(w.capture.retirements, self.retires + 1)
        self.assertIsNone(w.capture.session)

    def assert_incompatible_hint_rebuilds(self, key_index, transform):
        fresh = self.expire_scene(); w = self.window
        hwnd, saved = w.overlay._expired_badge_placement
        key = list(saved); key[key_index] = transform(key[key_index])
        w.overlay._expired_badge_placement = (hwnd, tuple(key))
        with patch('native_ui.time.monotonic', return_value=104.7):
            w.task_result('ocr', fresh, w.state.generation)
        self.assertTrue(w.state.confirmed)
        self.assertEqual(w.capture.retirements, self.retires + 1)
        self.assertIsNone(w.capture.session)

    def test_changed_layout_revision_cannot_reuse_old_hint(self):
        self.assert_incompatible_hint_rebuilds(1, lambda revision: revision + 1)

    def test_different_dpi_cannot_reuse_old_hint(self):
        self.assert_incompatible_hint_rebuilds(2, lambda dpr: dpr + .5)

    def test_different_slot_mask_cannot_reuse_old_hint(self):
        self.assert_incompatible_hint_rebuilds(5, lambda slots: slots[:-1])

    def test_native_region_mismatch_cannot_use_cached_layout(self):
        from screen_capture import CaptureUnavailable
        fresh = self.expire_scene(); w = self.window
        with patch('native_ui.time.monotonic', return_value=104.7), \
                patch('card_badges.native_region', side_effect=CaptureUnavailable('Owned changed region')):
            w.task_result('ocr', fresh, w.state.generation)
        self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.overlay._placed_key)
        self.assertIsNone(w.overlay._expired_badge_placement)


if __name__ == '__main__':
    unittest.main()
