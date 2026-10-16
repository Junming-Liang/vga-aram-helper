"""Fresh-HUD phase callback ordering; no Windows/capture timing claims."""
import io
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Optional Pillow runtime is not installed')
class RecognizeFrameCallbackTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (1280, 720), (26, 43, 67))
        output = io.BytesIO()
        self.image.save(output, format='PNG')
        self.payload = output.getvalue()
        self.roi = (.15, .25, .7, .35)
        self.vocabulary = ('Original title',)

    def test_callback_sees_fresh_hero_and_exact_ocr_bytes_before_inference(self):
        from hero_recognition import recognize_frame
        events, seen = [], {}
        hero = {'hero': 'Original hero', 'confident': True}
        class Matcher:
            def recognize(inner, image):
                self.assertIs(image, self.payload)
                events.append('hero')
                return hero
        class OCR:
            def recognize(inner, image, vocabulary):
                events.append('ocr')
                seen['ocr_bytes'] = image
                self.assertEqual(vocabulary, self.vocabulary)
                return {'ocr_lines': [], 'candidates': []}
        def before_ocr(observation, image):
            events.append('callback')
            self.assertIs(observation, hero)
            seen['callback_bytes'] = image
        actual = recognize_frame(self.payload, self.roi, OCR(), self.vocabulary,
                                 Matcher(), before_ocr=before_ocr)
        self.assertEqual(events, ['hero', 'callback', 'ocr'])
        self.assertIs(seen['callback_bytes'], seen['ocr_bytes'])
        self.assertIs(actual['hero_observation'], hero)
        from screen_capture import bounded_roi
        left, top, width, height = bounded_roi(1280, 720, self.roi)
        expected = io.BytesIO()
        self.image.crop((left, top, left+width, top+height)).save(expected, format='PNG')
        self.assertEqual(seen['callback_bytes'], expected.getvalue())
        baseline = recognize_frame(self.payload, self.roi, OCR(), self.vocabulary, Matcher())
        self.assertEqual(actual, baseline)

    def test_missing_matcher_reports_unknown_without_skipping_ocr(self):
        from hero_recognition import recognize_frame
        seen = []
        class OCR:
            def recognize(inner, *args):
                seen.append('ocr')
                return {'ocr_lines': [], 'candidates': []}
        def before_ocr(hero, image):
            self.assertFalse(hero['confident'])
            self.assertIsNone(hero['hero'])
            self.assertIsInstance(image, bytes)
            seen.append('callback')
        result = recognize_frame(self.payload, self.roi, OCR(), self.vocabulary,
                                 before_ocr=before_ocr)
        self.assertEqual(seen, ['callback', 'ocr'])
        self.assertFalse(result['hero_observation']['confident'])

    def test_callback_failure_does_not_continue_inference(self):
        from hero_recognition import recognize_frame
        class OCR:
            def recognize(inner, *args):
                self.fail('Inference must not continue after callback failure')
        def before_ocr(*args):
            raise RuntimeError('Owned phase failure')
        with self.assertRaisesRegex(RuntimeError, 'Owned phase failure'):
            recognize_frame(self.payload, self.roi, OCR(), self.vocabulary,
                            before_ocr=before_ocr)

    def test_resolver_runs_after_match_and_before_proof_and_result(self):
        from hero_recognition import recognize_frame
        events = []
        observed = {'hero': None, 'confident': False}
        resolved = {'hero': 'Owned resolved hero', 'confident': True}
        class Matcher:
            def recognize(inner, image):
                events.append('match')
                return observed
        class OCR:
            def recognize(inner, *args):
                events.append('ocr')
                return {'ocr_lines': [], 'candidates': []}
        def resolve(hero):
            self.assertIs(hero, observed)
            events.append('resolve')
            return resolved
        def proof(hero, crop):
            self.assertIs(hero, resolved)
            events.append('proof')
        result = recognize_frame(self.payload, self.roi, OCR(), self.vocabulary,
                                 Matcher(), resolve_hero=resolve, before_ocr=proof)
        self.assertEqual(events, ['match', 'resolve', 'proof', 'ocr'])
        self.assertIs(result['hero_observation'], resolved)


if __name__ == '__main__':
    unittest.main()
