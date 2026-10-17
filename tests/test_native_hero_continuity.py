"""Owned Qt state observations, not a live game or Windows capture claim."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tests import test_native_capture_worker as fixtures


@unittest.skipIf(fixtures.QtWidgets is None,'Qt unavailable')
class NativeHeroContinuityTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixtures.NativeCaptureWorkerTests.setUp
    wait=fixtures.NativeCaptureWorkerTests.wait
    dispose_window=fixtures.NativeCaptureWorkerTests.dispose_window

    def prepare(self):
        from native_ui import ControlWindow
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        w=self.window;self.hero=next(iter(w.data['heroes']));w.data['heroes'][self.hero]['championId']='103'
        self.names=list(w.data['augments']);self.rect=ClientRect(0,0,1280,720)
        self.meta=ProcessMetadata('C:/Riot/League/Game/League of Legends.exe',12345)
        w.automatic_policy=SimpleNamespace(bound=SimpleNamespace(role='game',metadata=self.meta),stop=lambda:None)
        w.capture_metadata=lambda:self.meta;w.last_rect=self.rect
        self.scope=(w.target.identity,self.meta,self.rect,tuple(x.value()/100 for x in w.roi),tuple(w.data['augments']),
                    (id(w.data),json.dumps(w.data.get('metadata',{}),sort_keys=True,ensure_ascii=False)),(None,None))
        self.raw={'hero':self.hero,'championId':'103','confident':True,'method':'own-hud-portrait'}
        self.unknown={'hero':None,'championId':None,'confident':False,'method':'own-hud-portrait','abstentionKind':'portrait-unavailable'}
        self.serial=0
        return w
    def value(self,stamp,names=None,raw=None):
        self.serial+=1
        names=self.names[:3] if names is None else names
        candidates=[{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,
            'box':[[x-40,150],[x+40,150],[x+40,180],[x-40,180]]} for x,name in zip((150,450,750),names)]
        return {'automatic_candidates':candidates,'candidates':candidates,'image_size':{'width':900,'height':400},
            'hero_observation':dict(self.raw if raw is None else raw),'_capturedAt':stamp,'_captureSerial':self.serial,
            '_identityMapping':(('103',self.hero),),'_windowIdentity':self.window.target.identity,'_captureRect':self.rect,'_frameScope':self.scope}
    def deliver(self,stamp,**kwargs):
        w=self.window;value=self.value(stamp,**kwargs)
        with patch('native_ui.time',SimpleNamespace(monotonic=lambda:stamp+.01)):
            w.task_result('ocr',value,w.state.generation)
        return value
    def test_countdown_uses_separate_identity_and_new_cards_not_new_hud_confidence(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        self.assertTrue(w.state.confirmed);proof_time=w.hero_continuity.verified_at;strong_count=w.state.hero_stable_frames
        result=self.deliver(110.,raw=self.unknown)
        self.assertFalse(result['hero_observation']['confident'])
        self.assertEqual(w.state.hero,self.hero);self.assertEqual(w.hero_origin,'game-continuity')
        self.deliver(111.,raw=self.unknown)
        self.assertTrue(w.state.confirmed);self.assertEqual(w.state.offered,tuple(self.names[:3]))
        self.assertEqual(w.hero_continuity.verified_at,proof_time)
        self.assertLessEqual(w.state.hero_stable_frames,strong_count)
    def test_no_cards_hides_tiers_but_keeps_private_same_game_seed(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        self.deliver(102.,names=[],raw=self.unknown)
        self.assertFalse(w.state.confirmed);self.assertFalse(w.state.hero)
        self.assertEqual(w.hero_continuity.hero,self.hero)
        self.deliver(103.,raw=self.unknown);self.deliver(104.,raw=self.unknown)
        self.assertTrue(w.state.confirmed);self.assertEqual(w.state.hero,self.hero)
    def test_fresh_conflict_revokes_before_final_ocr(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        value=self.value(102.,raw={'hero':'different','championId':'55','confident':True,'method':'own-hud-portrait'})
        w._capture_serial=value['_captureSerial'];w.ocr_busy=True
        with patch('native_ui.time',SimpleNamespace(monotonic=lambda:102.01)):
            w.task_result('capture-proof',value,w.state.generation)
        self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed);self.assertFalse(w.hero_continuity.hero)
        self.assertTrue(w.ocr_busy)
    def test_same_name_different_id_revokes_during_held_ocr(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        value=self.value(102.,raw={**self.raw,'championId':'104'})
        w._capture_serial=value['_captureSerial'];w.ocr_busy=True
        with patch('native_ui.time',SimpleNamespace(monotonic=lambda:102.01)):
            w.task_result('capture-proof',value,w.state.generation)
        self.assertFalse(w.state.hero);self.assertFalse(w.hero_continuity.hero)
        self.assertTrue(w.ocr_busy)
    def test_new_process_metadata_and_stop_cannot_carry(self):
        from session_windows import ProcessMetadata
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        self.meta=ProcessMetadata(self.meta.path,99999)
        self.deliver(102.,raw=self.unknown);self.assertFalse(w.state.hero);self.assertFalse(w.hero_continuity.hero)
        w.stop_monitor();self.assertIsNone(w.hero_continuity.scope)
    def test_focus_and_resize_clear_cards_but_keep_same_game_identity(self):
        from screen_capture import ClientRect
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        seed=w.hero_continuity.verified_at
        w.invalidate_scene('Focus lost',debug_reason='focus_lost')
        self.assertFalse(w.state.confirmed);self.assertEqual(w.hero_continuity.hero,self.hero)
        self.rect=ClientRect(0,0,1600,900);w.last_rect=self.rect
        self.scope=(*self.scope[:2],self.rect,*self.scope[3:])
        w.invalidate_scene('Resized',debug_reason='geometry_changed')
        self.assertEqual(w.hero_continuity.hero,self.hero)
        self.deliver(1000.,raw=self.unknown);self.deliver(1001.,raw=self.unknown)
        self.assertTrue(w.state.confirmed);self.assertEqual(w.hero_continuity.verified_at,seed)
        w.invalidate_scene('Source changed')
        self.assertFalse(w.hero_continuity.hero)
    def test_stale_selection_callback_does_not_clear_game_identity(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        w.task_result('selection',{},w.state.generation-1)
        self.assertEqual(w.hero_continuity.hero,self.hero);self.assertTrue(w.state.confirmed)
    def test_stale_error_preserves_new_job_but_releases_own_drain(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        current=w.state.generation;w.ocr_busy=True;w._active_capture_generation=current
        w.task_error('selection','old failure',current-1)
        self.assertTrue(w.ocr_busy);self.assertEqual(w.hero_continuity.hero,self.hero)
        w._active_capture_generation=current-1
        w.task_error('ocr','invalidated job ended',current-1)
        self.assertFalse(w.ocr_busy);self.assertEqual(w.hero_continuity.hero,self.hero)
        w.ocr_busy=True;w._active_capture_generation=current-1
        w.task_result('selection',{},current-1)
        self.assertFalse(w.ocr_busy);self.assertEqual(w.hero_continuity.hero,self.hero)
    def test_in_place_canonical_mapping_change_revokes_identity(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        w.data['heroes'][self.hero]['championId']='104'
        self.deliver(102.,raw=self.unknown)
        self.assertFalse(w.state.hero);self.assertFalse(w.hero_continuity.hero)
    def test_repeated_death_observations_never_renew_strong_identity(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        seed=w.hero_continuity.verified_at
        for stamp in (500.,501.,502.,503.):
            self.deliver(stamp,raw=self.unknown)
            self.assertEqual(w.state.hero,self.hero)
        self.assertTrue(w.state.confirmed);self.assertEqual(w.hero_continuity.verified_at,seed)
    def test_permission_default_and_minimize_preference_are_distinct(self):
        w=self.window
        self.assertTrue(w.live_identity_toggle.isChecked());self.assertFalse(w.lcu_toggle.isChecked())
        self.assertFalse(w.minimize_on_start.isChecked())
        w.live_identity_toggle.setChecked(False);w.minimize_on_start.setChecked(True)
        from monitor_preferences import load_preferences
        self.assertEqual(load_preferences(w.state_dir),{'live_identity':False,'minimize_on_start':True})
