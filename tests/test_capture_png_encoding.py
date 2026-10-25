"""Lossless capture transport parity, not Windows/game capture evidence."""
import io
import unittest
from unittest.mock import patch

try:
    from PIL import Image
    import numpy as np
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Optional Pillow/numpy runtime is not installed')
class CapturePNGEncodingTests(unittest.TestCase):
    def test_lossless_deterministic_rgb_transport_at_multiple_sizes(self):
        from screen_capture import encode_capture_png
        # Owned patterned pixels, including exact one-channel differences.
        for width, height in ((640, 360), (1280, 720), (1920, 1080), (3440, 1440)):
            with self.subTest(size=(width, height)):
                y, x = np.indices((height, width), dtype=np.uint16)
                pixels = np.stack(((x + y) % 256, (x * 3) % 256,
                                   (y * 5 + x % 17) % 256), axis=2).astype(np.uint8)
                image = Image.fromarray(pixels)
                encoded = encode_capture_png(image)
                self.assertEqual(encoded, encode_capture_png(image))
                with Image.open(io.BytesIO(encoded)) as decoded:
                    self.assertEqual(decoded.format, 'PNG')
                    self.assertEqual(decoded.size, (width, height))
                    np.testing.assert_array_equal(np.asarray(decoded), pixels)
                changed = pixels.copy(); changed[-1, -1, 2] ^= 1
                self.assertNotEqual(encoded, encode_capture_png(Image.fromarray(changed)))

    def test_fast_path_uses_level_one_once(self):
        from screen_capture import encode_capture_png
        image = Image.new('RGB', (64, 64), (17, 32, 66))
        with patch.object(image, 'save', wraps=image.save) as save:
            encode_capture_png(image)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(save.call_args.kwargs, {'format': 'PNG', 'compress_level': 1})

    def test_oversized_fast_encoding_falls_back_to_exact_old_encoder(self):
        from screen_capture import encode_capture_png
        image = Image.new('RGB', (128, 128), (17, 32, 66))
        expected = io.BytesIO(); image.save(expected, format='PNG')
        fast = io.BytesIO(); image.save(fast, format='PNG', compress_level=1)
        self.assertLess(len(expected.getvalue()), len(fast.getvalue()))
        # Exercise the same size decision without allocating a 16 MiB fixture.
        with patch('screen_capture._FAST_CAPTURE_PNG_LIMIT', len(expected.getvalue())), \
                patch.object(image, 'save', wraps=image.save) as save:
            actual = encode_capture_png(image)
        self.assertEqual(actual, expected.getvalue())
        self.assertEqual([call.kwargs['compress_level'] for call in save.call_args_list], [1, 6])

    def test_encoding_failure_is_not_hidden_or_retried_as_capture(self):
        from screen_capture import encode_capture_png
        image = Image.new('RGB', (64, 64))
        with patch.object(image, 'save', side_effect=OSError('owned failure')) as save:
            with self.assertRaises(OSError): encode_capture_png(image)
        self.assertEqual(save.call_count, 1)


if __name__ == '__main__':
    unittest.main()
