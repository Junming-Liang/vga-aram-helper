"""Exact pre-match proof coverage and ordering; synthetic pixels only."""
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    cv2 = None


@unittest.skipIf(cv2 is None, 'Optional OpenCV runtime is not installed')
class PortraitInputSignatureTests(unittest.TestCase):
    def setUp(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import frame, portraits
        self.bank = portraits()
        self.matcher = PortraitMatcher(self.bank, {f'Original hero {i}': {'championId': str(9001+i)}
                                                  for i in range(len(self.bank))})
        self.rgb = np.asarray(frame(self.bank['9001'])).copy()

    def test_prepared_arrays_are_exact_original_inputs_and_public_output_is_equal(self):
        from synthetic_vision import encoded
        prepared = self.matcher._prepare_array(self.rgb)
        h, w = self.rgb.shape[:2]
        scale = 720/h
        small = cv2.resize(self.rgb, (round(w*scale), 720), interpolation=cv2.INTER_AREA)
        sw = small.shape[1]
        x0, x1 = max(0, round(sw/2-720*.36)), min(sw, round(sw/2-720*.12))
        y0, y1 = round(720*.86), round(720*.995)
        expected = small[y0:y1, x0:x1]
        np.testing.assert_array_equal(prepared.rgb, expected)
        np.testing.assert_array_equal(prepared.gray, cv2.cvtColor(expected, cv2.COLOR_RGB2GRAY))
        self.assertEqual((prepared.scale, prepared.x0, prepared.y0), (scale, x0, y0))
        self.assertRegex(prepared.signature, r'^[0-9a-f]{64}$')
        self.assertEqual(self.matcher._recognize_prepared(prepared), self.matcher.recognize_array(self.rgb))
        self.assertEqual(self.matcher.recognize_array(self.rgb),
                         self.matcher.recognize(encoded(Image.fromarray(self.rgb))))

    def test_whole_search_roi_and_color_are_bound_not_just_winning_patch(self):
        first = self.matcher._prepare_array(self.rgb)
        changed = self.rgb.copy()
        changed[first.y0, first.x0] = (100, 100, 100)
        a = self.matcher._prepare_array(changed)
        changed[first.y0, first.x0] = (101, 100, 97)
        b = self.matcher._prepare_array(changed)
        np.testing.assert_array_equal(a.gray, b.gray)
        self.assertNotEqual(a.signature, b.signature)
        self.assertNotEqual(first.signature, a.signature)
        changed = self.rgb.copy()
        changed[first.y0+first.rgb.shape[0]-1, first.x0+first.rgb.shape[1]-1] ^= 1
        self.assertNotEqual(first.signature, self.matcher._prepare_array(changed).signature)

    def test_unchanged_inputs_keep_signature_but_source_dimensions_are_bound(self):
        first = self.matcher._prepare_array(self.rgb)
        self.assertEqual(first.signature, self.matcher._prepare_array(self.rgb.copy()).signature)
        outside = self.rgb.copy()
        outside[100, 100] ^= 1
        self.assertEqual(first.signature, self.matcher._prepare_array(outside).signature)
        # Uniform RGB yields identical normalized search pixels at both sizes;
        # source dimensions and scale must nevertheless distinguish the proof.
        a = self.matcher._prepare_array(np.full((720, 1280, 3), 60, dtype=np.uint8))
        b = self.matcher._prepare_array(np.full((1080, 1920, 3), 60, dtype=np.uint8))
        np.testing.assert_array_equal(a.rgb, b.rgb)
        self.assertNotEqual(a.signature, b.signature)

    def test_invalid_layout_and_empty_templates_never_produce_signature(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import encoded
        invalid = [np.zeros_like(self.rgb), np.full((500, 1000, 3), 60, dtype=np.uint8),
                   np.full((1200, 900, 3), 60, dtype=np.uint8)]
        for edge in ('top', 'bottom', 'left', 'right'):
            letterboxed = self.rgb.copy()
            if edge == 'top':letterboxed[:10] = 0
            elif edge == 'bottom':letterboxed[-10:] = 0
            elif edge == 'left':letterboxed[:, :14] = 0
            else:letterboxed[:, -14:] = 0
            invalid.append(letterboxed)
        for pixels in invalid:
            prepared = self.matcher._prepare_image(encoded(Image.fromarray(pixels)))
            self.assertIsInstance(prepared, dict)
            self.assertFalse(prepared['confident'])
            self.assertFalse(hasattr(prepared, 'signature'))
        prepared = PortraitMatcher({}, {})._prepare_array(self.rgb)
        self.assertIsInstance(prepared, dict)
        self.assertFalse(prepared['confident'])

    def test_model_identity_is_per_instance_threshold_bound_and_inputs_readonly(self):
        from hero_recognition import PortraitMatcher
        identity = self.matcher.proof_identity()
        self.assertEqual(identity, self.matcher.proof_identity())
        other = PortraitMatcher(self.bank, self.matcher.names)
        self.assertIsNot(identity[0], other.proof_identity()[0])
        self.matcher.minimum_score = .89
        self.assertNotEqual(identity, self.matcher.proof_identity())
        self.matcher.minimum_score = identity[1]
        self.matcher.minimum_margin = .08
        self.assertNotEqual(identity, self.matcher.proof_identity())
        for mapping in (self.matcher.names, self.matcher.templates, self.matcher._scaled_templates):
            with self.assertRaises(TypeError):mapping['9001'] = None
        for attribute in ('names', 'templates', '_scaled_templates'):
            with self.assertRaises(AttributeError):setattr(self.matcher, attribute, {})
        for color, gray in self.matcher.templates.values():
            self.assertFalse(color.flags.writeable)
            self.assertFalse(gray.flags.writeable)
        for variants in self.matcher._scaled_templates.values():
            for _, pixels in variants:
                self.assertFalse(pixels.flags.writeable)
                with self.assertRaises(ValueError):pixels[0, 0] = 0

    def test_custom_matcher_and_changed_roi_receive_no_reusable_identity(self):
        from hero_recognition import recognize_frame
        from synthetic_vision import encoded
        payload = encoded(Image.fromarray(self.rgb))
        seen = []
        class OCR:
            def recognize(inner, *args):return {'ocr_lines': [], 'candidates': []}
        class Custom:
            def recognize(inner, image):return {'hero': 'Original', 'confident': True}
        recognize_frame(payload, (.15, .25, .7, .35), OCR(), (), Custom(),
                        before_match=lambda signature, crop: seen.append(signature))
        self.assertEqual(seen, [None])
        # A wider source shifts the search ROI coordinates; exact dimension
        # binding revokes proof even if the previous portrait remains visible.
        shifted = np.pad(self.rgb, ((0, 0), (10, 10), (0, 0)), mode='edge')
        self.assertNotEqual(self.matcher._prepare_array(self.rgb).signature,
                            self.matcher._prepare_array(shifted).signature)

    def test_phase_precedes_every_fresh_match_and_uses_one_png_decode(self):
        from hero_recognition import recognize_frame
        from synthetic_vision import encoded
        payload = encoded(Image.fromarray(self.rgb))
        events, crops = [], []
        matcher = self.matcher
        class OCR:
            def recognize(inner, crop, vocabulary):
                events.append('ocr'); crops.append(crop)
                return {'ocr_lines': [], 'candidates': []}
        # Opening a PNG header is not a pixel decode. Track each lazy source's
        # first load with pending decoder tiles so geometry's size-only header
        # check cannot hide an accidental second full-frame decompression.
        original_open = Image.open
        sources, decoded_sources = [], []
        def observe_open(*args, **kwargs):
            source = original_open(*args, **kwargs)
            sources.append(source)
            original_load = source.load
            def observe_load(*load_args, **load_kwargs):
                if getattr(source, 'tile', None):
                    decoded_sources.append(source)
                return original_load(*load_args, **load_kwargs)
            source.load = observe_load
            return source
        with patch.object(cv2, 'matchTemplate', wraps=cv2.matchTemplate) as match, \
                patch.object(Image, 'open', side_effect=observe_open) as opened:
            def before_match(signature, crop):
                self.assertRegex(signature, r'^[0-9a-f]{64}$')
                self.assertEqual(match.call_count, 0)
                events.append('before_match'); crops.append(crop)
            def before_ocr(hero, crop):
                self.assertEqual(match.call_count, len(self.bank)*15)
                self.assertTrue(hero['confident'])
                events.append('before_ocr'); crops.append(crop)
            result = recognize_frame(payload, (.15, .25, .7, .35), OCR(), (), matcher,
                                     before_match=before_match, before_ocr=before_ocr)
            self.assertEqual(opened.call_count, 2)  # Decode plus size-only header validation.
            self.assertEqual(decoded_sources, [sources[0]])
            self.assertIsNot(sources[0], sources[1])
            self.assertEqual(match.call_count, len(self.bank)*15)
        self.assertEqual(events, ['before_match', 'before_ocr', 'ocr'])
        self.assertTrue(all(crop is crops[0] for crop in crops))
        self.assertTrue(result['hero_observation']['confident'])

    def test_invalid_layout_callback_receives_no_proof_and_byte_limit_is_preserved(self):
        from hero_recognition import recognize_frame
        from synthetic_vision import encoded
        payloads = [encoded(Image.new('RGB', (1280, 720), (0, 0, 0))),
                    encoded(Image.fromarray(self.rgb))+b'\0'*(16*1024*1024)]
        class OCR:
            def recognize(inner, *args):
                return {'ocr_lines': [], 'candidates': []}
        for payload in payloads:
            seen = []
            result = recognize_frame(payload, (.15, .25, .7, .35), OCR(), (), self.matcher,
                                     before_match=lambda signature, crop: seen.append(signature))
            self.assertEqual(seen, [None])
            self.assertEqual(result['hero_observation'], self.matcher.recognize(payload))


if __name__ == '__main__':
    unittest.main()
