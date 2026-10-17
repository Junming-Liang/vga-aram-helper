"""Same-game continuity is separate from current portrait confidence."""
import copy
import unittest
from hero_identity_continuity import HeroIdentityContinuity


class HeroContinuityTests(unittest.TestCase):
    def setUp(self):
        self.c=HeroIdentityContinuity()
        self.scope=((1,2,'RiotWindowClass'),('verified-game-path',1234),'source-v1')
        self.good={'hero':'Ahri','championId':'103','confident':True,'method':'own-hud-portrait'}
        self.unknown={'hero':None,'championId':None,'confident':False,
            'method':'own-hud-portrait','abstentionKind':'portrait-unavailable'}
    def observe(self,value=None,stamp=100.,serial=1,scope=None,now=None):
        return self.c.observe(self.good if value is None else value,
            scope=self.scope if scope is None else scope,captured_at=stamp,
            now=stamp if now is None else now,serial=serial)
    def seed(self,method='own-hud-portrait'):
        good=dict(self.good,method=method)
        self.assertFalse(self.observe(good))
        self.assertTrue(self.observe(good,stamp=101.,serial=2))
    def recover(self,value=None,**kwargs):
        args=dict(scope=self.scope,captured_at=110.,now=110.,fresh_card_scene=True,
            ocr_reused=False,serial=3);args.update(kwargs)
        return self.c.recover(self.unknown if value is None else value,**args)
    def eligible(self,value=None,**kwargs):
        args=dict(scope=self.scope,captured_at=110.,now=110.,serial=3);args.update(kwargs)
        return self.c.eligible(self.unknown if value is None else value,**args)
    def test_two_independent_strong_captures_for_hud_and_api(self):
        for method in ('own-hud-portrait','game-client-api'):
            with self.subTest(method=method):
                self.setUp();good=dict(self.good,method=method)
                self.assertFalse(self.observe(good));self.assertIsNone(self.c.verified_at)
                self.assertFalse(self.observe(good,stamp=100.,serial=1));self.assertEqual(self.c.frames,1)
                self.assertTrue(self.observe(good,stamp=101.,serial=2))
                recovered=self.recover();self.assertEqual(recovered['hero'],'Ahri')
                self.assertEqual(recovered['championId'],'103')
                self.assertEqual(recovered['method'],'same-game-hero-continuity')
                self.assertNotIn('confident',recovered)
    def test_serial_and_timestamp_must_both_strictly_increase(self):
        for stamp,serial in ((101.,1),(101.,0),(101.,-1),(101.,True),(101.,1.5),(100.,2),(99.9,2)):
            with self.subTest(stamp=stamp,serial=serial):
                self.setUp();self.observe()
                self.assertFalse(self.observe(stamp=stamp,serial=serial));self.assertIsNone(self.c.verified_at)
        self.setUp();self.observe(stamp=100.,serial=10)
        self.assertFalse(self.observe(stamp=101.,serial=9));self.assertEqual(self.c.frames,1)
        self.assertTrue(self.observe(stamp=101.,serial=11))
    def test_unknown_interrupts_pending_strong_streak(self):
        for method in ('own-hud-portrait','game-client-api'):
            with self.subTest(method=method):
                self.setUp();good=dict(self.good,method=method);self.observe(good)
                self.assertFalse(self.observe(self.unknown,stamp=101.,serial=2));self.assertEqual(self.c.frames,0)
                self.assertFalse(self.observe(good,stamp=102.,serial=3));self.assertIsNone(self.c.verified_at)
                self.assertTrue(self.observe(good,stamp=103.,serial=4))
    def test_pending_strong_frame_gap_boundary(self):
        for gap,expected in ((4.,True),(4.001,False)):
            with self.subTest(gap=gap):
                self.setUp();self.observe();self.assertEqual(self.observe(stamp=100.+gap,serial=2),expected)
    def test_unknown_without_cards_retains_only_private_identity(self):
        self.seed();original=(self.c.verified_at,self.c.frames)
        self.assertIsNone(self.recover(fresh_card_scene=False))
        self.assertFalse(self.observe(self.unknown,stamp=110.,serial=3))
        self.assertEqual((self.c.verified_at,self.c.frames),original)
        self.assertEqual(self.recover(captured_at=130.,now=130.,serial=4)['hero'],'Ahri')
        self.assertEqual((self.c.verified_at,self.c.frames),original)
    def test_unknown_candidate_box_and_low_score_are_not_identity_proof(self):
        for changes in ({'candidateChampionId':'55'},{'box':[400,800,60,60]},
                        {'candidateChampionId':None,'box':None},{'score':0.1,'margin':0.0}):
            with self.subTest(changes=changes):
                self.setUp();self.seed();value=dict(self.unknown,**changes)
                self.assertEqual(self.recover(value)['championId'],'103')
                self.assertFalse(self.observe(value,stamp=110.,serial=3));self.assertEqual(self.c.verified_at,101.)
    def test_api_unavailability_with_supported_hud_uses_prior_api_identity(self):
        self.seed('game-client-api');fallback=dict(self.unknown,_liveIdentityUnavailable=True)
        self.assertEqual(self.recover(fallback)['championId'],'103')
        self.assertFalse(fallback['confident']);self.assertIsNone(fallback['championId'])
    def test_unknown_api_always_revokes(self):
        for fields in ({},{'unavailable':True},{'abstentionKind':'portrait-unavailable'}):
            with self.subTest(fields=fields):
                self.setUp();self.seed();value={**self.unknown,'method':'game-client-api',**fields}
                self.assertFalse(self.eligible(value));self.assertIsNone(self.recover(value))
                self.assertIsNone(self.c.verified_at)
    def test_unsupported_or_unstructured_abstention_revokes(self):
        variants=(None,{},dict(self.unknown,abstentionKind=None),
            dict(self.unknown,abstentionKind='unsupported-layout'),
            dict(self.unknown,abstentionKind='unsupported-layout',occlusionKind='death-portrait'),
            dict(self.unknown,conflict=True),dict(self.unknown,method='other'))
        for value in variants:
            with self.subTest(value=value):
                self.setUp();self.seed()
                self.assertFalse(self.c.observe(value,scope=self.scope,captured_at=110.,now=110.,serial=3))
                self.assertIsNone(self.recover(captured_at=111.,now=111.,serial=4))
    def test_legacy_death_marker_needs_no_candidate_or_box(self):
        self.seed();value={'confident':False,'method':'own-hud-portrait','occlusionKind':'death-portrait'}
        self.assertEqual(self.recover(value)['hero'],'Ahri')
    def test_different_confident_hero_or_id_revokes_and_old_result_cannot_restore(self):
        for changes in ({'hero':'Katarina','championId':'55'},{'championId':'55'},
                        {'hero':'Katarina'},{'conflict':True}):
            with self.subTest(changes=changes):
                self.setUp();self.seed()
                self.assertFalse(self.observe(dict(self.good,**changes),stamp=110.,serial=3))
                self.assertIsNone(self.c.verified_at)
                self.assertFalse(self.observe(stamp=109.,serial=2));self.assertIsNone(self.c.verified_at)
    def test_changed_process_window_source_session_cannot_borrow(self):
        for scope in (((1,2,'RiotWindowClass'),('verified-game-path',9999),'source-v1'),
                      ((2,3,'RiotWindowClass'),('verified-game-path',1234),'source-v1'),
                      ((1,2,'RiotWindowClass'),('verified-game-path',1234),'source-v2'),(self.scope,'new-session')):
            with self.subTest(scope=scope):
                self.setUp();self.seed();self.assertFalse(self.eligible(scope=scope))
                self.assertIsNone(self.recover(scope=scope));self.assertIsNone(self.recover())
    def test_scope_change_requires_two_new_strong_captures(self):
        self.seed();scope=(self.scope,'new-process')
        self.assertFalse(self.observe(stamp=110.,serial=3,scope=scope))
        self.assertTrue(self.observe(stamp=111.,serial=4,scope=scope))
        self.assertEqual(self.recover(scope=scope,captured_at=112.,now=112.,serial=5)['hero'],'Ahri')
    def test_empty_scope_never_establishes_or_recovers(self):
        for scope in (None,(),False):
            with self.subTest(scope=scope):
                self.setUp();self.seed()
                self.assertFalse(self.c.observe(self.good,scope=scope,captured_at=110.,now=110.,serial=3))
                self.assertIsNone(self.recover())
    def test_eligible_is_nonmutating_and_proof_final_duplicate_safe(self):
        self.seed();before=copy.deepcopy(vars(self.c))
        for _ in range(3):self.assertTrue(self.eligible())
        self.assertEqual(vars(self.c),before)
        self.assertEqual(self.recover()['hero'],'Ahri');self.assertIsNone(self.recover())
        self.assertFalse(self.observe(self.unknown,stamp=110.,serial=3))
        self.assertFalse(self.observe(self.unknown,stamp=110.,serial=3));self.assertFalse(self.eligible())
        self.assertEqual(self.c.verified_at,101.);self.assertEqual(self.c.frames,2)
    def test_failed_eligible_does_not_mutate(self):
        self.seed();before=copy.deepcopy(vars(self.c))
        for args in ({'scope':('wrong',)},{'now':230.},{'captured_at':100.},{'serial':2},{'serial':1},{'serial':True}):
            with self.subTest(args=args):self.assertFalse(self.eligible(**args))
        self.assertFalse(self.eligible(dict(self.unknown,method='game-client-api')))
        self.assertEqual(vars(self.c),before)
    def test_cached_or_missing_cards_never_display_or_renew(self):
        for fields in ({'ocr_reused':True},{'ocr_reused':1},{'fresh_card_scene':False},{'fresh_card_scene':1}):
            with self.subTest(fields=fields):
                self.setUp();self.seed();before=copy.deepcopy(vars(self.c))
                self.assertIsNone(self.recover(**fields));self.assertEqual(vars(self.c),before)
    def test_recovery_requires_distinct_newer_capture_and_serial(self):
        for fields in ({'serial':2},{'serial':1},{'serial':None},{'serial':True},{'serial':3.0},
                       {'captured_at':101.,'now':101.}):
            with self.subTest(fields=fields):
                self.setUp();self.seed();self.assertIsNone(self.recover(**fields))
        self.setUp();self.seed();self.assertIsNotNone(self.recover())
        self.assertIsNone(self.recover(captured_at=111.,now=111.,serial=3))
        self.assertIsNone(self.recover(captured_at=110.,now=110.,serial=4))
    def test_stale_future_nonfinite_boolean_frames_never_recover(self):
        for fields in ({'captured_at':100.,'now':110.},{'captured_at':111.,'now':110.},
                       {'captured_at':float('nan')},{'now':float('inf')},{'now':True}):
            with self.subTest(fields=fields):
                self.setUp();self.seed();self.assertIsNone(self.recover(**fields))
    def test_frame_age_boundary(self):
        for age,expected in ((4.,True),(4.001,False)):
            with self.subTest(age=age):
                self.setUp();self.seed()
                self.assertEqual(self.recover(captured_at=110.,now=110.+age) is not None,expected)
    def test_whole_verified_game_retains_identity_without_renewing_proof(self):
        self.seed()
        for serial,stamp in enumerate((110.,300.,3600.,21600.),3):
            self.assertIsNone(self.recover(captured_at=stamp,now=stamp,serial=serial,ocr_reused=True))
            self.assertFalse(self.observe(self.unknown,stamp=stamp,serial=serial))
            self.assertEqual(self.c.verified_at,101.);self.assertEqual(self.c.frames,2)
        self.assertIsNotNone(self.recover(captured_at=86400.,now=86400.,serial=7))
        self.assertEqual(self.c.verified_at,101.);self.assertEqual(self.c.frames,2)
        self.assertIsNone(self.recover(captured_at=86401.,now=86405.001,serial=8))
    def test_genuine_same_hero_refreshes_proof_after_long_unknown_interval(self):
        self.seed();self.observe(self.unknown,stamp=150.,serial=3)
        self.assertTrue(self.observe(stamp=3600.,serial=4));self.assertEqual(self.c.verified_at,3600.)
        self.assertEqual(self.recover(captured_at=7200.,now=7200.,serial=5)['hero'],'Ahri')
    def test_long_death_without_cards_keeps_original_strong_proof(self):
        self.seed()
        self.assertIsNone(self.recover(captured_at=500.,now=500.,serial=3,fresh_card_scene=False))
        self.assertFalse(self.observe(self.unknown,stamp=500.,serial=3))
        self.assertTrue(self.eligible(captured_at=1000.,now=1000.,serial=4))
        self.assertEqual(self.recover(captured_at=1000.,now=1000.,serial=4)['hero'],'Ahri')
        self.assertEqual(self.c.verified_at,101.);self.assertEqual(self.c.frames,2)
    def test_stop_reacquisition_needs_two_frames(self):
        self.seed();self.c.clear();self.assertIsNone(self.recover())
        self.assertFalse(self.observe(stamp=111.,serial=3));self.assertTrue(self.observe(stamp=112.,serial=4))
    def test_invalid_same_scope_event_keeps_replay_watermark(self):
        self.seed();self.assertFalse(self.observe(stamp=102.,serial=False))
        self.assertIsNone(self.c.verified_at)
        self.assertFalse(self.observe(stamp=100.,serial=1,now=103.))
        self.assertFalse(self.observe(stamp=101.,serial=2,now=103.))
        self.assertIsNone(self.c.verified_at)
        self.setUp();self.seed()
        self.assertIsNone(self.recover(captured_at=111.,now=110.))
        self.assertFalse(self.observe(stamp=101.,serial=2,now=103.))
        self.assertIsNone(self.c.verified_at)
    def test_malformed_identity_never_seeds(self):
        for fields in ({'championId':'0'},{'championId':'0103'},{'championId':'１０３'},
                       {'championId':'1'*5000},{'championId':103},{'hero':' '},
                       {'method':'this-session-client-text'},{'confident':1}):
            with self.subTest(fields=fields):
                self.setUp();value=dict(self.good,**fields)
                self.assertFalse(self.observe(value));self.assertFalse(self.observe(value,stamp=101.,serial=2))
                self.assertIsNone(self.c.verified_at)
    def test_raw_observation_never_modified(self):
        self.seed();value=copy.deepcopy(self.unknown);before=copy.deepcopy(value)
        self.assertTrue(self.eligible(value));self.assertIsNotNone(self.recover(value))
        self.observe(value,stamp=110.,serial=3);self.assertEqual(value,before)

if __name__=='__main__':unittest.main()
