"""Qt thread/state integration with owned fakes; not Windows capture evidence."""
import copy
import gc
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class NativeCaptureWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def wait(self, predicate, seconds=4):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail('Qt worker did not reach the expected state')

    def setUp(self):
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable, WindowInfo
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self._release_events = []
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('owned portable fixture')) as capture_factory:
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=Path(self.directory.name), current_executable=Path('/unused.exe'),
                current_version='test', frozen=False, enable_updates=False)
        self.capture_constructor_options=capture_factory.call_args.kwargs
        self.addCleanup(self.dispose_window)
        self.wait(lambda: self.window.data is not None)
        self.window.watchdog.stop()
        self.window.monitor.stop()
        self.window.schedule_capture = lambda delay=None: None  # Tests drive exact owned observations.
        self.window.check_target = lambda: None
        self.window.target_allowed = lambda: True
        self.window.capture_metadata = lambda: None
        self.window.captured_frame_current = lambda value: True
        self.window.target = WindowInfo(123, 456, 'Owned mock', 'OwnedClass')
        self.window.state.start(self.window.target.identity)
        self.window.overlay.hide()
        self.main_thread = threading.get_ident()

    def dispose_window(self):
        # Qt's parentless widgets must be destroyed on their owning GUI thread,
        # not left in Python/Qt cycles for a later arbitrary GC pass. Release
        # only this fixture's waiting fakes even when an assertion failed.
        window = self.window
        if window is None:
            return
        for event in self._release_events:
            event.set()
        overlay = window.overlay
        window.capture = None
        window.close()
        self.wait(lambda: not window._workers, seconds=3)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(overlay))
        self.assertFalse(isValid(window))
        self.window = None
        gc.collect()
        self.app.processEvents()

    def test_slow_capture_is_off_gui_and_stop_discards_late_result(self):
        from screen_capture import ClientRect
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        threads = []
        class Capture:
            def capture(inner, *args, **kwargs):
                threads.append(threading.get_ident())
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('owned timeout')
                return b'owned-image', ClientRect(0, 0, 900, 600)
        self.window.capture = Capture()
        with patch('hero_recognition.recognize_frame', return_value={'automatic_candidates': [], 'candidates': []}):
            start = time.monotonic()
            self.window.capture_hidden(self.window.state.generation)
            self.assertLess(time.monotonic() - start, .25)
            self.wait(entered.is_set)
            self.assertNotEqual(threads[0], self.main_thread)
            self.window.stop_monitor()
            release.set()
            self.wait(lambda: not self.window.ocr_busy)
        self.assertFalse(self.window.state.running)
        self.assertFalse(self.window.state.confirmed)
        self.assertEqual(self.window.state.offered, ())

    def test_owned_cleanup_releases_waiting_fake_and_deletes_both_widgets(self):
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        def work():
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Owned cleanup fixture did not release worker')
        control, overlay = self.window, self.window.overlay
        control.spawn('owned-cleanup', work)
        self.wait(entered.is_set)
        self.dispose_window()
        self.assertTrue(release.is_set())
        self.assertFalse(control._workers)
        self.assertFalse(isValid(control))
        self.assertFalse(isValid(overlay))
        self.dispose_window()  # Registered cleanup remains safely idempotent.

    def test_two_independent_confirmations_before_reuse_and_fresh_capture_each_tick(self):
        from screen_capture import ClientRect
        names = list(self.window.data['augments'])[:3]
        hero = next(iter(self.window.data['heroes']))
        candidates = [{'name': name, 'recognized_text': name, 'match_method': 'exact',
                       'ocr_confidence': .99, 'box': [[x-40, 150], [x+40, 150],
                                                    [x+40, 180], [x-40, 180]]}
                      for x, name in zip((150, 450, 750), names)]
        capture_calls, infer_calls, hero_calls = [], [], []
        class Capture:
            def capture(inner, *args, **kwargs):
                capture_calls.append(time.monotonic())
                return b'owned-image', ClientRect(0, 0, 900, 600)
        class OCR:
            def recognize(inner, image, vocabulary):
                infer_calls.append(image)
                return {'automatic_candidates': copy.deepcopy(candidates),
                        'candidates': copy.deepcopy(candidates),
                        'image_size': {'width': 900, 'height': 400}}
        def recognize(image, roi, ocr, vocabulary, matcher, *, before_match=None,before_ocr=None,inference_worker=None):
            hero_calls.append(image)
            if before_ocr:before_ocr({'hero': hero, 'confident': True},b'exact-title-crop')
            result = ocr.recognize(b'exact-title-crop', vocabulary)
            result['hero_observation'] = {'hero': hero, 'confident': True}
            return result
        self.window.capture = Capture()
        self.window.ocr = OCR()
        with patch('hero_recognition.recognize_frame', side_effect=recognize):
            for expected in (False, True, True):
                self.window.capture_hidden(self.window.state.generation)
                self.wait(lambda: not self.window.ocr_busy)
                self.assertEqual(self.window.state.confirmed, expected)
            self.assertEqual(len(capture_calls), 3)
            self.assertEqual(len(hero_calls), 3)
            self.assertEqual(len(infer_calls), 2)
            self.assertEqual(self.window.state.automatic_frames, 2)
            self.assertGreaterEqual(self.window.last_observation, capture_calls[-1] - .01)
            self.window.invalidate_scene('owned ROI/scene reset')
            self.window.capture_hidden(self.window.state.generation)
            self.wait(lambda: not self.window.ocr_busy)
            self.assertFalse(self.window.state.confirmed)
            self.assertEqual(len(infer_calls), 3)

    def test_changed_hero_cached_titles_require_two_fresh_confirmations_in_both_directions(self):
        from screen_capture import ClientRect
        names = list(self.window.data['augments'])[:3]
        heroes = list(self.window.data['heroes'])[:2]
        self.assertEqual(len(heroes), 2)
        selected = [heroes[0]]
        calls = []
        candidates = [{'name': name, 'recognized_text': name, 'match_method': 'exact',
                       'ocr_confidence': .99, 'box': [[x-40, 150], [x+40, 150],
                                                    [x+40, 180], [x-40, 180]]}
                      for x, name in zip((150, 450, 750), names)]
        class Capture:
            def capture(inner, *args, **kwargs):
                return b'owned-image', ClientRect(0, 0, 900, 600)
        class OCR:
            def recognize(inner, image, vocabulary):
                calls.append(selected[0])
                return {'automatic_candidates': copy.deepcopy(candidates),
                        'candidates': copy.deepcopy(candidates),
                        'image_size': {'width': 900, 'height': 400}}
        def recognize(image, roi, ocr, vocabulary, matcher, *, before_match=None,before_ocr=None,inference_worker=None):
            if before_ocr:before_ocr({'hero': selected[0], 'confident': True},b'unchanged-owned-titles')
            result = ocr.recognize(b'unchanged-owned-titles', vocabulary)
            result['hero_observation'] = {'hero': selected[0], 'confident': True}
            return result
        def tick():
            self.window.capture_hidden(self.window.state.generation)
            self.wait(lambda: not self.window.ocr_busy)
        self.window.capture = Capture()
        self.window.ocr = OCR()
        self.window.ocr_reuse.clock = lambda: 100.0  # Deterministic non-expired owned cache.
        with patch('hero_recognition.recognize_frame', side_effect=recognize):
            tick(); tick()
            self.assertTrue(self.window.state.confirmed)
            self.assertEqual(len(calls), 2)
            for hero in (heroes[1], heroes[0]):
                selected[0] = hero
                before = len(calls)
                tick()  # Fresh hero + reused title must revoke old confirmation.
                self.assertEqual(len(calls), before)
                self.assertEqual(self.window.state.automatic_frames, 0)
                self.assertEqual(self.window.state.hero, '')
                self.assertFalse(self.window.state.confirmed)
                self.assertFalse(self.window.overlay.isVisible())
                tick()
                self.assertEqual(len(calls), before + 1)
                self.assertEqual(self.window.state.automatic_frames, 1)
                self.assertEqual(self.window.state.hero, hero)
                self.assertFalse(self.window.state.confirmed)
                self.assertFalse(self.window.overlay.isVisible())
                tick()
                self.assertEqual(len(calls), before + 2)
                self.assertEqual(self.window.state.automatic_frames, 2)
                self.assertEqual(self.window.state.hero, hero)
                self.assertTrue(self.window.state.confirmed)

    def test_watchdog_never_restores_overlay_while_capture_worker_is_busy(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        rect = ClientRect(0, 0, 900, 600)
        class Capture:
            def rect(inner, target):return rect
            def foreground(inner, target):return True
        self.window.capture = Capture()
        self.window.state.hero = next(iter(self.window.data['heroes']))
        self.window.state.confirm(list(self.window.data['augments'])[:3], self.window.data['augments'])
        self.window.last_observation = time.monotonic()
        self.window.last_rect = rect
        self.window.overlay.cards = [{'name': 'owned synthetic card'}]
        self.window.overlay.hide()
        self.window.ocr_busy = True
        self.window.ocr_started = time.monotonic()
        ControlWindow.check_target(self.window)
        self.assertFalse(self.window.overlay.isVisible())
        self.window.ocr_busy = False
        ControlWindow.check_target(self.window)
        self.assertTrue(self.window.overlay.isVisible())

    def test_manual_process_binding_and_post_inference_geometry_fail_closed(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        rect = ClientRect(0, 0, 900, 600)
        current = [rect]
        class Capture:
            def rect(inner, target):return current[0]
            def foreground(inner, target):return True
        self.window.capture = Capture()
        self.window.manual_identity = self.window.target.identity
        self.window.manual_metadata = ProcessMetadata('c:\\owned\\fixture.exe', 111)
        with patch('session_windows.process_metadata', return_value=self.window.manual_metadata):
            self.assertTrue(ControlWindow.target_allowed(self.window))
        with patch('session_windows.process_metadata', return_value=ProcessMetadata('c:\\owned\\fixture.exe', 222)):
            self.assertFalse(ControlWindow.target_allowed(self.window))
        proof = {'_captureRect': rect, '_windowIdentity': self.window.target.identity}
        self.assertTrue(ControlWindow.captured_frame_current(self.window, proof))
        current[0] = ClientRect(1, 0, 900, 600)
        self.assertFalse(ControlWindow.captured_frame_current(self.window, proof))
        self.assertFalse(ControlWindow.captured_frame_current(self.window, {}))

    def accepted_proof_fixture(self):
        from native_ui import ControlWindow
        from native_state import display_cards
        from screen_capture import ClientRect
        w=self.window;rect=ClientRect(0,0,900,600);names=tuple(w.data['augments'])[:3];hero=next(iter(w.data['heroes']))
        class Matcher:
            def __init__(inner):inner.token=object();inner.minimum_score=.88
            def proof_identity(inner):return (inner.token,inner.minimum_score,.07)
        class Capture:
            def rect(inner,target):return rect
            def foreground(inner,target):return True
        w.hero_matcher=Matcher();w.capture=Capture();w.state.hero=hero;w.state.hero_observed=hero;w.state.hero_stable_frames=2;w.state.confirm(names,w.data['augments'],automatic=True)
        w.overlay.set_cards(hero,display_cards(w.data,hero,names));w.overlay.hide()
        w.last_observation=time.monotonic()-.1;w.last_rect=rect;w.ocr_started=time.monotonic()
        scope=(w.target.identity,None,rect,tuple(s.value()/100 for s in w.roi),tuple(w.data['augments']),
            (id(w.data),json.dumps(w.data['metadata'],sort_keys=True,ensure_ascii=False)),(w.hero_matcher,w.hero_matcher.proof_identity()))
        value={'_windowIdentity':w.target.identity,'_captureRect':rect,'_frameScope':scope,'_roiDigest':hashlib.sha256(b'owned-crop').hexdigest(),
            '_hudInputDigest':'a'*64,'_capturedAt':w.last_observation,'hero_observation':{'hero':hero,'confident':True}}
        w.remember_accepted_frame(value)
        w.check_target=lambda:ControlWindow.check_target(w)
        fresh=dict(value,_capturedAt=time.monotonic(),_captureSerial=w._capture_serial)
        fresh.pop('hero_observation')
        return fresh,hero,names

    def test_early_exact_input_proof_restores_only_previous_result_without_refreshing_ttl(self):
        w=self.window;value,hero,names=self.accepted_proof_fixture();old_time=w.last_observation
        old_counts=(w.state.automatic_frames,w.state.hero_stable_frames,w.state.generation)
        w.capture_pending=True;w.ocr_busy=True
        w.task_result('capture-proof',value,w.state.generation)
        self.assertFalse(w.capture_pending);self.assertTrue(w.ocr_busy);self.assertTrue(w.overlay.isVisible())
        self.assertIn('上次候选复核中',w.overlay.heading.text())
        self.assertEqual(w.last_observation,old_time);self.assertEqual((w.state.automatic_frames,w.state.hero_stable_frames,w.state.generation),old_counts)
        changed=dict(value,hero_observation={'confident':False},automatic_candidates=[],candidates=[],image_size={'width':900,'height':400})
        w.task_result('ocr',changed,w.state.generation)
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed);self.assertIsNone(w._accepted_frame)

    def test_fast_restore_rejects_every_changed_or_expired_reference_scope(self):
        w=self.window;value,hero,names=self.accepted_proof_fixture()
        self.assertTrue(w.may_restore_accepted_frame(value))
        for field,replacement in (('_roiDigest','b'*64),('_hudInputDigest',None),('_capturedAt',w.last_observation)):
            with self.subTest(field=field):self.assertFalse(w.may_restore_accepted_frame(dict(value,**{field:replacement})))
        for index in range(7):
            scope=list(value['_frameScope']);scope[index]='changed-proof-scope'
            with self.subTest(scope=index):self.assertFalse(w.may_restore_accepted_frame(dict(value,_frameScope=tuple(scope))))
        self.assertFalse(w.may_restore_accepted_frame(dict(value,hero_observation={'hero':hero,'confident':False})))
        w.hero_matcher.minimum_score=.95;self.assertFalse(w.may_restore_accepted_frame(value));w.hero_matcher.minimum_score=.88
        old_data=w.data;w.data=dict(w.data);self.assertFalse(w.may_restore_accepted_frame(value));w.data=old_data
        w._accepted_frame['observed_at']=time.monotonic()-4.01;self.assertFalse(w.may_restore_accepted_frame(value))

    def test_direct_invalidation_hides_visible_previous_overlay_and_clears_status_now(self):
        w=self.window;value,_,_=self.accepted_proof_fixture()
        w.capture_pending=True;w.ocr_busy=True;w.task_result('capture-proof',value,w.state.generation)
        self.assertTrue(w.overlay.isVisible());w.status.setText('old confirmation status')
        w.invalidate_scene('Owned explicit scene invalidation')
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.confirmed)
        self.assertIsNone(w._accepted_frame);self.assertEqual(w.status.text(),'Owned explicit scene invalidation')

    def test_capture_failure_edit_stop_and_late_phase_never_restore(self):
        w=self.window;value,_,_=self.accepted_proof_fixture();generation=w.state.generation
        w.ocr_busy=True;w.capture_pending=True;w.task_error('ocr','owned acquisition failure',generation)
        self.assertFalse(w.overlay.isVisible());self.assertIsNone(w._accepted_frame)
        w.task_result('capture-proof',value,generation);self.assertFalse(w.overlay.isVisible())
        value,_,_=self.accepted_proof_fixture();w.edit_changed();self.assertIsNone(w._accepted_frame)
        w.task_result('capture-proof',value,w.state.generation-1);self.assertFalse(w.overlay.isVisible())
        value,_,_=self.accepted_proof_fixture();generation=w.state.generation;w.stop_monitor()
        w.task_result('capture-proof',value,generation);self.assertFalse(w.overlay.isVisible());self.assertFalse(w.state.running)

    def test_slow_inference_keeps_exact_previous_frame_visible_without_overlapping_capture(self):
        from screen_capture import ClientRect
        w=self.window;_,hero,names=self.accepted_proof_fixture();release=threading.Event();self._release_events.append(release);calls=[]
        class Capture:
            def capture(inner,*args,**kwargs):calls.append(1);return b'owned-image',ClientRect(0,0,900,600)
            def rect(inner,target):return ClientRect(0,0,900,600)
            def foreground(inner,target):return True
        w.capture=Capture()
        candidates=[{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,'box':[[x-40,150],[x+40,150],[x+40,180],[x-40,180]]} for x,name in zip((150,450,750),names)]
        def recognize(image,roi,ocr,vocabulary,matcher,*,before_match,before_ocr,inference_worker=None):
            before_match('a'*64,b'owned-crop')
            if not release.wait(2):raise RuntimeError('owned inference timeout')
            before_ocr({'hero':hero,'confident':True},b'owned-crop')
            return {'hero_observation':{'hero':hero,'confident':True},'candidates':candidates,'automatic_candidates':candidates,'image_size':{'width':900,'height':400}}
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation);self.wait(lambda:w.overlay.isVisible())
            self.assertTrue(w.ocr_busy);self.assertFalse(w.capture_pending)
            old_time=w.last_observation;w.capture_tick();self.assertEqual(calls,[1]);self.assertEqual(w.last_observation,old_time)
            self.assertIn('复核中',w.overlay.heading.text());release.set();self.wait(lambda:not w.ocr_busy)
        self.assertTrue(w.state.confirmed);self.assertNotIn('复核中',w.overlay.heading.text());self.assertEqual(calls,[1])

    def test_completion_cadence_is_single_shot_bounded_and_never_overlaps(self):
        from native_ui import ControlWindow
        w=self.window;self.assertTrue(w.monitor.isSingleShot())
        w.ocr_busy=True;ControlWindow.schedule_capture(w);self.assertFalse(w.monitor.isActive())
        w.ocr_busy=False;w.capture_pending=True;ControlWindow.schedule_capture(w);self.assertFalse(w.monitor.isActive())
        w.capture_pending=False;ControlWindow.schedule_capture(w);self.assertEqual(w.monitor.interval(),200);w.monitor.stop()
        w.state.confirmed=True;ControlWindow.schedule_capture(w);self.assertEqual(w.monitor.interval(),700);w.monitor.stop()
        w.state.confirmed=False
        with patch.object(w,'client_strength_reference',return_value={'sourceTier':'T5'}):
            ControlWindow.schedule_capture(w);self.assertEqual(w.monitor.interval(),700);w.monitor.stop();self.assertFalse(w.state.confirmed)
        with patch.object(w,'client_strength_reference',return_value=None):
            ControlWindow.schedule_capture(w);self.assertEqual(w.monitor.interval(),200);w.monitor.stop()
        w.stop_monitor();ControlWindow.schedule_capture(w);self.assertFalse(w.monitor.isActive())


    def game_round_fixture(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        w=self.window;rect=ClientRect(0,0,1280,720)
        class Capture:
            foreground_now=True
            def rect(inner,target):return rect
            def foreground(inner,target):return inner.foreground_now
        w.capture=Capture();w.last_rect=rect
        w.check_target=lambda:ControlWindow.check_target(w)
        w.captured_frame_current=lambda value:ControlWindow.captured_frame_current(w,value)
        hero=next(iter(w.data['heroes']));names=tuple(w.data['augments'])
        def observation(names,when,*,known=True,reused=False):
            candidates=[{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,
                'box':[[x-40,150],[x+40,150],[x+40,180],[x-40,180]]} for x,name in zip((150,450,750),names)]
            return {'automatic_candidates':candidates,'candidates':candidates,'image_size':{'width':900,'height':400},
                'hero_observation':{'hero':hero if known else None,'confident':known},'_capturedAt':when,
                '_windowIdentity':w.target.identity,'_captureRect':rect,'ocr_reused':reused}
        def deliver(names,when,*,delay=.01,generation=None,**kwargs):
            value=observation(names,when,**kwargs)
            with patch('native_ui.time.monotonic',return_value=when+delay):
                w.task_result('ocr',value,w.state.generation if generation is None else generation)
            return value
        deliver(names[:3],100);deliver(names[:3],100.3)
        self.assertTrue(w.state.confirmed)
        return names,hero,observation,deliver

    def test_game_display_expiry_retains_authorized_fresh_inflight_result(self):
        w=self.window;names,hero,observation,deliver=self.game_round_fixture()
        old=w.last_observation;generation=w.state.generation;counts=(w.state.automatic_frames,w.state.hero_stable_frames)
        w.ocr_busy=True;w.ocr_started=old+2.7;w._capture_cancel.clear()
        with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible());self.assertEqual(w.state.hero,'')
        self.assertEqual(w.hero_title.text(),'等待识别');self.assertTrue(all(v['name'].text()=='等待识别' for v in w.candidate_views))
        self.assertNotIn('资料已确认',w.status_chip.text());self.assertIsNone(w._accepted_frame)
        self.assertEqual(w.state.generation,generation);self.assertFalse(w._capture_cancel.is_set())
        self.assertEqual((w.state.automatic_frames,w.state.hero_stable_frames),counts);self.assertEqual(w.last_observation,old)
        deliver(names[:3],old+2.7,delay=2,generation=generation)
        self.assertTrue(w.state.confirmed);self.assertEqual(w.state.hero,hero);self.assertEqual(w.state.offered,names[:3])
        self.assertEqual(w.last_observation,old+2.7)

    def test_normal_reroll_and_three_slow_rounds_rearm_without_manual_actions(self):
        w=self.window;names,_,_,deliver=self.game_round_fixture();when=w.last_observation
        for next_names in (names[1:4],names[:3],tuple(reversed(names[1:4]))):
            old=when;generation=w.state.generation;w.ocr_busy=True;w.ocr_started=old+2.7;w._capture_cancel.clear()
            with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
            when=old+2.7;deliver(next_names,when,delay=2,generation=generation)
            self.assertFalse(w.manual_editing);self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
            self.assertEqual(w.state.observed,next_names)
            when+=2.7;deliver(next_names,when,delay=2)
            self.assertTrue(w.state.confirmed);self.assertEqual(w.state.offered,next_names)
            when+=.2;deliver([],when)
            self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
            # Fresh independently recognized round, no manual confirmation.
            when+=.2;deliver(next_names,when);self.assertFalse(w.state.confirmed)
            when+=.2;deliver(next_names,when);self.assertTrue(w.state.confirmed)

    def test_game_private_continuity_has_exact_four_second_capture_gap(self):
        for gap,expected in ((4.,True),(4.001,False)):
            with self.subTest(gap=gap):
                w=self.window;names,_,_,deliver=self.game_round_fixture();old=w.last_observation
                with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
                deliver(names[:3],old+gap,delay=.02)
                self.assertEqual(w.state.confirmed,expected)
                if not expected:
                    self.assertEqual(w.state.automatic_frames,1);self.assertEqual(w.state.hero_stable_frames,1)
                    deliver(names[:3],old+gap+.3);self.assertTrue(w.state.confirmed)
                w.invalidate_scene('Owned subcase reset')

    def test_expired_display_cannot_reconfirm_from_reused_ocr(self):
        w=self.window;names,_,_,deliver=self.game_round_fixture();old=w.last_observation
        with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
        deliver(names[:3],old+2.7,delay=2,reused=True)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())
        self.assertEqual(w.last_observation,old)

    def test_game_expiry_does_not_weaken_unknown_stale_future_or_timeout_rejection(self):
        for case in ('unknown','stale','future','timeout'):
            with self.subTest(case=case):
                w=self.window;names,_,_,deliver=self.game_round_fixture();old=w.last_observation;generation=w.state.generation
                w.ocr_busy=True;w.ocr_started=old+2.7;w._capture_cancel.clear()
                with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
                if case=='timeout':
                    with patch('native_ui.time.monotonic',return_value=w.ocr_started+8.01):w.check_target()
                    self.assertTrue(w._capture_cancel.is_set());self.assertNotEqual(w.state.generation,generation)
                    deliver(names[:3],old+2.7,delay=2,generation=generation)
                else:deliver(names[:3],old+2.7,delay={'unknown':2,'stale':4.001,'future':-.001}[case],generation=generation,known=case!='unknown')
                self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible());self.assertEqual(w.state.hero,'')
                w.invalidate_scene('Owned subcase reset')

    def test_hard_focus_or_stop_revocation_discards_result_after_soft_expiry(self):
        for action in ('focus','stop'):
            with self.subTest(action=action):
                w=self.window
                if not w.state.running:w.state.start(w.target.identity)
                names,_,_,deliver=self.game_round_fixture();old=w.last_observation;generation=w.state.generation
                w.ocr_busy=True;w.ocr_started=old+2.7;w._capture_cancel.clear()
                with patch('native_ui.time.monotonic',return_value=old+4.01):w.check_target()
                if action=='focus':
                    w.capture.foreground_now=False
                    with patch('native_ui.time.monotonic',return_value=old+4.02):w.check_target()
                else:w.stop_monitor()
                self.assertTrue(w._capture_cancel.is_set());self.assertNotEqual(w.state.generation,generation)
                deliver(names[:3],old+2.7,delay=2,generation=generation)
                self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())

    def test_successful_manual_confirm_ends_editing_but_invalid_confirm_does_not(self):
        from PySide6 import QtTest
        w=self.window;names,_,_,deliver=self.game_round_fixture()
        w.inputs[0].setFocus();w.inputs[0].setCursorPosition(len(w.inputs[0].text()))
        QtTest.QTest.keyClick(w.inputs[0],QtCore.Qt.Key.Key_Space)
        self.assertTrue(w.manual_editing);self.assertFalse(w.state.confirmed)
        with patch('native_ui.time.monotonic',return_value=100.4):w.confirm()
        self.assertTrue(w.state.confirmed);self.assertFalse(w.manual_editing)
        deliver([],100.6);deliver(names[1:4],100.9);self.assertFalse(w.state.confirmed)
        deliver(names[1:4],101.2);self.assertTrue(w.state.confirmed);self.assertEqual(w.state.offered,names[1:4])
        w.inputs[0].setText('Unmatched owned edit');w.edit_changed();w.confirm()
        self.assertFalse(w.state.confirmed);self.assertTrue(w.manual_editing)
        deliver(names[:3],101.5);deliver(names[:3],101.8)
        self.assertFalse(w.state.confirmed);self.assertEqual(w.inputs[0].text(),'Unmatched owned edit')


    def test_adaptive_cadence_preserves_remaining_game_and_client_capture_gap(self):
        from native_ui import ControlWindow
        from types import SimpleNamespace
        w=self.window;w.last_observation=100.;w.state.confirmed=False
        with patch('native_ui.time.monotonic',return_value=103.9):
            ControlWindow.schedule_capture(w);self.assertLessEqual(w.monitor.interval(),20);w.monitor.stop()
        w.client_phase=lambda:True;w.selection_session=SimpleNamespace(active=False,last_client_frame=100.,stop=lambda:None)
        w.last_observation=0.
        with patch('native_ui.time.monotonic',return_value=103.9):
            ControlWindow.schedule_capture(w);self.assertLessEqual(w.monitor.interval(),20);w.monitor.stop()
        with patch('native_ui.time.monotonic',return_value=104.1):
            ControlWindow.schedule_capture(w);self.assertEqual(w.monitor.interval(),200);w.monitor.stop()
        w.selection_session=None

    def test_hidden_settle_uses_actual_hide_age_including_external_hide_path(self):
        w=self.window;timers=[]
        class Capture:
            def foreground(inner,target):return True
        w.capture=Capture();w.overlay.show()
        with patch('native_ui.time.monotonic',return_value=100.):w.overlay.hide()
        with patch('native_ui.time.monotonic',return_value=100.02),patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:timers.append(delay)):
            w.capture_tick()
        self.assertGreaterEqual(timers[-1],39);self.assertLessEqual(timers[-1],41)
        w.capture_pending=False
        with patch('native_ui.time.monotonic',return_value=100.1),patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:timers.append(delay)):
            w.capture_tick()
        self.assertEqual(timers[-1],0)

    def visible_capture_fixture(self):
        from screen_capture import ClientRect
        w=self.window;_,hero,names=self.accepted_proof_fixture();self.assertIs(w.enable_visible_capture,True)
        class Capture:
            can_request_visible_overlay=True;cleanup_pending=False
            plans=[]
            def foreground(inner,target):return True
            def rect(inner,target):return ClientRect(0,0,900,600)
            def prepare_capture_mode(inner,visible):inner.plans.append(visible);return True
        w.capture=Capture();w.overlay.show();w.refresh_status_badge()
        return w.capture,hero,names

    def test_guarded_visible_capture_is_default_and_previous_label_does_not_refresh_evidence(self):
        w=self.window;capture,hero,names=self.visible_capture_fixture();old_time=w.last_observation
        self.assertEqual(self.capture_constructor_options,{'allow_visible_overlay':True})
        old_counts=(w.state.generation,w.state.automatic_frames,w.state.hero_stable_frames);calls=[]
        with patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:calls.append((delay,fn))):w.capture_tick()
        self.assertEqual(capture.plans,[True]);self.assertTrue(w.overlay.isVisible());self.assertTrue(w.capture_pending)
        self.assertIn('上次候选复核中',w.overlay.heading.text());self.assertIn('尚非本帧结果',w.candidate_caption.text())
        self.assertNotIn('资料已确认',w.status_chip.text());self.assertEqual(w.last_observation,old_time)
        self.assertEqual((w.state.generation,w.state.automatic_frames,w.state.hero_stable_frames),old_counts);self.assertEqual(calls[0][0],0)
        w.capture_pending=False;w.enable_visible_capture=False
        with patch('native_ui.time',SimpleNamespace(monotonic=lambda:old_time)), \
             patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:calls.append((delay,fn))):
            w.capture_tick()
        self.assertFalse(w.overlay.isVisible());self.assertEqual(calls[-1][0],60)

    def test_native_entrypoint_preserves_default_and_explicit_strict_hidden_diagnostics(self):
        from native_ui import run_native
        for options in ({},{'smoke_report':Path('native.json')},{'selection_smoke_input':Path('selection.json')},
                        {'smoke_report':Path('selection-result.json'),'selection_smoke_input':Path('selection.json')}):
            with self.subTest(options=options),patch('native_ui.QtWidgets.QApplication') as application,\
                    patch('native_ui.ControlWindow') as constructor:
                app=application.instance.return_value;app.exec.return_value=0
                self.assertEqual(run_native(lambda:None,state_dir=Path(self.directory.name),
                    current_executable=Path('/unused.exe'),current_version='test',frozen=False,**options),0)
                if options:self.assertIs(constructor.call_args.kwargs['enable_visible_capture'],False)
                else:self.assertNotIn('enable_visible_capture',constructor.call_args.kwargs)
                self.assertIs(app._vga_control,constructor.return_value)

    def test_visible_capture_waits_for_planned_cleanup_without_clearing_confirmation(self):
        w=self.window;capture,_,_=self.visible_capture_fixture();capture.cleanup_pending=True;scheduled=[];generation=w.state.generation
        capture.prepare_capture_mode=lambda visible:not capture.cleanup_pending
        w.schedule_capture=lambda delay=None:scheduled.append(delay)
        w.capture_tick()
        self.assertEqual(capture.plans,[]);self.assertEqual(scheduled,[50]);self.assertFalse(w.ocr_busy);self.assertFalse(w.capture_pending)
        self.assertTrue(w.state.confirmed);self.assertTrue(w.overlay.isVisible());self.assertEqual(w.state.generation,generation)
        capture.cleanup_pending=False;timers=[]
        capture.prepare_capture_mode=lambda visible:capture.plans.append(visible) or True
        with patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:timers.append((delay,fn))):w.capture_tick()
        self.assertEqual(capture.plans,[True]);self.assertTrue(w.capture_pending);self.assertEqual(timers[0][0],0)

    def test_planned_cleanup_is_bounded_and_does_not_start_replacement_work(self):
        w=self.window;capture,_,_=self.visible_capture_fixture();capture.cleanup_pending=True;capture.prepare_capture_mode=lambda visible:False
        with patch('native_ui.time.monotonic',return_value=100.):w.capture_tick()
        with patch('native_ui.time.monotonic',return_value=108.001):w.capture_tick()
        self.assertFalse(w.state.running);self.assertFalse(w.overlay.isVisible());self.assertFalse(w.capture_pending)
        self.assertEqual(capture.plans,[]);self.assertIn('监测已停止',w.status.text())

    def test_visible_changed_pixel_proof_stays_historical_until_fresh_final_result(self):
        w=self.window;capture,hero,names=self.visible_capture_fixture();release=threading.Event();self._release_events.append(release);requests=[]
        def acquire(*args,**kwargs):requests.append(kwargs);return b'owned changing frame',capture.rect(w.target)
        capture.capture=acquire
        candidates=[{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,
            'box':[[x-40,150],[x+40,150],[x+40,180],[x-40,180]]} for x,name in zip((150,450,750),names)]
        def recognize(image,roi,ocr,vocabulary,matcher,*,before_match,before_ocr,inference_worker=None):
            before_match('changed-HUD-animation',b'changed-whole-ROI-animation')
            if not release.wait(2):raise RuntimeError('owned timeout')
            before_ocr({'hero':hero,'confident':True},b'changed-whole-ROI-animation')
            return {'hero_observation':{'hero':hero,'confident':True},'automatic_candidates':candidates,'candidates':candidates,'image_size':{'width':900,'height':400}}
        old=w.last_observation;w._visible_previous=True;w.overlay.set_rechecking(True)
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation,allow_visible_overlay=True)
            self.wait(lambda:bool(requests) and not w.capture_pending)
            self.assertTrue(w.overlay.isVisible());self.assertTrue(w.ocr_busy);self.assertEqual(w.last_observation,old)
            self.assertIn('上次候选复核中',w.overlay.heading.text());self.assertTrue(requests[0]['allow_visible_overlay'])
            release.set();self.wait(lambda:not w.ocr_busy)
        self.assertTrue(w.state.confirmed);self.assertFalse(w._visible_previous);self.assertNotIn('复核中',w.overlay.heading.text())

    def test_resolved_hero_conflict_hides_while_title_ocr_is_still_held(self):
        w=self.window;capture,hero,names=self.visible_capture_fixture()
        release=threading.Event();resolved=threading.Event();self._release_events.append(release)
        capture.capture=lambda *args,**kwargs:(b'owned synthetic conflict',capture.rect(w.target))
        def recognize(image,roi,ocr,vocabulary,matcher,*,before_match,before_ocr,inference_worker=None):
            before_match('owned-digest',b'owned-crop')
            observation={'hero':None,'confident':False,'method':'game-client-api'}
            before_ocr(observation,b'owned-crop');resolved.set()
            if not release.wait(2):raise RuntimeError('owned timeout')
            return {'hero_observation':observation,'automatic_candidates':[],'candidates':[]}
        generation=w.state.generation;w._visible_previous=True
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(generation,allow_visible_overlay=True)
            self.wait(lambda:resolved.is_set() and not w.state.confirmed)
            self.assertTrue(w.ocr_busy);self.assertFalse(w.overlay.isVisible())
            self.assertFalse(w.state.hero);self.assertIsNone(w._accepted_frame)
            self.assertEqual(w.state.generation,generation)
            release.set();self.wait(lambda:not w.ocr_busy)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible())

    def test_early_hero_proof_preserves_manual_and_valid_carried_unknown(self):
        for manual,origin in ((True,'manual'),(False,'client-provisional')):
            with self.subTest(manual=manual):
                w=self.window;value,hero,names=self.accepted_proof_fixture()
                w.hero_auto.blockSignals(True);w.hero_auto.setChecked(not manual);w.hero_auto.blockSignals(False)
                w.hero_origin=origin;w.overlay.show();w._visible_previous=True;w.ocr_busy=True
                generation=w.state.generation
                w.task_result('capture-proof',dict(value,hero_observation={'confident':False,'method':'own-hud-portrait'}),generation)
                self.assertTrue(w.state.confirmed);self.assertEqual(w.state.generation,generation)
                self.assertTrue(w.overlay.isVisible());self.assertTrue(w.ocr_busy)
                w.ocr_busy=False

    def test_changed_confident_hero_proof_revokes_prior_grade_immediately(self):
        w=self.window;value,hero,names=self.accepted_proof_fixture()
        w.overlay.show();w._visible_previous=True;w.ocr_busy=True
        generation=w.state.generation
        w.task_result('capture-proof',dict(value,hero_observation={'hero':'different hero','confident':True}),generation)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.overlay.isVisible());self.assertTrue(w.ocr_busy)
        self.assertEqual(w.state.generation,generation);w.ocr_busy=False

    def test_visible_pending_unknown_or_expired_result_clears_previous_display(self):
        w=self.window;_,_,_=self.visible_capture_fixture();generation=w.state.generation
        w._visible_previous=True;w.overlay.set_rechecking(True)
        with patch('native_ui.time.monotonic',return_value=w.last_observation+4.001):w.check_target()
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w._visible_previous);self.assertFalse(w.state.confirmed)
        self.assertEqual(w.state.generation,generation)


    def test_pending_legacy_cleanup_reaches_strict_hidden_worker_drain(self):
        w=self.window;capture,_,_=self.visible_capture_fixture();capture.cleanup_pending=True
        capture.can_request_visible_overlay=False
        calls=[]
        def acquire(*args,**kwargs):
            calls.append(kwargs)
            self.assertFalse(w.overlay.isVisible())
            self.assertNotIn('allow_visible_overlay',kwargs)
            capture.cleanup_pending=False  # Explicit owned worker-drain double.
            return b'owned drained frame',capture.rect(w.target)
        capture.capture=acquire;timers=[]
        with patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:timers.append(fn)):
            w.capture_tick()
        self.assertEqual(capture.plans,[False]);self.assertTrue(w.capture_pending);self.assertFalse(w.overlay.isVisible())
        with patch('hero_recognition.recognize_frame',return_value={'hero_observation':{'confident':False},'candidates':[],'automatic_candidates':[]}):
            timers[0]();self.wait(lambda:not w.ocr_busy)
        self.assertEqual(len(calls),1);self.assertFalse(capture.cleanup_pending)

    def test_rechecking_heading_does_not_revoke_cached_native_placement(self):
        import ctypes
        w=self.window;_,_,_=self.visible_capture_fixture();overlay=w.overlay;rect=w.capture.rect(w.target)
        class Capture:
            class User:
                def GetWindowRect(inner,hwnd,output):
                    import native_ui
                    native=ctypes.cast(output,ctypes.POINTER(native_ui.W.RECT)).contents
                    native.left=rect.x;native.top=rect.y;native.right=rect.x+800;native.bottom=rect.y+80
                    return True
            u=User()
            def configure_overlay(inner,*args,**kwargs):pass
        overlay.capture=Capture();dpr=float(overlay.windowHandle().devicePixelRatio());key=(rect,overlay._layout_revision,dpr)
        overlay._placed_key=key;before=overlay.size();hides=[]
        class HideObserver(QtCore.QObject):
            def eventFilter(inner,obj,event):
                if event.type()==QtCore.QEvent.Type.Hide:hides.append(1)
                return False
        observer=HideObserver(overlay);overlay.installEventFilter(observer)
        for reviewing in (True,False,True,False):
            overlay.set_rechecking(reviewing);overlay.show_at(rect,w.target);self.app.processEvents()
            self.assertEqual(overlay._placed_key,key);self.assertEqual(overlay.size(),before)
        self.assertEqual(hides,[]);self.assertTrue(overlay.isVisible())
        overlay.capture=None


if __name__ == '__main__':
    unittest.main()
