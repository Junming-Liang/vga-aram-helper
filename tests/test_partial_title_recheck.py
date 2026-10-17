"""Synthetic active-capture phases for independently confirmed partial badges.

Real Qt visibility, accessibility and masks; no Windows capture claim. The
separate partial_candidates_qt suite runs unchanged original pixels through
actual local OCR and the production threaded inference path.
"""
import unittest
from unittest.mock import patch

from tests import test_semantic_title_recheck as full_fixture
from tests import test_native_capture_worker as fixture


@unittest.skipIf(fixture.QtWidgets is None,'Optional Qt runtime is not installed')
class PartialTitleRecheckTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixture.NativeCaptureWorkerTests.setUp
    wait=fixture.NativeCaptureWorkerTests.wait
    dispose_window=fixture.NativeCaptureWorkerTests.dispose_window
    accepted_proof_fixture=fixture.NativeCaptureWorkerTests.accepted_proof_fixture
    phase=full_fixture.SemanticTitleRecheckTests.phase

    def evidence(self,value,names,scores=(.99,.99,.99)):
        from partial_candidates import title_evidence
        rows=[dict(text=name,confidence=score,box=box)
              for name,score,box in zip(names,scores,self.boxes)]
        return title_evidence(rows,value['image_size'],self.window.data['augments'],crop_top=0,frame_height=600)

    def scene(self):
        from partial_candidates import PartialCandidateState
        value,hero,names=full_fixture.SemanticTitleRecheckTests.scene(self);w=self.window
        self.boxes=[item['box'] for item in value['automatic_candidates']]
        partial=self.evidence(value,(names[0],'未知强化',names[2]))
        self.assertTrue(partial.valid)
        w.clear_partial_candidates();w.partial_candidates=PartialCandidateState()
        w._partial_hero=hero;w._partial_scope=value['_frameScope']
        for serial,captured in ((1,w.last_observation-.1),(2,w.last_observation)):
            w.partial_candidates.observe(partial,frame_serial=serial,captured_at=captured,
                now=w.last_observation,context=(w._partial_revision,w._partial_scope,hero),
                guards_passed=True,ocr_reused=False)
        w.state.confirmed=False;w.state.offered=();w._completed_capture_serial=None
        w.state.observed=();w.state.stable_frames=0;w.state.automatic_observed=();w.state.automatic_frames=0
        value=dict(value,partial_title_evidence=partial,
                   automatic_candidates=[value['automatic_candidates'][i] for i in (0,2)])
        value['candidates']=value['automatic_candidates']
        w.overlay.set_candidate_geometry(value['automatic_candidates'],value['image_size'],value['_frameScope'][3],value['_cardGeometry'])
        w.show_partial_candidates();w._capture_serial=2
        w.remember_accepted_partial_frame(dict(value,_captureSerial=2,_capturedAt=w.last_observation,
                                                hero_observation=dict(hero=hero,confident=True)))
        self.assertIsNotNone(w._accepted_partial_frame)
        w._capture_serial=3;value['_captureSerial']=3
        w.overlay.show_at(value['_captureRect'],w.target)
        w._visible_previous=True;w.capture_pending=True;w.ocr_busy=True
        w.overlay.set_rechecking(True);self.app.processEvents()
        return value,hero,names

    def stamps(self):
        w=self.window;s=w.partial_candidates;r=w._accepted_partial_frame
        return (w.last_observation,s._last_serial,s._last_capture,s._last_ocr,
                r['observed_at'],r['serial'])

    def assert_slots(self,names):
        w=self.window
        self.assertEqual(w.current_partial_names(),names)
        self.assertEqual(len(w.overlay._badge_regions),sum(bool(n) for n in names))
        for i,name in enumerate(names):
            badge=w.overlay._badge_widgets[i]
            self.assertEqual(badge.isVisibleTo(w.overlay),bool(name))
            if not name:
                self.assertEqual((badge.tier,badge.hint,badge.display_hint,badge.identity_provenance),('','','',''))
                self.assertNotIn('T1',badge.accessibleName());self.assertNotIn('T2',badge.accessibleName())
                self.assertEqual(badge.accessibleDescription(),'')
                self.assertEqual(w.overlay.cards[i]['name'],'待识别')
                self.assertIsNone(w.overlay.cards[i]['sourceTier'])

    def test_same_partial_each_phase_keeps_window_mask_grades_and_original_authority(self):
        value,hero,names=self.scene();w=self.window
        wanted=(names[0],'',names[2]);before=self.stamps();counts=w.partial_candidates._counts
        hwnd=int(w.overlay.winId());mask=w.overlay.mask();key=w.overlay._placed_key;hidden=[]
        class Events(fixture.QtCore.QObject):
            def eventFilter(inner,obj,event):
                if event.type()==fixture.QtCore.QEvent.Type.Hide:hidden.append(True)
                return False
        events=Events();w.overlay.installEventFilter(events)
        with patch.object(w.overlay,'set_title_checking',wraps=w.overlay.set_title_checking) as checking:
            for kind,phase in (('capture-proof',value),('title-proof',value),
                               ('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))):
                self.phase(kind,phase)
                self.assertTrue(w.overlay.isVisible());self.assertFalse(w.overlay._titles_pending)
                self.assert_slots(wanted);self.assertEqual(self.stamps(),before)
                self.assertEqual(w.partial_candidates._counts,counts)
                self.assertEqual(int(w.overlay.winId()),hwnd);self.assertEqual(w.overlay.mask(),mask)
                self.assertEqual(w.overlay._placed_key,key);self.assertEqual(hidden,[])
            self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
            self.assertNotIn(True,[call.args[0] for call in checking.call_args_list])
        self.assert_slots(wanted);self.assertTrue(w.overlay.isVisible());self.assertEqual(hidden,[])
        self.assertEqual(w.partial_candidates._last_serial,3)
        self.assertEqual(w.partial_candidates._last_capture,value['_capturedAt'])

    def test_changed_known_slot_revokes_before_hud_and_late_positive_cannot_restore_count(self):
        value,hero,names=self.scene();w=self.window;before=self.stamps()
        bad=self.evidence(value,(names[0]+'甲','未知强化',names[2]))
        self.phase('title-proof',dict(value,partial_title_evidence=bad))
        self.assert_slots(('','',names[2]));self.assertTrue(w.overlay.isVisible())
        self.assertEqual(self.stamps(),before);self.assertEqual(w.partial_candidates._counts,(0,0,2))
        self.phase('title-proof',value)
        self.phase('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assert_slots(('','',names[2]));self.assertEqual(w.partial_candidates._counts,(0,0,2))
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assert_slots(('','',names[2]));self.assertEqual(w.partial_candidates._counts,(1,0,2))
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.assertEqual(w.partial_candidates._counts,(1,0,2))

    def test_low_confidence_only_revokes_affected_known_slot(self):
        value,_,names=self.scene();w=self.window
        low=self.evidence(value,(names[0],'未知强化',names[2]),scores=(.92,.99,.99))
        self.phase('title-proof',dict(value,partial_title_evidence=low))
        self.assert_slots(('','',names[2]));self.assertEqual(w.partial_candidates._counts,(0,0,2))

    def test_new_known_slot_needs_two_final_observations_without_churning_existing_regions(self):
        value,hero,names=self.scene();w=self.window
        evidence=self.evidence(value,names)
        from local_ocr import candidate_matches
        lines=[dict(text=n,confidence=.99,box=b) for n,b in zip(names,self.boxes)]
        candidates=candidate_matches(lines,w.data['augments'],min_ocr_confidence=.93)
        new=dict(value,partial_title_evidence=evidence,automatic_candidates=candidates,candidates=candidates)
        self.phase('title-proof',new)
        self.assertEqual(w.partial_candidates._counts,(2,0,2))
        oldmask=w.overlay.mask();hwnd=int(w.overlay.winId());hides=[]
        original=w.overlay.hide
        def hide(*args):
            if w.overlay.isVisible():hides.append(args)
            return original(*args)
        with patch.object(w.overlay,'hide',side_effect=hide):
            self.phase('ocr',dict(new,hero_observation=dict(hero=hero,confident=True)))
        self.assert_slots((names[0],'',names[2]));self.assertEqual(w.partial_candidates._counts,(2,1,2))
        self.assertEqual(w.overlay.mask(),oldmask);self.assertEqual(int(w.overlay.winId()),hwnd);self.assertEqual(hides,[])
        w._capture_serial=4;w.ocr_busy=True;w.capture_pending=False
        captured=new['_capturedAt']+.1
        with patch('native_ui.time.monotonic',return_value=captured):
            self.phase('ocr',dict(new,_captureSerial=4,_capturedAt=captured,
                                   hero_observation=dict(hero=hero,confident=True)))
        self.assertTrue(w.state.confirmed);self.assertEqual(w.state.offered,names)
        self.assertEqual(w.partial_candidates._counts,(2,2,2))
        self.assertEqual(len(w.overlay._badge_regions),3)

    def test_missing_rows_geometry_or_every_scope_change_revokes_all_and_late_positive_stays_hidden(self):
        from partial_candidates import TitleEvidence
        changes=[dict(partial_title_evidence=TitleEvidence()),dict(_cardGeometry=None),dict(ocr_reused=True)]
        for index in range(7):changes.append({'scope_index':index})
        for change in changes:
            with self.subTest(change=change):
                value,hero,_=self.scene();w=self.window
                if 'scope_index' in change:
                    scope=list(value['_frameScope']);scope[change['scope_index']]='changed'
                    change=dict(_frameScope=tuple(scope))
                self.phase('title-proof',dict(value,**change))
                self.assertFalse(w.overlay.isVisible());self.assertIsNone(w._accepted_partial_frame)
                self.assertEqual(w.current_partial_names(),('','',''))
                self.phase('title-proof',value)
                self.phase('capture-proof',dict(value,hero_observation=dict(hero=hero,confident=True)))
                self.assertFalse(w.overlay.isVisible())

    def test_identity_negative_has_monotonic_precedence(self):
        for observation in (dict(confident=False),dict(confident=True,hero='different hero'),
                            dict(confident=False,method='game-client-api',conflict=True)):
            with self.subTest(observation=observation):
                value,hero,_=self.scene();w=self.window
                self.phase('capture-proof',dict(value,hero_observation=observation))
                self.phase('title-proof',value)
                self.assertIsNone(w._accepted_partial_frame);self.assertFalse(w.overlay.isVisible())

    def test_stale_generation_serial_and_post_final_phases_cannot_mutate_new_partial(self):
        from partial_candidates import TitleEvidence
        value,hero,names=self.scene();w=self.window
        negative=dict(value,partial_title_evidence=TitleEvidence())
        for kind in ('title-proof','capture-proof'):
            w.task_result(kind,dict(negative,_captureSerial=2),w.state.generation)
            w.task_result(kind,negative,w.state.generation-1)
        self.assert_slots((names[0],'',names[2]))
        self.phase('ocr',dict(value,hero_observation=dict(hero=hero,confident=True)))
        self.phase('title-proof',negative);self.phase('capture-proof',dict(value,_matchingCardGeometry=None))
        self.assert_slots((names[0],'',names[2]));self.assertTrue(w.overlay.isVisible())

    def test_original_deadline_and_accepted_serial_cannot_be_refreshed_by_early_phases(self):
        value,_,_=self.scene();w=self.window;before=self.stamps()
        self.phase('title-proof',value);self.assertEqual(self.stamps(),before)
        with patch('native_ui.time.monotonic',return_value=before[0]+4.001):
            w.check_target()
        self.assertFalse(w.overlay.isVisible());self.assertIsNone(w._accepted_partial_frame)
        self.phase('title-proof',value);self.assertFalse(w.overlay.isVisible())

    def test_hidden_partial_does_not_restore_without_current_identity_evidence(self):
        value,_,names=self.scene();w=self.window
        w._visible_previous=False;w.overlay.hide('capture_pending')
        bad=self.evidence(value,(names[0]+'甲','未知强化',names[2]))
        self.phase('title-proof',dict(value,partial_title_evidence=bad,_hudInputDigest='different'))
        w.check_target()
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w._restore_while_ocr)


if __name__=='__main__':unittest.main()
