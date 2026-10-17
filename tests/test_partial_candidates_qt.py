"""Actual local OCR and owned synthetic Qt capture for per-slot display.

No live game, Windows capture, or measured flicker claim. Low-score/missing-row
cases explicitly mutate one real OCR result to test the result-handler boundary;
the unknown-name/round/reroll/TTL/focus cases use unchanged real OCR output.
"""
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from tests import test_animated_augment_rounds as fixture


@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class PartialCandidatesQtTests(unittest.TestCase):
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

    def make_fourth_unknown(self):
        # Original fourth-title glyphs remain on screen, with no exact current
        # vocabulary entry. This does not alter or fabricate OCR output.
        self.window.data['augments'].pop(fixture.NAMES[3])

    def assert_partial(self, names):
        w = self.window
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.offered, ())
        self.assertEqual(w.current_partial_names(), names)
        self.assertEqual(w.state.hero, fixture.HERO)
        self.assertTrue(w.overlay.isVisible(), w.status.text())
        self.assertIsNone(w._accepted_frame)
        self.assertFalse(w._restore_while_ocr)
        self.assertEqual(len(w.overlay.cards), 3)
        for index, (name, card) in enumerate(zip(names, w.overlay.cards)):
            self.assertEqual(card['slot'], index + 1)
            self.assertEqual(card['name'], name or '待识别')
            self.assertEqual(w.candidate_views[index]['name'].text(), name or '待识别')
            if name:
                self.assertEqual(card['sourceTier'], fixture.TIERS[name])
            else:
                self.assertIsNone(card['sourceTier'])
                self.assertEqual(card['description'], '')
                self.assertEqual(card['notes'], [])
                self.assertTrue(card['pending'])
                self.assertFalse(w.overlay._badge_widgets[index].isVisibleTo(w.overlay))
                self.assertEqual(len(w.overlay._badge_regions),sum(bool(n) for n in names))

    def assert_blank(self):
        w = self.window
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.offered, ())
        self.assertEqual(w.current_partial_names(), ('', '', ''))
        self.assertFalse(w.overlay.isVisible())
        self.assertTrue(all(view['name'].text() == '等待识别' for view in w.candidate_views))

    def test_three_rounds_unknown_middle_and_single_slot_reroll(self):
        self.make_fourth_unknown()
        n = fixture.NAMES
        self.observe((0, 1, 2), 0)
        self.assert_blank()
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        # Same hero/source/geometry: two unaffected slots stay current while
        # the changed middle title loses its previous T2 immediately.
        self.observe((0, 3, 2), 2)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 3, 2), 3)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 1, 2), 4)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 1, 2), 5)
        self.assert_confirmed((0, 1, 2))
        for phase, order, expected in ((6, (2, 3, 0), (n[2], '', n[0])),
                                       (9, (1, 0, 3), (n[1], n[0], ''))):
            self.observe(None, phase, advance=5.)
            self.assert_blank()
            self.observe(order, phase + 1)
            self.assert_blank()
            self.observe(order, phase + 2)
            self.assert_partial(expected)
        self.assertEqual(self.window.ocr_reuse.hits, 0)
        self.assertEqual(len(self.window.ocr.records), 12)

    def test_low_score_blanks_only_that_slot_but_missing_row_revokes_all(self):
        n = fixture.NAMES
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        original = self.window.ocr.recognize
        def low_score(*args):
            result = original(*args)
            middle = next(row for row in result['ocr_lines'] if row['text'] == n[1])
            middle['confidence'] = .92
            return result
        with patch.object(self.window.ocr, 'recognize', side_effect=low_score):
            self.observe((0, 1, 2), 2)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 1, 2), 3)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 1, 2), 4)
        self.assert_confirmed((0, 1, 2))
        def missing_row(*args):
            result = original(*args)
            result['ocr_lines'] = [row for row in result['ocr_lines'] if row['text'] != n[1]]
            return result
        with patch.object(self.window.ocr, 'recognize', side_effect=missing_row):
            self.observe((0, 1, 2), 5)
        self.assert_blank()
        self.observe((0, 1, 2), 6)
        self.assert_blank()
        self.observe((0, 1, 2), 7)
        self.assert_confirmed((0, 1, 2))

    def test_partial_two_frames_unknown_hero_and_stop_clear(self):
        self.make_fourth_unknown()
        n = fixture.NAMES
        self.observe((0, 3, 2), 0)
        self.assert_blank()
        self.observe((0, 3, 2), 1)
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 3, 2), 2, gray=True)
        self.assert_blank()
        self.assertEqual(self.window.state.hero, '')
        self.observe((0, 3, 2), 3)
        self.assert_blank()
        self.observe((0, 3, 2), 4)
        self.assert_partial((n[0], '', n[2]))
        self.window.stop_monitor()
        self.assert_blank()
        self.assertFalse(self.window.state.running)

    def test_focus_roi_and_source_changes_revoke_partial_continuity(self):
        self.make_fourth_unknown()
        n = fixture.NAMES
        w = self.window
        phase = 0
        for change in ('focus', 'roi', 'source'):
            self.observe((0, 3, 2), phase)
            self.observe((0, 3, 2), phase + 1)
            phase += 2
            self.assert_partial((n[0], '', n[2]))
            if change == 'focus':
                w.capture.foreground = lambda target: False
                w.check_target()
                w.capture.foreground = lambda target: True
                w.check_target()
            elif change == 'roi':
                original = w.roi[0].value()
                w.roi[0].setValue(original + 1)
                w.roi[0].setValue(original)
            else:
                w.data = deepcopy(w.data)
                w.check_target()
                w.refresh_card_details()
            self.assert_blank()
            self.observe((0, 3, 2), phase)
            phase += 1
            self.assert_blank()

    def test_expiry_during_visible_inference_does_not_resurrect_old_slots(self):
        self.make_fourth_unknown()
        n = fixture.NAMES
        self.observe((0, 3, 2), 0)
        self.observe((0, 3, 2), 1)
        self.assert_partial((n[0], '', n[2]))
        w = self.window
        w.capture.can_request_visible_overlay = True  # Owned capability fake.
        old_time = w.last_observation
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        w.ocr.next_gate = (ready, release)
        previous = len(self.results)
        self.start_frame((0, 3, 2), 2, advance=2.7)
        self.wait(ready.is_set)
        self.assertTrue(w.overlay.isVisible())
        self.assertTrue(w.overlay._rechecking)
        self.assertIn('复核', w.overlay.heading.text())
        generation = w.state.generation
        self.now = old_time + 4.
        w.check_target()
        self.assertTrue(w.overlay.isVisible())
        self.assertEqual(w.current_partial_names(), (n[0], '', n[2]))
        self.now = old_time + 4.001
        w.check_target()
        self.assert_blank()
        self.assertEqual(w.state.generation, generation)
        self.assertFalse(w._capture_cancel.is_set())
        self.now = old_time + 4.7
        release.set()
        self.finish_frame(previous)
        # The old display expired, but this independent capture was acquired
        # within four seconds of the previous observation and is still fresh.
        # Private continuity can revalidate it without two redundant frames.
        self.assert_partial((n[0], '', n[2]))
        self.observe((0, 3, 2), 3)
        self.assert_partial((n[0], '', n[2]))

    def test_cache_hit_cannot_reauthorize_expired_partial_display(self):
        self.make_fourth_unknown()
        self.observe((0, 3, 2), 0)
        last = self.observe((0, 3, 2), 1)
        w = self.window
        self.now += 4.001
        w.check_target()
        self.assert_blank()
        # Explicit boundary injection: even a purported exact-pixel hit from a
        # fresh capture cannot revive the expired partial display.
        replay = {**last, '_capturedAt': self.now, 'ocr_reused': True,
                  '_captureSerial': w._capture_serial + 1}
        w.task_result('ocr', replay, w.state.generation)
        self.assert_blank()

    def test_manual_edit_and_manual_hero_change_clear_partial(self):
        self.make_fourth_unknown()
        self.observe((0, 3, 2), 0)
        self.observe((0, 3, 2), 1)
        self.assert_partial((fixture.NAMES[0], '', fixture.NAMES[2]))
        w = self.window
        w.edit_changed()
        self.assert_blank()
        self.assertTrue(w.manual_editing)
        w.manual_editing = False
        self.observe((0, 3, 2), 2)
        self.observe((0, 3, 2), 3)
        self.assert_partial((fixture.NAMES[0], '', fixture.NAMES[2]))
        w.hero_changed(next(name for name in w.data['heroes'] if name != fixture.HERO))
        self.assert_blank()


if __name__ == '__main__':
    unittest.main()
