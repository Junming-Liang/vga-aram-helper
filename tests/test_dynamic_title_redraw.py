"""Real offline OCR through Qt on animated original synthetic card sequences.

These check redisplay DURING independent OCR, not merely its final names.
No live game, Windows capture, compositor flicker or accuracy claim is made.
"""
import threading
import unittest
from unittest.mock import patch

from tests import test_animated_augment_rounds as fixture


@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class DynamicTitleRedrawTests(unittest.TestCase):
    setUpClass = classmethod(fixture.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp = fixture.AnimatedAugmentRoundTests.setUp
    wait = fixture.AnimatedAugmentRoundTests.wait
    dispose_window = fixture.AnimatedAugmentRoundTests.dispose_window
    record_result = fixture.AnimatedAugmentRoundTests.record_result
    record_error = fixture.AnimatedAugmentRoundTests.record_error
    start_frame = fixture.AnimatedAugmentRoundTests.start_frame
    finish_frame = fixture.AnimatedAugmentRoundTests.finish_frame
    observe = fixture.AnimatedAugmentRoundTests.observe
    assert_confirmed = fixture.AnimatedAugmentRoundTests.assert_confirmed

    def gated_frame(self, order, phase):
        ready, release = threading.Event(), threading.Event()
        self.releases.append(release)
        self.window.ocr.next_gate = ready, release
        previous = len(self.results)
        self.start_frame(order, phase)
        self.wait(lambda: ready.is_set() and not self.window.capture_pending)
        self.assertTrue(self.window.ocr_busy)
        return previous, release

    def test_moving_background_redraws_while_real_ocr_runs_and_reroll_hides(self):
        order = (0, 1, 2)
        self.observe(order, 0)
        self.observe(order, 1)
        self.assert_confirmed(order)
        w = self.window
        for phase in range(2, 6):
            prior_digest = self.results[-1]['_roiDigest']
            previous, release = self.gated_frame(order, phase)
            self.assertTrue(w._restore_while_ocr)
            self.assertTrue(w.overlay.isVisible())
            self.assertEqual(w.state.offered, fixture.NAMES[:3])
            release.set()
            current = self.finish_frame(previous)
            self.assertNotEqual(current['_roiDigest'], prior_digest)
            self.assert_confirmed(order)
        # A real rendered new title must never borrow the old badge during OCR.
        reroll = (0, 3, 2)
        previous, release = self.gated_frame(reroll, 6)
        self.assertFalse(w._restore_while_ocr)
        self.assertFalse(w.overlay.isVisible())
        release.set()
        self.finish_frame(previous)
        self.assertFalse(w.state.confirmed)
        self.observe(reroll, 7)
        self.assert_confirmed(reroll)
        self.assertEqual(w.ocr_reuse.hits, 0)
        self.assertEqual(len(w.ocr.records), 8)

    def test_local_title_proof_still_requires_exact_reference_scope_and_freshness(self):
        from copy import deepcopy
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        w = self.window
        proofs = []
        w.signals.result.connect(lambda kind, value, generation:
                                 proofs.append(value) if kind == 'capture-proof' else None)
        previous, release = self.gated_frame((0, 1, 2), 2)
        value = proofs[-1]
        self.assertTrue(w.may_restore_accepted_frame(value))
        # Structural equality is insufficient: provenance must bind to the
        # exact accepted immutable proof captured before the worker started.
        changed = dict(value, _matchingTitleProof=deepcopy(value['_matchingTitleProof']))
        self.assertFalse(w.may_restore_accepted_frame(changed))
        for index in range(7):
            scope = list(value['_frameScope'])
            scope[index] = 'different scene scope'
            self.assertFalse(w.may_restore_accepted_frame(dict(value, _frameScope=tuple(scope))))
        self.assertFalse(w.may_restore_accepted_frame(dict(value, _capturedAt=w.last_observation)))
        self.now += 4.01
        self.assertFalse(w.may_restore_accepted_frame(value))
        w.check_target()
        self.assertFalse(w.overlay.isVisible())
        release.set()
        self.wait(lambda: not w.ocr_busy and not w._workers)
        self.assertFalse(w.state.confirmed)
        self.assertFalse(w.overlay.isVisible())

    def test_card_free_frame_cannot_restore_old_badges_during_real_ocr(self):
        self.observe((0, 1, 2), 0)
        self.observe((0, 1, 2), 1)
        self.assert_confirmed((0, 1, 2))
        previous, release = self.gated_frame(None, 2)
        self.assertFalse(self.window._restore_while_ocr)
        self.assertFalse(self.window.overlay.isVisible())
        release.set()
        result = self.finish_frame(previous)
        self.assertEqual(result['automatic_candidates'], [])
        self.assertFalse(self.window.state.confirmed)
        self.assertFalse(self.window.overlay.isVisible())

    def test_visible_animated_title_band_keeps_grade_and_hwnd_through_fresh_real_ocr(self):
        from PySide6 import QtCore
        self.observe((0,1,2),0);self.observe((0,1,2),1)
        self.assert_confirmed((0,1,2));w=self.window
        w.capture.can_request_visible_overlay=True
        w.capture.visible_capture_status='eligible'
        w.capture.prepare_capture_mode=lambda visible:True
        hidden=[]
        class Events(QtCore.QObject):
            def eventFilter(inner,obj,event):
                if event.type()==QtCore.QEvent.Type.Hide:hidden.append(True)
                return False
        events=Events();w.overlay.installEventFilter(events)
        hwnd=int(w.overlay.winId());mask=w.overlay.mask();key=w.overlay._placed_key
        original=self.scene.image
        def animation(*args,**kwargs):
            image=original(*args,**kwargs)
            region=w._accepted_frame['title_proof'].regions[0]
            # Original synthetic non-glyph pixels inside the full-width band.
            x=fixture.ROI_BOX[0]+region[0]+10
            y=fixture.ROI_BOX[1]+(region[1]+region[3])//2
            image.putpixel((x,y),(241,17,30))
            return image
        with patch.object(self.scene,'image',side_effect=animation), \
                patch.object(w.overlay,'set_title_checking',wraps=w.overlay.set_title_checking) as neutral:
            old=w.last_observation;previous,release=self.gated_frame((0,1,2),2)
            self.assertTrue(w.overlay.isVisible());self.assertFalse(w.overlay._titles_pending)
            self.assertEqual(w.last_observation,old)
            release.set();result=self.finish_frame(previous)
            self.assertIsNone(result['_matchingTitleProof'])
            self.assert_confirmed((0,1,2))
            self.assertNotIn(True,[call.args[0] for call in neutral.call_args_list])
        self.assertEqual(hidden,[]);self.assertEqual(int(w.overlay.winId()),hwnd)
        self.assertEqual(w.overlay.mask(),mask);self.assertEqual(w.overlay._placed_key,key)
