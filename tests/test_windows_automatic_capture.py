"""Portable fixture-image regressions; these do not claim Windows OS coverage."""
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_automatic_capture import assert_pixels, make_original_png, make_hidden_capture_observer, force_first_copy_blank
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


class WorkerCaptureObserverTests(unittest.TestCase):
    def fixture(self):
        expected = Image.new('RGB', (64, 64), (229, 67, 81))
        stream = io.BytesIO(); expected.save(stream, format='PNG')
        result = (stream.getvalue(), object())
        capture = Mock(return_value=result)
        exists, visible = Mock(return_value=True), Mock(return_value=False)
        observed = []
        observer = make_hidden_capture_observer(capture, exists, visible, 123,
            expected, observed, threading.get_ident())
        return observer, capture, exists, visible, observed, result

    def call_worker(self, observer, *args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(observer, *args, **kwargs).result(timeout=3)

    def test_exact_cancellation_and_metadata_options_reach_real_capture(self):
        observer, capture, exists, visible, observed, result = self.fixture()
        target, roi, cancelled, metadata = object(), (0.,0.,1.,1.), threading.Event(), object()
        actual = self.call_worker(observer, target, roi, cancelled=cancelled, expected_metadata=metadata)
        self.assertIs(actual, result)
        capture.assert_called_once_with(target, roi, cancelled=cancelled, expected_metadata=metadata)
        exists.assert_called_once_with(123); visible.assert_called_once_with(123)
        self.assertEqual(observed, [True])

    def test_gui_thread_cannot_pass_the_worker_observation(self):
        observer, capture, *_ = self.fixture()
        with self.assertRaisesRegex(AssertionError, 'worker'):
            observer(object(), (0.,0.,1.,1.))
        capture.assert_not_called()

    def test_destroyed_or_visible_overlay_cannot_capture(self):
        for is_window, is_visible in ((False,False), (True,True)):
            observer, capture, exists, visible, observed, _ = self.fixture()
            exists.return_value = is_window; visible.return_value = is_visible
            with self.assertRaisesRegex(AssertionError, 'hidden overlay'):
                self.call_worker(observer, object(), (0.,0.,1.,1.))
            capture.assert_not_called(); self.assertFalse(observed)

    def test_capture_failures_propagate_without_success_evidence(self):
        observer, capture, _, _, observed, _ = self.fixture()
        capture.side_effect = RuntimeError('owned capture rejection')
        with self.assertRaisesRegex(RuntimeError, 'owned capture rejection'):
            self.call_worker(observer, object(), (0.,0.,1.,1.))
        self.assertFalse(observed)


    def test_wrong_pixels_still_fail(self):
        observer, capture, _, _, observed, _ = self.fixture()
        stream = io.BytesIO(); Image.new('RGB', (64,64), 'black').save(stream,format='PNG')
        capture.return_value = (stream.getvalue(), object())
        with self.assertRaisesRegex(AssertionError, 'did not match'):
            self.call_worker(observer, object(), (0.,0.,1.,1.))
        self.assertFalse(observed)


class LegacyGdiFixtureIsolationTests(unittest.TestCase):
    def fixture(self):
        events=[]
        class Capture:
            _persistent=object();_wgc=object();cleanup_pending=False
            def retire_session(self):events.append('retire')
            def _copy_pixels(self,*args):
                events.append('actual-copy');return Image.new('RGB',(64,64),'white')
        return Capture(),events

    def test_retirement_precedes_explicit_legacy_backend_and_restores_it(self):
        capture,events=self.fixture();persistent,one_shot=capture._persistent,capture._wgc
        with force_first_copy_blank(capture) as calls:
            self.assertEqual(events,['retire'])
            self.assertIsNone(capture._persistent);self.assertIsNone(capture._wgc)
            self.assertEqual(capture._copy_pixels(1,64,64,0,0).getpixel((0,0)),(0,0,0))
            self.assertEqual(capture._copy_pixels(1,64,64,0,0).getpixel((0,0)),(255,255,255))
            self.assertEqual(len(calls),2)
        self.assertIs(capture._persistent,persistent);self.assertIs(capture._wgc,one_shot)
        self.assertEqual(events,['retire','actual-copy'])

    def test_pending_session_cannot_be_bypassed_to_force_gdi(self):
        capture,events=self.fixture();capture.cleanup_pending=True;persistent=capture._persistent
        with patch('windows_automatic_capture.time.monotonic',side_effect=[0,4]):
            with self.assertRaisesRegex(RuntimeError,'cleanup'):
                with force_first_copy_blank(capture):self.fail('Unclosed session entered GDI fixture')
        self.assertIs(capture._persistent,persistent);self.assertEqual(events,['retire'])



if __name__ == '__main__':
    unittest.main()
