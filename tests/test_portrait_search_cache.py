"""Exact deterministic search reuse never substitutes a captured observation."""
from dataclasses import replace
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None


@unittest.skipIf(cv2 is None, 'Optional OpenCV runtime is not installed')
class PortraitSearchCacheTests(unittest.TestCase):
    def setUp(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import frame, portraits
        self.bank = portraits()
        self.heroes = {f'Owned {key}': {'championId': key} for key in self.bank}
        self.matcher = PortraitMatcher(self.bank, self.heroes)
        # Subclasses remain an exhaustive reference: no trusted built-in cache.
        class ExhaustiveMatcher(PortraitMatcher): pass
        self.reference = ExhaustiveMatcher(self.bank, self.heroes)
        self.rgb = np.asarray(frame(self.bank['9001'])).copy()
        self.searches = len(self.bank) * 15

    def recognize(self, pixels, expected_searches):
        expected = self.reference.recognize_array(pixels)
        with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
            actual = self.matcher.recognize_array(pixels)
        self.assertEqual(match.call_count, expected_searches)
        self.assertEqual(actual, expected)
        return actual

    def test_hit_recomputes_output_and_never_retains_mutable_observation(self):
        first = self.recognize(self.rgb, self.searches)
        first['hero'] = 'tampered'; first['box'][0] = -123
        second = self.recognize(self.rgb.copy(), 0)
        self.assertEqual(second['hero'], 'Owned 9001')
        self.assertGreaterEqual(second['box'][0], 0)
        key, winners = self.matcher._search_cache
        self.assertEqual(len(winners), 2)
        self.assertEqual(key, (self.matcher.proof_identity(),
                               self.matcher._prepare_array(self.rgb).signature))
        # Cache contains only scalar scores/coordinates and existing model
        # arrays, not source/ROI arrays, timestamps or a prior hero dict.
        for score, champion_id, position, size, color in winners:
            self.assertIs(color, self.matcher.templates[champion_id][0])
            self.assertFalse(color.flags.writeable)

    def test_full_roi_change_including_same_grayscale_color_misses(self):
        self.recognize(self.rgb, self.searches)
        prepared = self.matcher._prepare_array(self.rgb)
        changed = self.rgb.copy()
        changed[prepared.y0, prepared.x0] = (100, 100, 100)
        self.recognize(changed, self.searches)
        recolored = changed.copy()
        recolored[prepared.y0, prepared.x0] = (101, 100, 97)
        np.testing.assert_array_equal(self.matcher._prepare_array(changed).gray,
                                      self.matcher._prepare_array(recolored).gray)
        self.recognize(recolored, self.searches)
        self.recognize(recolored, 0)
        # One-entry cache: returning to an earlier input requires a full search.
        self.recognize(self.rgb, self.searches)

    def test_non_input_animation_can_hit_but_letterbox_rechecks_every_frame(self):
        self.recognize(self.rgb, self.searches)
        outside = self.rgb.copy(); outside[100, 100] ^= 1
        self.recognize(outside, 0)
        letterboxed = self.rgb.copy(); letterboxed[:10] = 0
        result = self.recognize(letterboxed, 0)
        self.assertFalse(result['confident'])
        self.assertEqual(result['hudOutcome'], 'letterboxed')

    def test_dimensions_thresholds_and_separate_models_never_share_entries(self):
        from hero_recognition import PortraitMatcher
        self.recognize(self.rgb, self.searches)
        wider = np.pad(self.rgb, ((0, 0), (10, 10), (0, 0)), mode='edge')
        self.recognize(wider, self.searches)
        self.recognize(self.rgb, self.searches)
        self.matcher.minimum_score = self.reference.minimum_score = 1.01
        self.assertFalse(self.recognize(self.rgb, self.searches)['confident'])
        self.assertFalse(self.recognize(self.rgb, 0)['confident'])
        fresh = PortraitMatcher(self.bank, self.heroes)
        with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
            fresh.recognize_array(self.rgb)
        self.assertEqual(match.call_count, self.searches)

    def test_post_search_saturation_and_color_gates_run_on_every_hit(self):
        prepared = self.matcher._prepare_array(self.rgb)
        self.assertTrue(self.matcher._recognize_prepared(prepared)['confident'])
        for pixels in (255-prepared.rgb, np.repeat(prepared.gray[:, :, None], 3, axis=2)):
            # Internal test seam deliberately keeps the search input/signature
            # unchanged to prove no prior final identity bypasses current gates.
            changed = replace(prepared, rgb=pixels)
            expected = self.reference._recognize_prepared(changed)
            with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
                actual = self.matcher._recognize_prepared(changed)
            self.assertEqual(match.call_count, 0)
            self.assertEqual(actual, expected)
            self.assertFalse(actual['confident'])
            self.assertIn(actual['hudOutcome'], ('color_mismatch', 'death_grayscale'))

    def test_negative_and_tied_winners_match_exhaustive_on_repeated_inputs(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import frame
        for pixels in (np.asarray(frame(self.bank['9001'], side=True)),
                       np.asarray(frame(self.bank['9001'], gray=True)),
                       np.asarray(frame(self.bank['9002'])),
                       np.full_like(self.rgb, 60)):
            self.recognize(pixels, self.searches)
            self.recognize(pixels, 0)
        tied = PortraitMatcher({'9001': self.bank['9001'], '9002': self.bank['9001']}, self.heroes)
        first = tied.recognize_array(self.rgb)
        second = tied.recognize_array(self.rgb)
        self.assertEqual(first, second)
        self.assertEqual(second['margin'], 0)
        self.assertFalse(second['confident'])


if __name__ == '__main__':
    unittest.main()
