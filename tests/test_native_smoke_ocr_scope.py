"""Owned Qt callback regression for native smoke's explicit identity negative.

No Windows capture claim: recognition values and geometry are synthetic. The
real production handler must reject the old smoke replay, and process the
freshly scoped fixture through the same dispatcher used on Windows.
"""
import time
import unittest
from unittest.mock import patch

from tests import test_native_capture_worker as fixture
from tests import test_semantic_title_recheck as semantic_fixture


@unittest.skipIf(fixture.QtWidgets is None,'Optional Qt runtime is not installed')
class NativeSmokeOcrScopeTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixture.NativeCaptureWorkerTests.setUp
    wait=fixture.NativeCaptureWorkerTests.wait
    dispose_window=fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture=fixture.NativeCaptureWorkerTests.accepted_proof_fixture

    def test_old_smoke_replay_is_rejected_but_new_unknown_observation_clears(self):
        from native_smoke import _dispatch_owned_ocr
        value,hero,names=semantic_fixture.SemanticTitleRecheckTests.scene(self)
        w=self.window;roi=value['_frameScope'][3];rect=value['_captureRect']
        raw=dict(value,hero_observation=dict(hero=hero,confident=True))
        old=_dispatch_owned_ocr(w,w.target,raw,rect,time.monotonic(),roi)
        # The lifecycle smoke subsequently removes/restores one catalog name
        # and delivers five more real captures before its unknown-hero case.
        middle=w.data['augments'].pop(names[1]);w.data['augments'][names[1]]=middle
        for _ in range(5):
            current=_dispatch_owned_ocr(w,w.target,raw,rect,time.monotonic(),roi)
        self.assertTrue(w.state.confirmed);self.assertTrue(w.overlay.isVisible())
        self.assertNotEqual(old['_captureSerial'],current['_captureSerial'])
        self.assertNotEqual(old['_frameScope'][4],current['_frameScope'][4])
        before=(w.state.hero,w.state.offered,w.last_observation,w._completed_capture_serial)
        unknown=dict(hero=None,confident=False,reason='Synthetic unknown portrait')
        replay=dict(old,hero_observation=unknown,_capturedAt=time.monotonic())
        with patch.object(w.debug_log,'record',wraps=w.debug_log.record) as record:
            w.task_result('ocr',replay,w.state.generation)
        self.assertTrue(any(call.kwargs.get('reason')=='serial_changed' for call in record.call_args_list))
        self.assertEqual((w.state.hero,w.state.offered,w.last_observation,w._completed_capture_serial),before)
        self.assertTrue(w.overlay.isVisible())
        # Merely relabeling the old callback with the last delivered serial
        # would still be a duplicate. The fixed fixture observes a new frame.
        w.task_result('ocr',dict(replay,_captureSerial=current['_captureSerial']),w.state.generation)
        self.assertTrue(w.state.confirmed);self.assertTrue(w.overlay.isVisible())
        captured_at=time.monotonic()-.01
        delivered=_dispatch_owned_ocr(w,w.target,raw,rect,captured_at,roi,hero_observation=unknown)
        self.assertEqual(delivered['_captureSerial'],current['_captureSerial']+1)
        self.assertEqual(delivered['_capturedAt'],captured_at)
        self.assertEqual(delivered['_frameScope'][4],tuple(w.data['augments']))
        self.assertEqual(w._completed_capture_serial,delivered['_captureSerial'])
        self.assertFalse(w.state.confirmed);self.assertEqual(w.state.hero,'')
        self.assertFalse(w.overlay.isVisible())
        self.assertEqual(raw['hero_observation'],dict(hero=hero,confident=True))

    def test_fresh_unknown_identity_also_revokes_an_exact_title_cache_hit(self):
        from native_smoke import _dispatch_owned_ocr
        value,hero,_=semantic_fixture.SemanticTitleRecheckTests.scene(self);w=self.window
        raw=dict(value,hero_observation=dict(hero=hero,confident=True),ocr_reused=True)
        unknown=dict(hero=None,confident=False,reason='Synthetic unknown portrait')
        delivered=_dispatch_owned_ocr(w,w.target,raw,value['_captureRect'],time.monotonic(),
                                     value['_frameScope'][3],hero_observation=unknown)
        self.assertTrue(delivered['ocr_reused'])
        self.assertFalse(w.state.confirmed);self.assertEqual(w.state.hero,'')
        self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w._completed_capture_serial,delivered['_captureSerial'])
        self.assertFalse(w.may_restore_accepted_frame(delivered))
        w.check_target();self.app.processEvents()
        self.assertFalse(w.overlay.isVisible())


if __name__=='__main__':unittest.main()
