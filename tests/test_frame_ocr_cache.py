import threading
import unittest

from frame_ocr_cache import FrameOCRCache


class FakeOCR:
    def __init__(self):
        self.calls = 0

    def recognize(self, image, names):
        self.calls += 1
        return {'candidates': [{'name': names[0]}], 'ocr_lines': [],
                'image_size': {'width': 900, 'height': 400}}


class FrameOCRCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.cache = FrameOCRCache(clock=lambda: self.now)
        self.ocr = FakeOCR()
        self.scope = ((123, 7, 'GameWindow'), (.15, .25, .7, .35), 'game')

    def recognize(self, image=b'fresh-title-pixels', names=('甲', '乙', '丙'), scope=None):
        return self.cache.scoped(self.ocr, scope or self.scope, allow_reuse=True).recognize(image, names)

    def test_identical_fresh_crop_reuses_only_ocr_and_returns_owned_copy(self):
        first = self.recognize()
        first['candidates'][0]['name'] = 'caller-mutated'
        self.now += 1.3
        second = self.recognize()
        self.assertEqual(second['candidates'][0]['name'], '甲')
        self.assertFalse(first['ocr_reused'])
        self.assertTrue(second['ocr_reused'])
        second['_capturedAt'] = self.now
        self.assertNotIn('_capturedAt', self.recognize())
        self.assertEqual(self.ocr.calls, 1)
        self.assertEqual(self.cache.hits, 2)

    def test_any_byte_change_and_vocabulary_change_force_new_inference(self):
        self.recognize()
        self.recognize(b'fresh-title-pixelS')
        self.recognize(b'fresh-title-pixelS', names=('丁', '乙', '丙'))
        self.assertEqual(self.ocr.calls, 3)

    def test_default_requires_independent_inference_before_confirmation(self):
        for _ in range(2):
            result = self.cache.scoped(self.ocr, self.scope).recognize(b'image', ('甲',))
            self.assertFalse(result['ocr_reused'])
        self.assertEqual(self.ocr.calls, 2)

    def test_window_roi_phase_or_engine_change_force_new_inference(self):
        self.recognize()
        for scope in [((124, 7, 'GameWindow'), self.scope[1], 'game'),
                      (self.scope[0], (.15, .25, .6, .35), 'game'),
                      (self.scope[0], self.scope[1], 'client')]:
            self.recognize(scope=scope)
        other = FakeOCR()
        self.cache.scoped(other, self.scope).recognize(b'fresh-title-pixels', ('甲', '乙', '丙'))
        self.assertEqual(self.ocr.calls, 4)
        self.assertEqual(other.calls, 1)

    def test_ttl_is_not_extended_by_cache_hits(self):
        self.recognize()
        self.now += 1.3
        self.recognize()
        self.now += 1.3
        self.recognize()
        self.assertEqual(self.ocr.calls, 2)

    def test_clock_rollback_and_clear_force_new_inference(self):
        self.recognize()
        self.now -= 1
        self.recognize()
        self.cache.clear()
        self.recognize()
        self.assertEqual(self.ocr.calls, 3)

    def test_invalidated_worker_cannot_repopulate_or_read_new_scope(self):
        started, finish = threading.Event(), threading.Event()
        class SlowOCR(FakeOCR):
            def recognize(inner, image, names):
                started.set()
                self.assertTrue(finish.wait(2))
                return super().recognize(image, names)
        slow = SlowOCR()
        proxy = self.cache.scoped(slow, self.scope)
        worker = threading.Thread(target=lambda: proxy.recognize(b'image', ('甲',)))
        worker.start()
        self.assertTrue(started.wait(2))
        self.cache.clear()
        finish.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.cache._entry)
        proxy.recognize(b'image', ('甲',))
        self.assertIsNone(self.cache._entry)

    def test_failure_is_not_cached(self):
        class BrokenOCR:
            def recognize(inner, *args):
                raise RuntimeError('inference failed')
        with self.assertRaises(RuntimeError):
            self.cache.scoped(BrokenOCR(), self.scope).recognize(b'image', ('甲',))
        self.assertIsNone(self.cache._entry)

    def test_expiry_bounds_reject_invalid_configuration(self):
        for age in (0, -1, 4, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                FrameOCRCache(max_age=age)


if __name__ == '__main__':
    unittest.main()
