"""Owned selection timing and display fixtures; not live Windows/game evidence."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from selection_session import SelectionSession


CLIENT = (1, 10, 'Chrome_WidgetWin_1')


def deliver_portraits(window, value):
    # Each synthetic terminal belongs to a distinct public-asset worker lease.
    window._portraits_attempt += 1
    window._portraits_busy = True
    window.task_result('portraits', value, window._portraits_attempt)


def assigned(champion='9001'):
    return {'scene': 'assigned-selection', 'assigned': True, 'championId': champion}


class ClientExpiryTests(unittest.TestCase):
    def game_session(self, verified=False):
        session = SelectionSession(); session.start(CLIENT)
        for stamp in (100., 101.):
            session.observe_client(assigned(), CLIENT, stamp, stamp, generation=session.generation)
        game = (2, 20, 'game')
        session.begin_handoff(game, 102., generation=session.generation, new_game_window=True)
        session.observe_game(game, 103., 105., generation=session.generation, game_scene=True,
                             hud_hero='9001' if verified else None)
        return session, game

    def test_expired_game_carry_requires_fresh_scene_and_new_hud_for_verified(self):
        for initially_verified in (False, True):
            for new_hud in (None, '9001'):
                with self.subTest(initially_verified=initially_verified, new_hud=new_hud):
                    session, game = self.game_session(initially_verified); token = session.generation
                    session.expire(107.1)
                    self.assertEqual(session.stage, 'game-expired'); self.assertEqual(session.verified, '')
                    self.assertIsNone(session.visible_identity(allow_provisional=True)); self.assertEqual(session.generation, token)
                    self.assertTrue(session.observe_game(game, 105.76, 107.76, generation=token, game_scene=True, hud_hero=new_hud))
                    self.assertEqual(session.visible_identity(allow_provisional=True)['verified'], new_hud is not None)

    def test_expired_game_carry_rejects_missing_scene_conflict_gap_age_future_and_stop(self):
        for kind in ('unknown', 'conflict', 'gap', 'late', 'future', 'stop', 'identity'):
            with self.subTest(kind=kind):
                session, game = self.game_session(True); token = session.generation; session.expire(107.1)
                captured = 105.76; now = 107.76; scene = True; hud = None
                if kind == 'unknown': scene = False
                elif kind == 'conflict': hud = '9002'
                elif kind == 'gap': captured = 107.01
                elif kind == 'late': now = 109.761
                elif kind == 'future': captured = 108.
                elif kind == 'stop': session.stop()
                else: game = (9, 99, 'other')
                self.assertFalse(session.observe_game(game, captured, now, generation=token, game_scene=scene, hud_hero=hud))
                self.assertIsNone(session.visible_identity(allow_provisional=True)); self.assertFalse(session.carried)

    def test_one_to_four_second_inference_keeps_existing_freshness_and_gap_contract(self):
        for latency in (1., 1.8, 2., 3., 3.7, 4.):
            with self.subTest(latency=latency):
                session = SelectionSession(); session.start(CLIENT)
                session.observe_client(assigned(), CLIENT, 100., 100. + latency,
                                       generation=session.generation)
                token = session.generation
                second_capture = 100. + latency + .26
                finish = second_capture + latency
                session.expire(finish - .01)
                self.assertEqual(session.generation, token)
                if finish - .01 > 104.:
                    self.assertEqual(session.assigned, '')
                    self.assertEqual(session.stage, 'client-expired')
                stable = session.observe_client(assigned(), CLIENT, second_capture, finish,
                                                generation=token)
                self.assertEqual(stable, second_capture - 100. <= 4.)
                self.assertEqual(session.candidate_frames, 2 if stable else 1)

    def test_expiry_never_renews_frame_time_or_permits_loading(self):
        session = SelectionSession(); session.start(CLIENT)
        for stamp in (100., 101.):
            session.observe_client(assigned(), CLIENT, stamp, stamp, generation=session.generation)
        token = session.generation; session.expire(105.01); session.expire(110.)
        self.assertEqual(session.last_client_frame, 101.)
        self.assertEqual(session.generation, token)
        self.assertFalse(session.assigned)
        self.assertFalse(session.begin_handoff((2, 20, 'game'), 110., generation=token, new_game_window=True))

    def test_late_duplicate_unknown_swap_and_revoked_generation_remain_rejected(self):
        for kind in ('late', 'duplicate', 'unknown', 'swap', 'stop', 'permission'):
            with self.subTest(kind=kind):
                session = SelectionSession(); session.start(CLIENT)
                session.observe_client(assigned(), CLIENT, 100., 102., generation=session.generation)
                token = session.generation; session.expire(104.1)
                value = assigned(); captured = 102.26; now = 104.26; window = CLIENT
                if kind == 'late': now = 106.261
                elif kind == 'duplicate': captured = 100.; now = 104.
                elif kind == 'unknown': value = {'scene': 'unknown'}
                elif kind == 'swap': value = assigned('9002')
                elif kind == 'stop': session.stop()
                else: window = (9, 99, 'other')
                self.assertFalse(session.observe_client(value, window, captured, now, generation=token))
                self.assertFalse(session.assigned)


try:
    from PySide6 import QtGui, QtWidgets
    from PIL import Image
    import test_native_design as design_fixtures
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt/PIL runtime unavailable')
class ClientDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        design_fixtures.NativeDesignTests.setUpClass.__func__(cls)

    setUp = design_fixtures.NativeDesignTests.setUp if QtWidgets else lambda self: None
    pump = design_fixtures.NativeDesignTests.pump if QtWidgets else lambda self, *args: None
    dispose = design_fixtures.NativeDesignTests.dispose if QtWidgets else lambda self: None

    def prepare_client(self):
        from screen_capture import WindowInfo, ClientRect
        w = self.window; self.hero = next(iter(w.data['heroes']))
        w.data['heroes'][self.hero].update(championId='9001', overallTier='T5')
        w.target = WindowInfo(*CLIENT[:2], 'owned client', CLIENT[2]); w.state.start(w.target.identity)
        w.selection_session = SelectionSession(); w.selection_session.start(CLIENT)
        self.proof = {'allowed': True, 'foreground': True, 'rect': ClientRect(0, 0, 1280, 720)}
        proof = self.proof
        class Capture:
            def rect(self, target): return proof['rect']
            def foreground(self, target): return proof['foreground']
        w.capture = Capture(); w.target_allowed = lambda: self.proof['allowed']; w.queue_discovery = lambda **kw: None
        w.automatic_policy = SimpleNamespace(stop=lambda: None, bound=None)
        w.portrait_bank.replace({'9001': Image.new('RGB', (120, 120), (220, 30, 60))})
        return w

    def deliver(self, captured, now, *, champion='9001', scene='assigned-selection', tokens=None, rect=None):
        w = self.window; session = w.selection_session
        state_token, session_token = tokens or (w.state.generation, session.generation)
        value = dict(assigned(champion), scene=scene, _capturedAt=captured,
                     _sessionGeneration=session_token, _windowIdentity=CLIENT,
                     _captureRect=rect or self.proof['rect'])
        with patch('native_ui.time.monotonic', return_value=now):
            w.task_result('selection', value, state_token)
        w.monitor.stop()

    @staticmethod
    def center_color(label):
        image = label.pixmap().toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2).getRgb()[:3]

    def test_same_fresh_client_reference_has_no_hide_or_structural_rebuild(self):
        from PySide6 import QtCore
        w=self.prepare_client();self.deliver(100.,100.1);self.deliver(101.,101.1)
        self.assertTrue(w.overlay.isVisible());revision=w.overlay._layout_revision;hides=[]
        class Observer(QtCore.QObject):
            def eventFilter(inner,obj,event):
                if event.type()==QtCore.QEvent.Type.Hide:hides.append(1)
                return False
        observer=Observer(w.overlay);w.overlay.installEventFilter(observer)
        w._visible_previous=True;w.overlay.set_rechecking(True)
        self.deliver(102.,102.1)
        self.assertTrue(w.overlay.isVisible());self.assertEqual(hides,[])
        self.assertEqual(w.overlay._layout_revision,revision);self.assertFalse(w.overlay._rechecking)
        self.deliver(103.,103.1,scene='unknown')
        self.assertFalse(w.overlay.isVisible());self.assertTrue(hides)

    def test_fresh_held_second_result_survives_visible_expiry(self):
        w = self.prepare_client(); self.deliver(100., 102.)
        tokens = (w.state.generation, w.selection_session.generation)
        w.ocr_busy = True; w.capture_pending = True; w.ocr_started = 102.26
        with patch('native_ui.time.monotonic', return_value=104.1): w.check_target()
        self.assertEqual((w.state.generation, w.selection_session.generation), tokens)
        self.assertFalse(w.overlay.isVisible()); self.assertFalse(w.state.hero)
        self.assertEqual(w.hero_title.text(), '等待识别')
        self.assertFalse(w._capture_cancel.is_set())
        self.deliver(102.26, 104.26, tokens=tokens)
        self.assertEqual(w.state.hero, self.hero); self.assertEqual(w.selection_session.candidate_frames, 2)
        self.assertTrue(w.overlay.isVisible()); self.assertIn('T5', w.hero_caption.text())
        self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.assertEqual(self.center_color(w.overlay.hero_portrait), (220, 30, 60))

    def test_active_carried_and_verified_game_session_do_not_cancel_fresh_held_result(self):
        from native_state import display_cards
        from screen_capture import WindowInfo
        for verified in (False, True):
            with self.subTest(verified=verified):
                w = self.prepare_client(); self.deliver(100., 100.1); self.deliver(101., 101.1)
                session = w.selection_session; game = WindowInfo(2, 20, 'owned game', 'game')
                session.begin_handoff(game.identity, 102., generation=session.generation, new_game_window=True)
                session.observe_game(game.identity, 103., 105., generation=session.generation,
                                     game_scene=True, hud_hero='9001' if verified else None)
                w.target = game; w.state.target = game.identity; w.last_rect = self.proof['rect']; w.was_target_foreground = True
                names = list(w.data['augments'])[:3]
                w.state.hero = self.hero; w.state.hero_observed = self.hero; w.state.hero_stable_frames = 2
                for _ in range(2):
                    w.state.observe(names, generation=w.state.generation); w.state.observe_automatic_candidates(names, True)
                w.state.confirm(names, names, automatic=True); w.last_observation = 103.
                w.overlay.set_cards(self.hero, display_cards(w.data, self.hero, names)); w.overlay.show()
                tokens = (w.state.generation, session.generation)
                w.ocr_busy = True; w.capture_pending = True; w.ocr_started = 105.76
                with patch('native_ui.time.monotonic', return_value=107.1): w.check_target()
                self.assertEqual(session.stage, 'game-expired'); self.assertEqual((w.state.generation, session.generation), tokens)
                self.assertFalse(w.state.hero); self.assertFalse(w.overlay.isVisible()); self.assertFalse(w._capture_cancel.is_set())
                candidates = [{'name': name, 'recognized_text': name, 'match_method': 'exact', 'ocr_confidence': .99,
                               'box': [[x-40, 150], [x+40, 150], [x+40, 180], [x-40, 180]]}
                              for x, name in zip((150, 450, 750), names)]
                result = {'_capturedAt': 105.76, '_sessionGeneration': tokens[1], '_windowIdentity': game.identity,
                          '_captureRect': self.proof['rect'], 'hero_observation': {'confident': verified,
                          'championId': '9001' if verified else None, 'hero': self.hero if verified else None},
                          'automatic_candidates': candidates, 'candidates': candidates, 'image_size': {'width': 900, 'height': 400}}
                with patch('native_ui.time.monotonic', return_value=107.76): w.task_result('ocr', result, tokens[0])
                w.monitor.stop()
                self.assertTrue(w.state.confirmed); self.assertEqual(w.state.hero, self.hero)
                self.assertEqual(session.visible_identity(allow_provisional=True)['verified'], verified)
                self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))

    def test_held_result_cannot_survive_hard_revocation(self):
        from screen_capture import ClientRect
        for kind in ('stop', 'focus', 'permission', 'geometry', 'edit', 'handoff'):
            with self.subTest(kind=kind):
                w = self.prepare_client(); self.deliver(100., 102.)
                tokens = (w.state.generation, w.selection_session.generation); rect = self.proof['rect']
                w.ocr_busy = True; w.capture_pending = True; w.ocr_started = 102.26
                with patch('native_ui.time.monotonic', return_value=104.1):
                    w.check_target()
                    if kind == 'stop': w.stop_monitor()
                    elif kind == 'edit': w.edit_changed()
                    elif kind == 'handoff': w.invalidate_scene('Owned handoff revocation')
                    else:
                        if kind == 'focus': self.proof['foreground'] = False
                        elif kind == 'permission': self.proof['allowed'] = False
                        else: self.proof['rect'] = ClientRect(0, 0, 1200, 720)
                        w.check_target()
                self.deliver(102.26, 104.26, tokens=tokens, rect=rect)
                self.assertFalse(w.state.hero); self.assertFalse(w.overlay.isVisible())
                self.assertEqual(w.hero_title.text(), '等待识别')

    def test_expired_game_held_result_cannot_survive_authority_revocation_or_unknown_scene(self):
        from screen_capture import ClientRect, WindowInfo
        for kind in ('stop', 'focus', 'permission', 'identity', 'geometry', 'edit', 'unknown'):
            with self.subTest(kind=kind):
                w = self.prepare_client(); self.deliver(100., 100.1); self.deliver(101., 101.1)
                session = w.selection_session; game = WindowInfo(2, 20, 'owned game', 'game')
                session.begin_handoff(game.identity, 102., generation=session.generation, new_game_window=True)
                session.observe_game(game.identity, 103., 105., generation=session.generation, game_scene=True, hud_hero='9001')
                w.target = game; w.state.target = game.identity; w.last_rect = self.proof['rect']; w.was_target_foreground = True
                w.state.hero = self.hero; w.state.hero_observed = self.hero; w.state.hero_stable_frames = 2
                tokens = (w.state.generation, session.generation); rect = self.proof['rect']
                w.ocr_busy = True; w.capture_pending = True; w.ocr_started = 105.76
                with patch('native_ui.time.monotonic', return_value=107.1):
                    w.check_target(); self.assertEqual(session.stage, 'game-expired')
                    if kind == 'stop': w.stop_monitor()
                    elif kind == 'edit': w.edit_changed()
                    elif kind != 'unknown':
                        if kind == 'focus': self.proof['foreground'] = False
                        elif kind == 'permission': self.proof['allowed'] = False
                        elif kind == 'geometry': self.proof['rect'] = ClientRect(0, 0, 1200, 720)
                        else: w.target = WindowInfo(3, 30, 'other game', 'game')
                        w.check_target()
                result = {'_capturedAt': 105.76, '_sessionGeneration': tokens[1], '_windowIdentity': game.identity,
                          '_captureRect': rect, 'hero_observation': {'confident': kind != 'unknown',
                          'championId': '9001', 'hero': self.hero}, 'automatic_candidates': [], 'candidates': [],
                          'image_size': {'width': 900, 'height': 400}}
                with patch('native_ui.time.monotonic', return_value=107.76): w.task_result('ocr', result, tokens[0])
                w.monitor.stop(); self.assertFalse(w.state.hero); self.assertFalse(w.overlay.isVisible())
                if kind == 'unknown': self.assertFalse(session.carried)

    def test_dashboard_and_strip_pixels_clear_on_expiry_unknown_and_stop(self):
        w = self.prepare_client(); self.deliver(100., 100.1); self.deliver(101., 101.1)
        self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        with patch('native_ui.time.monotonic', return_value=105.01): w.check_target()
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.assertEqual(w.hero_title.text(), '等待识别'); self.assertFalse(w.overlay.isVisible())
        self.deliver(103., 105.1); self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.deliver(106., 106.1, scene='unknown')
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.deliver(107., 107.1); self.deliver(108., 108.1); w.stop_monitor()
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))

    def test_dashboard_age_guard_does_not_need_watchdog_first(self):
        w = self.prepare_client(); self.deliver(100., 100.1); self.deliver(101., 101.1)
        with patch('native_ui.time.monotonic', return_value=105.01): w.refresh_dashboard()
        self.assertEqual(w.hero_title.text(), '等待识别'); self.assertNotIn('T5', w.hero_caption.text())
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))

    def test_swap_replaces_exact_portrait_only_after_new_assignment_stability(self):
        w = self.prepare_client(); other = next(name for name in w.data['heroes'] if name != self.hero)
        w.data['heroes'][other].update(championId='9002', overallTier='T2')
        w.portrait_bank.replace({'9001': Image.new('RGB', (120, 120), (220, 30, 60)),
                                '9002': Image.new('RGB', (120, 120), (30, 80, 220))})
        self.deliver(100., 100.1); self.deliver(101., 101.1)
        self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.deliver(102., 102.1, champion='9002')
        self.assertEqual(w.hero_title.text(), '等待识别'); self.assertFalse(w.overlay.isVisible())
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.deliver(103., 103.1, champion='9002')
        self.assertEqual(w.hero_title.text(), other); self.assertIn('T2', w.hero_caption.text())
        self.assertEqual(self.center_color(w.hero_avatar), (30, 80, 220))
        self.assertEqual(self.center_color(w.overlay.hero_portrait), (30, 80, 220))

    def test_manual_hero_tier_is_only_labeled_dictionary_reference(self):
        w = self.prepare_client(); w.hero_auto.setChecked(False); w.hero_box.setCurrentText(self.hero)
        w.refresh_dashboard()
        self.assertIn('人工查阅英雄', w.hero_caption.text()); self.assertIn('T5', w.hero_caption.text())
        self.assertIn('人工选择', w.status_chip.text()); self.assertIsNone(w.client_strength_reference())
        self.assertFalse(w.overlay.isVisible()); self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))

    def test_verified_bank_arriving_later_refreshes_actual_pixels_without_new_identity(self):
        w = self.prepare_client(); w.portrait_bank.replace({})
        self.deliver(100., 100.1); self.deliver(101., 101.1)
        self.assertNotEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        with patch('native_ui.time.monotonic', return_value=101.2), patch('hero_recognition.PortraitMatcher'):
            deliver_portraits(w, ({'9001': Image.new('RGB', (120, 120), (220, 30, 60))}, {'message': 'owned bank'}))
        self.assertEqual(self.center_color(w.hero_avatar), (220, 30, 60))
        self.assertEqual(self.center_color(w.overlay.hero_portrait), (220, 30, 60))

    def test_alias_detector_rebuilds_only_when_verified_roster_availability_changes(self):
        w = self.window; sentinel = object(); w.selection_detector = sentinel
        deliver_portraits(w, ({}, {})); self.assertIs(w.selection_detector, sentinel)
        folder = Path(w.state_dir) / 'hero-portraits'; folder.mkdir()
        roster = b'{"data":{}}'; (folder / 'roster-16.1.1.json').write_bytes(roster)
        (folder / 'manifest.json').write_text(json.dumps({'version': '16.1.1', 'rosterSha256': hashlib.sha256(roster).hexdigest()}))
        deliver_portraits(w, ({}, {})); self.assertIsNone(w.selection_detector)
        w.selection_detector = sentinel; deliver_portraits(w, ({}, {}))
        self.assertIs(w.selection_detector, sentinel)

    def test_bank_is_bounded_detached_exact_id_and_neutral_on_missing_or_ambiguous_mapping(self):
        from portrait_display import PortraitDisplayBank
        bank = PortraitDisplayBank(); source = Image.new('RGB', (512, 512), (20, 150, 70))
        bank.replace({'9001': source, 'bad': source}); source.paste((0, 0, 0), (0, 0, 512, 512))
        self.assertEqual(len(bank._images), 1); self.assertLessEqual(bank._images['9001'].width(), 128)
        self.assertEqual(bank.pixmap('9001', 40).toImage().pixelColor(20, 20).getRgb()[:3], (20, 150, 70))
        self.assertIsNone(bank.pixmap('09001', 40)); self.assertIsNone(bank.pixmap(9001, 40))
        data = {'heroes': {'one': {'championId': '9001'}}}
        self.assertEqual(bank.hero_id(data, 'one'), '9001'); self.assertIsNone(bank.hero_id(data, 'alias'))
        data['heroes']['two'] = {'championId': '9001'}; self.assertIsNone(bank.hero_id(data, 'one'))
        bank.replace({str(i): Image.new('RGB', (64, 64)) for i in range(401)})
        self.assertEqual(bank._images, {})

    def test_overlay_portrait_also_rejects_ambiguous_or_mismatched_canonical_mapping(self):
        w = self.prepare_client(); self.deliver(100., 100.1); self.deliver(101., 101.1)
        reference = dict(w.overlay.reference)
        self.assertEqual(self.center_color(w.overlay.hero_portrait), (220, 30, 60))
        w.data['heroes']['ambiguous'] = {'championId': '9001'}
        w.overlay.set_hero_reference(reference)
        self.assertNotEqual(self.center_color(w.overlay.hero_portrait), (220, 30, 60))
        del w.data['heroes']['ambiguous']; reference['championId'] = '9002'
        w.overlay.set_hero_reference(reference)
        self.assertNotEqual(self.center_color(w.overlay.hero_portrait), (220, 30, 60))


if __name__ == '__main__':
    unittest.main()
