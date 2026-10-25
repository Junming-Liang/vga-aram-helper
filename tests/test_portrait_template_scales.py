"""Exact model-preparation parity; synthetic pixels, not game accuracy evidence."""
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    cv2 = None


class OnDemandScales:
    """Reference: perform the original resize in order during each frame."""
    def __init__(self, templates):
        self.templates = templates

    def __getitem__(self, key):
        template = self.templates[key][1]
        return ((size, cv2.resize(template, (size, size), interpolation=cv2.INTER_AREA))
                for size in range(20, 49, 2))


@unittest.skipIf(cv2 is None, 'Optional OpenCV runtime is not installed')
class PortraitTemplateScaleTests(unittest.TestCase):
    def setUp(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import portraits
        self.bank = portraits()
        self.heroes = {f'Original hero {i}': {'championId': str(9001+i)}
                       for i in range(len(self.bank))}
        self.matcher = PortraitMatcher(self.bank, self.heroes)
        class ReferenceMatcher(PortraitMatcher):
            @property
            def _scaled_templates(inner):
                return OnDemandScales(inner.templates)
        self.reference_class = ReferenceMatcher
        self.reference = ReferenceMatcher(self.bank, self.heroes)

    def test_every_prepared_scale_matches_original_resize_exactly(self):
        self.assertEqual(list(self.matcher._scaled_templates), list(self.matcher.templates))
        for key, variants in self.matcher._scaled_templates.items():
            self.assertEqual([size for size, _ in variants], list(range(20, 49, 2)))
            for size, pixels in variants:
                expected = cv2.resize(self.matcher.templates[key][1], (size, size),
                                      interpolation=cv2.INTER_AREA)
                np.testing.assert_array_equal(pixels, expected)
                self.assertEqual(pixels.dtype, expected.dtype)
        self.assertEqual(sum(pixels.nbytes for variants in self.matcher._scaled_templates.values()
                             for _, pixels in variants), len(self.bank)*sum(s*s for s in range(20, 49, 2)))

    def test_complete_results_match_on_demand_for_positive_and_negative_scenes(self):
        from synthetic_vision import encoded, frame
        cases = [(f'{width}x{height}', frame(self.bank['9001'], width=width, height=height), True)
                 for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3440, 1440))]
        cases.extend([
            ('sidebar', frame(self.bank['9001'], side=True), False),
            ('grayscale', frame(self.bank['9001'], gray=True), False),
            ('blank', Image.new('RGB', (1280, 720), (20, 30, 40)), False),
            ('portrait layout', frame(self.bank['9001'], width=900, height=1200), False),
        ])
        for name, pixels, confident in cases:
            with self.subTest(name=name):
                image = encoded(pixels)
                actual = self.matcher.recognize(image)
                self.assertEqual(actual, self.reference.recognize(image))
                self.assertIs(actual['confident'], confident)
                if confident:
                    self.assertEqual(actual['championId'], '9001')

    def test_cache_miss_searches_every_scale_and_exact_hit_retains_fresh_color_checks(self):
        from synthetic_vision import encoded, frame
        image = encoded(frame(self.bank['9001']))
        before = {key: tuple(pixels.tobytes() for _, pixels in variants)
                  for key, variants in self.matcher._scaled_templates.items()}
        for expected_searches in (len(self.bank)*15, 0):
            with patch.object(cv2, 'resize', wraps=cv2.resize) as resize, \
                    patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match:
                result = self.matcher.recognize(image)
                self.assertTrue(result['confident'])
                self.assertEqual(match.call_count, expected_searches)
                # Full-frame normalization and winning RGB color check remain.
                self.assertEqual(resize.call_count, 2)
        after = {key: tuple(pixels.tobytes() for _, pixels in variants)
                 for key, variants in self.matcher._scaled_templates.items()}
        self.assertEqual(before, after)

    def test_runner_up_tie_and_color_rejection_remain_unchanged(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import encoded, frame
        duplicated = {'9001': self.bank['9001'], '9002': self.bank['9001']}
        matcher = PortraitMatcher(duplicated, self.heroes)
        reference = self.reference_class(duplicated, self.heroes)
        actual = matcher.recognize(encoded(frame(self.bank['9001'])))
        self.assertEqual(actual, reference.recognize(encoded(frame(self.bank['9001']))))
        self.assertFalse(actual['confident'])
        self.assertEqual(actual['margin'], 0)
        # Isolate the independent RGB color gate without mutating models:
        # retain matching grayscale inputs but invert the test RGB patch.
        from dataclasses import replace
        rgb = np.asarray(frame(self.bank['9001']))
        prepared = self.matcher._prepare_array(rgb)
        prepared = replace(prepared, rgb=255-prepared.rgb)
        actual = self.matcher._recognize_prepared(prepared)
        self.assertEqual(actual, self.reference._recognize_prepared(prepared))
        self.assertFalse(actual['confident'])
        self.assertIn('colorScore', actual)


if __name__ == '__main__':
    unittest.main()
