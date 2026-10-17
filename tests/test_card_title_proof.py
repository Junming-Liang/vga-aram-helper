"""Exact title-local pixel proof; synthetic pixels, no gameplay claim."""
import unittest
from PIL import Image, ImageDraw
from synthetic_vision import encoded
from card_title_proof import make_title_proof


class CardTitleProofTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (900, 300), (20, 40, 60))
        self.candidates = []
        draw = ImageDraw.Draw(self.image)
        for index, name in enumerate(('alpha', 'beta', 'gamma')):
            x = index * 300 + 100
            draw.rectangle((x, 100, x + 80, 120), fill='white')
            self.candidates.append(dict(name=name, recognized_text=name,
                match_method='exact', ocr_confidence=.99,
                box=[[x, 100], [x + 80, 100], [x + 80, 120], [x, 120]]))
        self.size = dict(width=900, height=300)
        self.proof = make_title_proof(encoded(self.image), self.candidates, self.size)
        self.assertIsNotNone(self.proof)

    def test_background_animation_does_not_need_static_crop(self):
        for phase in range(12):
            current = self.image.copy()
            ImageDraw.Draw(current).ellipse((phase * 30, 220, phase * 30 + 20, 240), fill='red')
            self.assertTrue(self.proof.matches(encoded(current)))

    def test_any_changed_title_pixel_in_each_slot_fails_closed(self):
        for slot in range(3):
            current = self.image.copy()
            current.putpixel((slot * 300 + 101, 101), (255, 0, 0))
            self.assertFalse(self.proof.matches(encoded(current)))

    def test_appended_glyph_outside_old_text_box_fails_closed(self):
        current = self.image.copy()
        ImageDraw.Draw(current).rectangle((210, 101, 225, 119), fill='white')
        self.assertFalse(self.proof.matches(encoded(current)))

    def test_blank_size_changed_and_malformed_capture_fail_closed(self):
        for current in (Image.new('RGB', self.image.size), self.image.resize((901, 300))):
            self.assertFalse(self.proof.matches(encoded(current)))
        self.assertFalse(self.proof.matches(b'not an image'))

    def test_untrusted_or_incomplete_title_geometry_cannot_seed_proof(self):
        self.assertIsNone(make_title_proof(encoded(self.image), self.candidates[:2], self.size))
        self.candidates[1]['ocr_confidence'] = .92
        self.assertIsNone(make_title_proof(encoded(self.image), self.candidates, self.size))
