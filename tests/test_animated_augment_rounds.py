"""Actual local OCR through the Qt worker/handler on original synthetic pixels.

No Windows capture, borderless-game, live gameplay, or flicker claim is made.
The capture source is an owned in-memory fixture. LocalOCR, recognize_frame,
portrait matching, the OCR cache, and Qt result handlers are production code.
The controlled clock tests observation age, not a CPU performance target.
The first three cards use fixtures/auto-scene.png. The fourth is original test
artwork for the existing demo title 旧日回声, generated offline by the adjacent
tests/fixtures script. Tests load its PNG without requiring an installed font.
Moving shapes deliberately change pixels away from title glyphs.

Run with the optional Qt/OCR dependencies installed:
    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests \
        -p test_animated_augment_rounds.py -v
"""
import gc
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None

from local_ocr import LocalOCR

OCR_AVAILABLE = all(importlib.util.find_spec(name) is not None
                    for name in ('PIL', 'numpy', 'cv2', 'rapidocr', 'onnxruntime'))
NAMES = ('星火共鸣', '晶盾回路', '风步微光', '旧日回声')
TIERS = dict(zip(NAMES, ('T1', 'T2', 'T3', None)))
HERO = '星火术士（演示）'
ROI_BOX = (192, 180, 1088, 432)
HUD_BOX = (381, 619, 554, 716)
CARD_X = (196, 498, 800)


class AnimatedOriginalScene:
    def __init__(self):
        from PIL import Image
        from synthetic_vision import portraits
        self.bank = portraits()
        with Image.open(ROOT / 'fixtures/auto-scene.png') as source:
            self.original = source.convert('RGB')
        self.cards = [self.original.crop((x, 176, x + 268, 501))
                      for x in CARD_X]
        with Image.open(ROOT / 'tests/fixtures/animated-augment-new-title.png') as new_title:
            self.cards.append(new_title.convert('RGB'))

    def image(self, order=(0, 1, 2), phase=0, *, gray=False, side=False,
              title_offsets=(0, 0, 0)):
        from PIL import ImageDraw
        from synthetic_vision import frame
        image = frame(self.bank['9001'], gray=gray, side=side)
        if order is not None:
            image.paste(self.original.crop((0, 0, 1280, 576)), (0, 0))
            for slot, source in enumerate(order):
                card = self.cards[source].copy()
                if title_offsets[slot]:
                    # Move the original glyph pixels, never render new text.
                    title = card.crop((35, 110, 235, 180))
                    ImageDraw.Draw(card).rectangle((35, 110, 234, 179),
                                                   fill=card.getpixel((20, 110)))
                    card.paste(title, (35, 110 + title_offsets[slot]))
                image.paste(card, (CARD_X[slot], 176))
        draw = ImageDraw.Draw(image)
        # Inside the OCR crop, below every unshifted title. Keep title/HUD
        # pixels unchanged while making exact-ROI reuse impossible.
        x = 215 + (phase * 19) % 210
        draw.ellipse((x, 370, x + 12, 382), fill=(95, 147, 170))
        # Outside the OCR crop and the own-HUD search band.
        x = 80 + (phase * 37) % 1000
        draw.rectangle((x, 535, x + 22, 550), fill=(190, 123, 69))
        return image


class ObservedLocalOCR(LocalOCR):
    """Instrumentation delegates every inference unchanged to real LocalOCR."""
    def __init__(self):
        super().__init__()
        self.records = []
        self.next_gate = None

    def recognize(self, image_bytes, vocabulary):
        gate, self.next_gate = self.next_gate, None
        result = super().recognize(image_bytes, vocabulary)
        self.records.append({'digest': hashlib.sha256(image_bytes).hexdigest(),
                             'thread': threading.get_ident(), 'result': result})
        if gate:
            gate[0].set()
            if not gate[1].wait(10):
                raise RuntimeError('Owned inference-tail gate was not released')
        return result


@unittest.skipUnless(QtWidgets is not None and OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class AnimatedAugmentRoundTests(unittest.TestCase):
    # A standalone TestCase deliberately does not inherit the existing Qt
    # capture test class, so discovery never runs its inherited tests twice.
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.scene = AnimatedOriginalScene()

    def wait(self, predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Qt pipeline did not finish: ' + repr(self.errors))

    def setUp(self):
        from engine import load_data
        from hero_recognition import PortraitMatcher
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable, ClientRect, WindowInfo
        from synthetic_vision import configure_data
        self.errors = []
        self.results = []
        self.releases = []
        self.now = 100.
        self.main_thread = threading.get_ident()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # Replace this module's clock only; threading/Qt/real OCR retain their
        # actual clocks, and waiting for real model inference has a real timeout.
        clock = patch('native_ui.time', SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        with patch('native_ui.Win32Capture',
                   side_effect=CaptureUnavailable('Owned offscreen pixel source')):
            self.window = ControlWindow(
                lambda: {'data': load_data(ROOT / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='synthetic-test', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose_window)
        w = self.window
        self.wait(lambda: w.data is not None)
        configure_data(w.data)
        # Test-only short alias for the fourth existing demo item. Its absence
        # from the hero's tier table must continue to display as unrated.
        w.data['augments'][NAMES[3]] = dict(w.data['augments']['旧日回声（演示）'])
        w.watchdog.stop()
        w.monitor.stop()
        w.schedule_capture = lambda delay=None: None  # Exact test-owned cadence.
        w.queue_discovery = lambda *args, **kwargs: None
        w.target_allowed = lambda: True  # The fixture owns its synthetic target.
        w.capture_metadata = lambda: None
        w.target = WindowInfo(123, 456, 'Original synthetic rounds', 'OwnedClass')
        w.state.start(w.target.identity)
        w.hero_matcher = PortraitMatcher(self.scene.bank, w.data['heroes'])
        w.ocr = ObservedLocalOCR()
        w.ocr_reuse.clock = lambda: self.now
        self.rect = ClientRect(0, 0, 1280, 720)
        test = self

        class OwnedCapture:
            def __init__(self):
                self.payload = None
                self.calls = []

            def capture(inner, target, roi, **kwargs):
                inner.calls.append((hashlib.sha256(inner.payload).hexdigest(),
                                    threading.get_ident()))
                return inner.payload, test.rect

            def rect(inner, target):
                return test.rect

            def foreground(inner, target):
                return True

        w.capture = OwnedCapture()
        w.signals.result.connect(self.record_result)
        w.signals.error.connect(self.record_error)
        # Keep real check_target and captured_frame_current: identity, geometry,
        # freshness, hero/title guards and generation checks are exercised.
        w.check_target()

    def record_result(self, kind, value, generation):
        if kind == 'ocr':
            self.results.append(value)

    def record_error(self, kind, error, generation):
        self.errors.append((kind, error))

    def dispose_window(self):
        for event in self.releases:
            event.set()
        w = self.window
        if w is None:
            return
        w.capture = None
        w.close()
        self.wait(lambda: not w._workers)
        overlay = w.overlay
        overlay.deleteLater()
        w.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(overlay))
        self.assertFalse(isValid(w))
        self.window = None
        gc.collect()
        self.app.processEvents()

    def start_frame(self, order, phase, *, advance=.3, **options):
        from synthetic_vision import encoded
        self.now += advance
        self.window.capture.payload = encoded(self.scene.image(order, phase, **options))
        self.window.capture_tick()  # Real hide/settle/worker/callback/Qt handler.

    def finish_frame(self, previous):
        w = self.window
        self.wait(lambda: self.errors or len(self.results) > previous)
        self.assertEqual(self.errors, [])
        self.wait(lambda: not w.ocr_busy and not w.capture_pending and not w._workers)
        result = self.results[-1]
        self.assertEqual(result['_windowIdentity'], w.target.identity)
        self.assertEqual(result['_captureRect'], self.rect)
        self.assertEqual(result['_capturedAt'], w.last_observation)
        self.assertFalse(result['ocr_reused'])
        self.assertFalse(result['network_transmission'])
        self.assertFalse(result['image_saved'])
        self.assertFalse(w.manual_editing)
        self.assertTrue(w.hero_auto.isChecked())
        self.assertFalse(w.hero_box.isEnabled())
        return result

    def observe(self, order, phase, **options):
        previous = len(self.results)
        self.start_frame(order, phase, **options)
        return self.finish_frame(previous)

    def assert_confirmed(self, order):
        w = self.window
        names = tuple(NAMES[index] for index in order)
        self.assertTrue(w.state.confirmed, w.status.text())
        self.assertEqual(w.state.confirmation_mode, 'automatic')
        self.assertEqual(w.state.hero, HERO)
        self.assertEqual(w.state.offered, names)
        self.assertTrue(w.overlay.isVisible())
        self.assertEqual(tuple(card['name'] for card in w.overlay.cards), names)
        self.assertEqual(tuple(card['sourceTier'] for card in w.overlay.cards),
                         tuple(TIERS[name] for name in names))
        self.assertEqual(tuple(edit.text() for edit in w.inputs), names)
        actual = self.results[-1]['automatic_candidates']
        self.assertEqual(tuple(item['recognized_text'] for item in actual), names)
        self.assertTrue(all(item['match_method'] == 'exact' and item['ocr_confidence'] >= .93
                            for item in actual))

    def assert_unconfirmed(self):
        w = self.window
        self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.offered, ())
        self.assertFalse(w.overlay.isVisible())

    def test_three_animated_rounds_and_normal_reroll_without_assistant_edits(self):
        orders = ((0, 1, 2), (2, 0, 1), (1, 3, 0), (3, 0, 2))
        phase = 0
        for index, order in enumerate(orders):
            with self.subTest(stage=('round-1', 'normal-reroll', 'round-2', 'round-3')[index]):
                if index >= 2:
                    # No card selection is inferred; the fixture only observes
                    # a card-free interval and then new offers.
                    empty = self.observe(None, phase, advance=5.)
                    phase += 1
                    self.assertEqual(empty['automatic_candidates'], [])
                    self.assertEqual(empty['candidates'], [])
                    self.assert_unconfirmed()
                first = self.observe(order, phase)
                phase += 1
                self.assertEqual(tuple(item['name'] for item in first['automatic_candidates']),
                                 tuple(NAMES[i] for i in order))
                if index == 2:
                    self.assertNotIn(NAMES[3], tuple(NAMES[i] for i in orders[index - 1]))
                    self.assertIn(NAMES[3], tuple(item['recognized_text']
                                                for item in first['automatic_candidates']))
                self.assert_unconfirmed()
                self.assertEqual(self.window.state.automatic_frames, 1)
                self.observe(order, phase)
                phase += 1
                self.assert_confirmed(order)
                self.observe(order, phase)
                phase += 1
                self.assert_confirmed(order)
        w = self.window
        self.assertEqual(len(w.ocr.records), phase)
        self.assertEqual(len(w.capture.calls), phase)
        self.assertEqual(w.ocr_reuse.hits, 0)
        self.assertEqual(len({record['digest'] for record in w.ocr.records}), phase)
        self.assertTrue(all(record['thread'] != self.main_thread for record in w.ocr.records))
        self.assertTrue(all(thread != self.main_thread for _, thread in w.capture.calls))

    def test_expiring_display_does_not_cancel_actual_inflight_ocr_or_next_reroll(self):
        order = (0, 1, 2)
        self.observe(order, 0)
        self.observe(order, 1)
        self.assert_confirmed(order)
        w = self.window
        for phase, next_order, changed in ((2, order, False), (3, (2, 3, 1), True)):
            old_time, generation = w.last_observation, w.state.generation
            counts = (w.state.automatic_frames, w.state.hero_stable_frames)
            ready, release = threading.Event(), threading.Event()
            self.releases.append(release)
            w.ocr.next_gate = (ready, release)
            previous = len(self.results)
            self.start_frame(next_order, phase, advance=old_time + 2.7 - self.now)
            self.wait(ready.is_set)
            self.assertTrue(w.ocr_busy)
            self.now = old_time + 4.01
            w.check_target()
            self.assert_unconfirmed()
            self.assertEqual(w.state.hero, '')
            self.assertEqual(w.state.generation, generation)
            self.assertFalse(w._capture_cancel.is_set())
            self.assertEqual((w.state.automatic_frames, w.state.hero_stable_frames), counts)
            self.assertIsNone(w._accepted_frame)
            self.assertEqual(w.hero_title.text(), '等待识别')
            self.assertTrue(all(view['name'].text() == '等待识别' for view in w.candidate_views))
            self.now = old_time + 4.7
            release.set()
            result = self.finish_frame(previous)
            self.assertEqual(result['_capturedAt'], old_time + 2.7)
            if changed:
                self.assert_unconfirmed()
                self.assertEqual(w.state.automatic_frames, 1)
                second = self.observe(next_order, phase + 1)
                self.assertNotEqual(second['_roiDigest'], result['_roiDigest'])
                self.assertGreater(second['_capturedAt'], result['_capturedAt'])
            self.assert_confirmed(next_order)

    def test_real_title_geometry_and_own_hud_guards_still_reject_unsafe_frames(self):
        from native_state import automatic_candidates
        order = (0, 1, 2)
        cases = (
            ('misaligned-title', {'title_offsets': (0, 28, 0)}),
            ('outside-title-band', {'title_offsets': (88, 88, 88)}),
            ('gray-own-hud', {'gray': True}),
            ('sidebar-portrait-only', {'side': True}),
        )
        phase = 0
        for name, options in cases:
            with self.subTest(guard=name):
                self.observe(order, phase)
                self.observe(order, phase + 1)
                self.assert_confirmed(order)
                result = self.observe(order, phase + 2, **options)
                phase += 3
                self.assert_unconfirmed()
                self.assertEqual(tuple(item['name'] for item in result['candidates']), NAMES[:3])
                if name == 'misaligned-title':
                    self.assertEqual(len(result['automatic_candidates']), 3)
                    self.assertFalse(automatic_candidates(result['automatic_candidates'], result['image_size']))
                elif name == 'outside-title-band':
                    self.assertEqual(result['automatic_candidates'], [])
                else:
                    self.assertFalse(result['hero_observation']['confident'])
                    self.assertEqual(self.window.state.hero, '')

    def test_animation_changes_both_regions_without_changing_title_or_hud_pixels(self):
        from PIL import ImageChops
        first = self.scene.image(phase=0)
        second = self.scene.image(phase=1)
        self.assertIsNotNone(ImageChops.difference(first.crop(ROI_BOX), second.crop(ROI_BOX)).getbbox())
        self.assertIsNotNone(ImageChops.difference(first.crop((0, 500, 1280, 576)),
                                                second.crop((0, 500, 1280, 576))).getbbox())
        self.assertIsNone(ImageChops.difference(first.crop(HUD_BOX), second.crop(HUD_BOX)).getbbox())
        for x in CARD_X:
            glyph_box = (x + 35, 286, x + 235, 356)
            self.assertIsNone(ImageChops.difference(first.crop(glyph_box), second.crop(glyph_box)).getbbox())
        self.assertEqual(len({self.scene.image(order).tobytes() for order in
                              ((0, 1, 2), (2, 0, 1), (1, 2, 0))}), 3)


if __name__ == '__main__':
    unittest.main()
