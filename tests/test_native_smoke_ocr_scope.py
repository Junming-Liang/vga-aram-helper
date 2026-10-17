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
from tests import test_animated_augment_rounds as rounds


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

    def test_manual_matcher_scope_mismatch_reproduces_failure_and_current_scope_restores(self):
        from native_smoke import _dispatch_owned_ocr
        value,hero,names=semantic_fixture.SemanticTitleRecheckTests.scene(self);w=self.window
        manual=next(name for name in w.data['heroes'] if name!=hero)
        w.hero_box.setCurrentText(manual)
        for edit,name in zip(w.inputs,names):edit.setText(name)
        w.confirm();self.assertTrue(w.state.confirmed);self.assertFalse(w.hero_auto.isChecked())
        self.assertEqual(w.state.hero,manual)
        # Exact old smoke behavior: current serial/time, but automatic matcher
        # scope is attached even though the actual UI is now in manual mode.
        w._capture_serial+=1
        wrong=dict(value,_captureSerial=w._capture_serial,_capturedAt=time.monotonic())
        w.task_result('ocr',wrong,w.state.generation)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        self.assertIn('范围变化',w.state.reason)
        w.confirm()
        current=_dispatch_owned_ocr(w,w.target,value,value['_captureRect'],time.monotonic(),value['_frameScope'][3])
        self.assertEqual(current['_frameScope'][6],(None,None))
        self.assertEqual(w._completed_capture_serial,current['_captureSerial'])
        self.assertTrue(w.state.confirmed);self.assertTrue(w.overlay.isVisible())
        self.assertEqual(w.state.hero,manual)
        self.assertEqual([card['sourceTier'] for card in w.overlay.cards],['T3','T1','T2'])


@unittest.skipUnless(rounds.QtWidgets is not None and rounds.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class NativeSmokeLifecycleSequenceTests(unittest.TestCase):
    setUpClass=classmethod(rounds.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp=rounds.AnimatedAugmentRoundTests.setUp
    wait=rounds.AnimatedAugmentRoundTests.wait
    dispose_window=rounds.AnimatedAugmentRoundTests.dispose_window
    record_result=rounds.AnimatedAugmentRoundTests.record_result
    record_error=rounds.AnimatedAugmentRoundTests.record_error

    def observe_current(self,key='9001',*,allow_reuse=True,**overrides):
        from native_smoke import _recognize_owned_ocr,_dispatch_owned_ocr
        from synthetic_vision import encoded,frame
        w=self.window;w.overlay.hide();self.now+=.3
        cards=self.scene.image((0,1,2),0)
        image=frame(self.scene.bank[key]);image.paste(cards.crop((0,0,1280,576)),(0,0))
        roi=tuple(spin.value()/100 for spin in w.roi)
        value=_recognize_owned_ocr(w,w.target,encoded(image),w.ocr,roi,allow_reuse=allow_reuse)
        result=_dispatch_owned_ocr(w,w.target,value,self.rect,self.now,roi,**overrides)
        self.assertEqual(w._completed_capture_serial,result['_captureSerial'])
        self.assertEqual(result['_capturedAt'],self.now)
        self.assertEqual(result['_frameScope'][3],roi)
        matcher=w.hero_matcher if w.hero_auto.isChecked() else None
        self.assertEqual(result['_frameScope'][6],(matcher,matcher.proof_identity() if matcher else None))
        self.app.processEvents()
        return result

    def assert_full(self,hero,tiers):
        w=self.window
        self.assertTrue(w.state.confirmed,w.state.reason);self.assertEqual(w.state.hero,hero)
        self.assertTrue(w.overlay.isVisible(),w.state.reason)
        self.assertEqual(w.state.offered,rounds.NAMES[:3])
        self.assertEqual([card['sourceTier'] for card in w.overlay.cards],tiers)

    def test_complete_handler_lifecycle_with_real_ocr_and_current_scopes(self):
        w=self.window;hero=rounds.HERO;other='磐石守卫（演示）';names=rounds.NAMES[:3]
        self.observe_current();self.assertFalse(w.state.confirmed)
        self.observe_current();self.assert_full(hero,['T1','T2','T3'])
        independent=w.state.automatic_frames
        reused=self.observe_current();self.assertTrue(reused['ocr_reused'])
        self.assertEqual(w.state.automatic_frames,independent)
        middle=w.data['augments'].pop(names[1]);w.ocr_reuse.clear()
        self.observe_current();self.observe_current()
        self.assertFalse(w.state.confirmed);self.assertTrue(w.overlay.isVisible())
        self.assertEqual(w.current_partial_names(),(names[0],'',names[2]))
        self.assertEqual(len(w.overlay._badge_regions),2)
        self.assertEqual(w.overlay._badge_widgets[1].tier,'')
        w.data['augments'][names[1]]=middle;w.ocr_reuse.clear()
        self.observe_current();self.observe_current();self.assert_full(hero,['T1','T2','T3'])
        self.observe_current(hero_observation=dict(hero=None,confident=False,reason='Synthetic unknown portrait'))
        self.assertFalse(w.state.confirmed);self.assertEqual(w.state.hero,'');self.assertFalse(w.overlay.isVisible())
        self.observe_current();self.observe_current();self.assert_full(hero,['T1','T2','T3'])
        for key,expected,tiers in (('9002',other,['T3','T1','T2']),('9001',hero,['T1','T2','T3'])):
            first=self.observe_current(key)
            self.assertFalse(w.state.confirmed);self.assertEqual(w.state.hero,'');self.assertFalse(w.overlay.isVisible())
            independent=0 if first['ocr_reused'] else 1
            self.assertEqual(w.state.automatic_frames,independent)
            for count in range(independent+1,3):
                fresh=self.observe_current(key);self.assertFalse(fresh['ocr_reused'])
                self.assertEqual(w.state.automatic_frames,count)
                self.assertEqual(w.state.confirmed,count==2)
            self.assert_full(expected,tiers)
        # The real hero-box signal switches to manual mode. No portrait
        # matcher may run or appear in the scope of these later observations.
        w.hero_box.setCurrentText(other);self.assertFalse(w.hero_auto.isChecked())
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        with patch.object(w.hero_matcher,'recognize',side_effect=AssertionError('Manual frame ran the portrait matcher')):
            w.confirm();fresh=self.observe_current(allow_reuse=False);self.assertFalse(fresh['ocr_reused'])
            self.assert_full(other,['T3','T1','T2'])
            tier_row=w.data['heroAugmentStats'][other][0];saved=tier_row['tier']
            for missing in (None,'UNKNOWN'):
                tier_row['tier']=missing;w.confirm();self.observe_current()
                self.assert_full(other,['T3',None,'T2'])
                self.assertEqual(w.overlay._badge_widgets[1].tier,'暂无评级')
                self.assertIn('暂无评级',w.overlay._badge_widgets[1].accessibleName())
            tier_row['tier']=saved
            w.hero_box.setCurrentText(hero);w.confirm();self.observe_current()
            self.assert_full(hero,['T1','T2','T3'])
        # The final scene-loss fixture now carries current serial/ROI/source,
        # reaches the production handler, and cannot retain partial evidence.
        # Native duty testing returns to a freshly confirmed automatic scene
        # before this last lifecycle branch, so reproduce that mode boundary.
        w.hero_auto.setChecked(True)
        self.observe_current();self.observe_current();self.assert_full(hero,['T1','T2','T3'])
        missing=self.observe_current(candidates_missing=True)
        self.assertEqual(missing['automatic_candidates'],[])
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w.current_partial_names(),('','',''))
        w.hero_box.setCurrentText(other);w.confirm();self.observe_current()
        self.assert_full(other,['T3','T1','T2'])
        self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
