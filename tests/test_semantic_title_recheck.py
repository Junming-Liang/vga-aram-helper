"""Owned Qt/window lifecycle evidence for fresh semantic title rechecks.

Synthetic pixels and explicit presentation geometry only. These tests verify
real Qt visibility/events and painted/accessibility data, not Windows DWM.
"""
import copy
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_native_capture_worker as fixture


@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime is not installed')
class SemanticTitleRecheckTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = fixture.NativeCaptureWorkerTests.setUp
    wait = fixture.NativeCaptureWorkerTests.wait
    dispose_window = fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture = fixture.NativeCaptureWorkerTests.accepted_proof_fixture

    def scene(self):
        from PIL import Image, ImageDraw
        from synthetic_vision import encoded
        from card_title_proof import make_title_proof
        from native_ui import ControlWindow
        w = self.window
        for spin, value in zip(w.roi, (0, 0, 100, 100)):
            spin.blockSignals(True); spin.setValue(value); spin.blockSignals(False)
        value, hero, names = self.accepted_proof_fixture()
        candidates = [dict(name=name, recognized_text=name, match_method='exact',
            ocr_confidence=.99, box=[[90+i*270,240],[180+i*270,240],
                                    [180+i*270,270],[90+i*270,270]])
            for i, name in enumerate(names)]
        size = dict(width=900, height=600)
        geometry = SimpleNamespace(rects=w.overlay._badge_anchors.rects,
            size=(900,600), space='frame', matches=lambda *a, **k: True)
        image = Image.new('RGB', (900,600), (20,40,60))
        draw = ImageDraw.Draw(image)
        for item in candidates:
            box = item['box']; draw.rectangle((*box[0], *box[2]), fill='white')
        proof = make_title_proof(encoded(image), candidates, size)
        self.assertIsNotNone(proof)
        animated = image.copy(); animated.putpixel((30,245),(200,30,40))
        self.assertFalse(proof.matches(encoded(animated)))
        reference = w._accepted_frame
        reference['title_proof'] = proof; reference['card_geometry'] = geometry
        value.update(_matchingTitleProof=None, _matchingCardGeometry=geometry,
                     _roiDigest='different-pixels', _cardGeometry=geometry,
                     automatic_candidates=candidates, candidates=candidates,
                     image_size=size, ocr_reused=False)
        w.ocr_busy=True; w.capture_pending=True; w._visible_previous=True
        w._active_capture_generation=w.state.generation
        w.overlay.show_at(value['_captureRect'], w.target); self.app.processEvents()
        w.captured_frame_current=lambda v: ControlWindow.captured_frame_current(w,v)
        w.check_target=lambda: ControlWindow.check_target(w)
        w.overlay.set_rechecking(True)
        return value, hero, names

    def phase(self, kind, value):
        self.window.task_result(kind,value,self.window.state.generation)
        self.app.processEvents()

    def assert_neutral(self):
        w=self.window
        self.assertTrue(w.overlay._titles_pending)
        for badge in w.overlay._badge_widgets:
            self.assertEqual((badge.tier,badge.hint,badge.display_hint,badge.identity_provenance), ('','','',''))
            self.assertEqual(badge.accent,'#C1C8D2')
            self.assertEqual(badge.toolTip(),'正在核对当前候选')
            self.assertEqual(badge.accessibleDescription(),'')
            self.assertNotIn('T1',badge.accessibleName())
        self.assertEqual(w.hero_title.text(),'等待识别')
        self.assertTrue(all(v['tier'].text()=='—' for v in w.candidate_views))
        self.assertEqual(w.card_details.text(),'正在核对当前候选，确认后显示资料。')

    def test_animated_title_band_same_semantics_never_hides_or_neutralizes(self):
        value, hero, names=self.scene(); w=self.window
        before=(w.last_observation,w.state.generation,w.state.automatic_frames,w.state.hero_stable_frames,w.state.stable_frames)
        hwnd=int(w.overlay.winId());mask=w.overlay.mask();key=w.overlay._placed_key
        hidden=[]
        class Events(fixture.QtCore.QObject):
            def eventFilter(inner,obj,event):
                if event.type()==fixture.QtCore.QEvent.Type.Hide:hidden.append(True)
                return False
        events=Events();w.overlay.installEventFilter(events)
        with patch.object(w.overlay,'set_title_checking',wraps=w.overlay.set_title_checking) as checking:
            self.phase('capture-proof',value)
            self.assertTrue(w.overlay.isVisible());self.assertFalse(w.overlay._titles_pending)
            self.phase('title-proof',value)
            # The slower HUD phase must not undo already-available semantic proof.
            self.phase('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))
            self.assertNotIn(True,[call.args[0] for call in checking.call_args_list])
            self.assertEqual(before,(w.last_observation,w.state.generation,w.state.automatic_frames,w.state.hero_stable_frames,w.state.stable_frames))
            self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertTrue(w.state.confirmed);self.assertEqual(w.state.offered,names)
        self.assertEqual(w.last_observation,value['_capturedAt'])
        self.assertEqual(w.state.automatic_frames,before[2]+1)
        self.assertTrue(w.overlay.isVisible());self.assertFalse(w.overlay._titles_pending)
        self.assertEqual(int(w.overlay.winId()),hwnd);self.assertEqual(w.overlay.mask(),mask)
        self.assertEqual(w.overlay._placed_key,key);self.assertEqual(hidden,[])

    def test_one_character_reroll_revokes_before_hud_and_late_positive_cannot_restore(self):
        value,hero,names=self.scene();w=self.window;generation=w.state.generation
        changed=copy.deepcopy(value['automatic_candidates']);changed[1]['name']+='甲';changed[1]['recognized_text']=changed[1]['name']
        self.phase('capture-proof',value)
        self.phase('title-proof',dict(value,automatic_candidates=changed))
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible());self.assert_neutral()
        self.assertEqual(w.state.generation,generation)
        self.phase('title-proof',value)
        self.phase('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertFalse(w.overlay.isVisible());self.assertIsNone(w._accepted_frame)

    def test_absent_low_confidence_reordered_and_unproven_geometry_revoke(self):
        value,hero,names=self.scene();w=self.window
        low=copy.deepcopy(value['automatic_candidates']);low[0]['ocr_confidence']=.92
        reordered=copy.deepcopy(value['automatic_candidates']);reordered[0]['name'],reordered[1]['name']=reordered[1]['name'],reordered[0]['name']
        reordered[0]['recognized_text']=reordered[0]['name'];reordered[1]['recognized_text']=reordered[1]['name']
        for changes in (dict(automatic_candidates=[]),dict(automatic_candidates=low),
                        dict(automatic_candidates=reordered),dict(_cardGeometry=None),dict(ocr_reused=True)):
            with self.subTest(changes=changes.keys()):
                value,hero,names=self.scene()
                self.phase('title-proof',dict(value,**changes))
                self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed);self.assert_neutral()

    def test_every_changed_reference_scope_immediately_revokes_historical_display(self):
        for index in range(7):
            with self.subTest(index=index):
                value,_,_=self.scene();w=self.window
                scope=list(value['_frameScope']);scope[index]='changed scope'
                self.phase('capture-proof',dict(value,_frameScope=tuple(scope)))
                self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed)

    def test_raw_pixel_changes_and_positive_phases_never_extend_original_deadline(self):
        value,hero,_=self.scene();w=self.window;old=w.last_observation
        self.phase('capture-proof',value);self.phase('title-proof',value)
        self.assertEqual(w.last_observation,old);self.assertEqual(w._accepted_frame['observed_at'],old)
        with patch('native_ui.time.monotonic',return_value=old+4.001):w.check_target()
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed)
        self.phase('title-proof',value)
        self.assertFalse(w.overlay.isVisible())

    def test_stale_generation_serial_and_post_final_callbacks_cannot_mutate_window(self):
        value,hero,_=self.scene();w=self.window
        negative=dict(value,automatic_candidates=[])
        for kind in ('capture-proof','title-proof','ocr'):
            w.task_result(kind,dict(negative,_captureSerial=w._capture_serial-1),w.state.generation)
            w.task_result(kind,negative,w.state.generation-1)
        self.assertTrue(w.overlay.isVisible());self.assertTrue(w.state.confirmed)
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        count=w.state.automatic_frames
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertEqual(w.state.automatic_frames,count)
        self.phase('title-proof',negative)
        self.phase('capture-proof',dict(value,_matchingCardGeometry=None))
        self.assertTrue(w.overlay.isVisible());self.assertTrue(w.state.confirmed)

    def test_hero_conflict_precedes_same_capture_positive_semantics(self):
        value,hero,_=self.scene();w=self.window
        self.phase('capture-proof',dict(value,hero_observation=dict(hero='different hero',confident=True)))
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.hero)
        self.phase('title-proof',value)
        self.phase('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed)

    def test_unknown_hero_without_valid_carry_revokes_before_positive_titles(self):
        value,hero,_=self.scene();w=self.window
        self.phase('capture-proof',dict(value,hero_observation=dict(confident=False,method='own-hud-portrait')))
        self.phase('title-proof',value)
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed)

    def test_neutral_refresh_and_placement_cannot_restore_old_accessible_grade(self):
        value,_,_=self.scene();w=self.window
        w.overlay.set_title_checking(True);w.refresh_card_details()
        hwnd=int(w.overlay.winId());mask=w.overlay.mask();key=w.overlay._placed_key
        for state in (False,True,False):
            w.overlay.set_rechecking(state);w.check_target();self.app.processEvents()
            self.assert_neutral();self.assertTrue(w.overlay.isVisible())
        self.assertEqual(int(w.overlay.winId()),hwnd);self.assertEqual(w.overlay.mask(),mask);self.assertEqual(w.overlay._placed_key,key)

    def test_geometry_revocation_needs_two_new_observations_not_old_title_counts(self):
        value,hero,_=self.scene();w=self.window
        w.state.automatic_frames=5;w.state.stable_frames=5
        self.phase('title-proof',dict(value,_cardGeometry=None))
        self.assertEqual((w.state.automatic_frames,w.state.stable_frames),(0,0))
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        self.assertEqual((w.state.automatic_frames,w.state.stable_frames),(1,1))

    def test_partial_and_manual_without_full_frame_authority_use_strict_hidden_route(self):
        for manual in (False,True):
            with self.subTest(manual=manual):
                value,_,names=self.scene();w=self.window
                w._accepted_frame=None;w.ocr_busy=False;w.capture_pending=False
                w.capture.can_request_visible_overlay=True
                w.capture.visible_capture_status='eligible'
                calls=[];w.capture.prepare_capture_mode=lambda visible:calls.append(visible) or True
                w.state.confirmed=manual;w.state.confirmation_mode='manual' if manual else 'automatic'
                if not manual:w.current_partial_names=lambda now=None:(names[0],None,names[2])
                with patch('native_ui.QtCore.QTimer.singleShot'):
                    w.capture_tick()
                self.assertEqual(calls,[False]);self.assertFalse(w.overlay.isVisible())
                self.assertFalse(w._visible_previous)


if __name__=='__main__':unittest.main()
