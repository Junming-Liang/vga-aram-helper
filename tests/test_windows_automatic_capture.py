"""Portable fixture-image regressions; these do not claim Windows OS coverage."""
import io
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_automatic_capture import assert_pixels, make_original_png
from windows_session_fixture import validate_png


class AutomaticCaptureFixtureTests(unittest.TestCase):
    def test_actual_occluder_and_game_dimensions_produce_valid_nonblank_pngs(self):
        for dimensions in ((64, 64), (964, 602)):
            with self.subTest(dimensions=dimensions), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'owned-original.png'
                expected = make_original_png(path, dimensions)
                self.assertEqual(validate_png(path), path.resolve())
                with Image.open(io.BytesIO(path.read_bytes())) as decoded:
                    self.assertEqual(decoded.format, 'PNG')
                    self.assertEqual(decoded.size, dimensions)
                    self.assertEqual(decoded.convert('RGB').tobytes(), expected.tobytes())
                self.assertEqual(assert_pixels(path.read_bytes(), expected), 0)
                colors = {color for _, color in expected.getcolors(dimensions[0] * dimensions[1])}
                self.assertTrue({(229, 67, 81), (41, 194, 148), (74, 108, 239),
                                 (251, 197, 49), (239, 53, 184)} <= colors)

    def test_normal_game_fixture_pixels_remain_exactly_unchanged(self):
        # The old geometry is valid at the normal game size. Keep those pixels
        # identical while fixing only the minimum-size occluder's invalid inset.
        width, height = 964, 602
        reference = Image.new('RGB', (width, height), (21, 39, 63))
        draw = ImageDraw.Draw(reference)
        colors = [(229, 67, 81), (41, 194, 148), (74, 108, 239), (251, 197, 49)]
        for row in range(4):
            for column in range(6):
                x, y = column * width // 6, row * height // 4
                draw.rectangle((x + 5, y + 5, (column + 1) * width // 6 - 6,
                                (row + 1) * height // 4 - 6), fill=colors[(row + column) % 4])
        draw.rectangle((width // 4, height // 4, width // 4 + 70, height // 4 + 70), fill=(239, 53, 184))
        with tempfile.TemporaryDirectory() as directory:
            actual = make_original_png(Path(directory) / 'owned-original.png', (width, height))
            self.assertEqual(actual.tobytes(), reference.tobytes())


if __name__ == '__main__':
    unittest.main()
