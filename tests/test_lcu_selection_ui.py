"""Owned synthetic Qt checks. No actual League client or credentials accessed."""
import unittest
from unittest.mock import patch
from tests import test_client_feedback as fixtures

@unittest.skipIf(fixtures.QtWidgets is None,'Qt unavailable')
class LCUDisplayTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.ClientDisplayTests.setUpClass.__func__)
    setUp=fixtures.ClientDisplayTests.setUp
    dispose=fixtures.ClientDisplayTests.dispose
    pump=fixtures.ClientDisplayTests.pump
    prepare_client=fixtures.ClientDisplayTests.prepare_client

    def prepare(self):
        self.window.lcu_toggle.setChecked(True)
        w=self.prepare_client()
        names=list(w.data['heroes'])
        w.data['heroes'][names[1]].update(championId='9002',overallTier='T2')
        return w
    def deliver(self,stamp,own='9001',bench=('9002',),method='lcu-read-only'):
        w=self.window
        value={'scene':'assigned-selection' if own else 'initial-cards','assigned':bool(own),'championId':own,'teamChampionIds':('9001',),'benchChampionIds':bench,'method':method,'_capturedAt':stamp,'_sessionGeneration':w.selection_session.generation,'_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=stamp+.1):w.task_result('selection',value,w.state.generation)
        w.monitor.stop()
    def test_opt_in_off_default_and_revokes_on_change(self):
        self.assertFalse(self.window.lcu_toggle.isChecked());w=self.prepare();self.deliver(100.);self.deliver(101.);self.assertTrue(w.overlay.isVisible());w.lcu_toggle.setChecked(False);self.assertFalse(w.state.running);self.assertFalse(w.overlay.isVisible());self.assertIsNone(w.lcu_snapshot.value)
    def test_own_team_bench_literal_tiers(self):
        w=self.prepare();self.deliver(100.);self.assertFalse(w.overlay.isVisible());self.deliver(101.);text=' '.join(x.text() for x in w.overlay.tier_labels);self.assertIn('本人',text);self.assertIn('T5',text);self.assertIn('T2',text);self.assertIn('备选席',text)
    def test_swap_hides_until_second_and_stop_clears(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.);self.deliver(102.,own='9002',bench=());self.assertIsNone(w.lcu_snapshot.value);self.deliver(103.,own='9002',bench=());self.assertIsNotNone(w.lcu_snapshot.value);w.stop_monitor();self.assertIsNone(w.lcu_snapshot.value)
    def test_bench_before_own_assignment_does_not_invent_identity(self):
        w=self.prepare();self.deliver(100.,own=None);self.deliver(101.,own=None);self.assertFalse(w.state.hero);self.assertTrue(w.overlay.isVisible());self.assertIn('T2',' '.join(x.text() for x in w.overlay.tier_labels))
    def test_unknown_method_and_expiry_remove_collection(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        with patch('native_ui.time.monotonic',return_value=105.1):self.assertIsNone(w.client_selection_reference())
        self.deliver(102.,method='screenshot');self.assertIsNone(w.lcu_snapshot.value)

    def test_old_result_cannot_restore_after_consent_change(self):
        w=self.prepare();token=w.state.generation;session=w.selection_session.generation
        self.deliver(100.);w.lcu_toggle.setChecked(False)
        value={'scene':'assigned-selection','assigned':True,'championId':'9001','method':'lcu-read-only','_capturedAt':101.,'_sessionGeneration':session,'_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=101.1):w.task_result('selection',value,token)
        self.assertFalse(w.state.running);self.assertFalse(w.overlay.isVisible());self.assertIsNone(w.lcu_snapshot.value)
    def test_live_identity_default_on_and_explicit_off_revocation(self):
        self.assertTrue(self.window.live_identity_toggle.isChecked())
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        w.live_identity_toggle.setChecked(False)
        self.assertFalse(w.state.running);self.assertIsNone(w.lcu_snapshot.value);self.assertFalse(w.overlay.isVisible())
    def test_api_hud_conflict_cannot_borrow_selection_identity(self):
        from screen_capture import WindowInfo
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        game=WindowInfo(2,20,'owned game','RiotWindowClass')
        w.selection_session.begin_handoff(game.identity,102.,generation=w.selection_session.generation,new_game_window=True)
        token=w.selection_session.generation;w.target=game;w.state.target=game.identity
        value={'hero_observation':{'hero':None,'championId':None,'confident':False,'method':'game-client-api','reason':'conflicting fresh identities'},'candidates':[],'automatic_candidates':[], '_capturedAt':103.,'_sessionGeneration':token,'_windowIdentity':game.identity,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=103.1):w.task_result('ocr',value,w.state.generation)
        w.monitor.stop();self.assertIsNone(w.selection_session);self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed)
    def test_roster_hash_and_canonical_slugs_required(self):
        import json,hashlib
        w=self.window;cache=w.state_dir/'hero-portraits';cache.mkdir(parents=True,exist_ok=True)
        source={'version':'16.17.1','data':{str(i):{'id':'Canonical'+str(i),'key':str(i),'name':'localized '+str(i),'image':{'full':'Canonical'+str(i)+'.png'}} for i in range(1,101)}}
        raw=json.dumps(source).encode();(cache/'roster-16.17.1.json').write_bytes(raw)
        (cache/'manifest.json').write_text(json.dumps({'version':'16.17.1','rosterSha256':hashlib.sha256(raw).hexdigest()}))
        result=w.canonical_champion_map();self.assertEqual(result['Canonical1'],'1');self.assertNotIn('localized 1',result)
        (cache/'roster-16.17.1.json').write_bytes(raw+b' ');self.assertEqual(w.canonical_champion_map(),{})
    def test_stale_game_api_result_after_scope_generation_change_is_ignored(self):
        from screen_capture import WindowInfo
        w=self.prepare();old=w.state.generation;w.live_identity_toggle.setChecked(False)
        game=WindowInfo(2,20,'owned game','RiotWindowClass');w.target=game;w.state.start(game.identity)
        value={'hero_observation':{'hero':self.hero,'championId':'9001','confident':True,'method':'game-client-api'},'_capturedAt':103.,'_windowIdentity':game.identity,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=103.1):w.task_result('ocr',value,old)
        w.monitor.stop();self.assertFalse(w.state.hero);self.assertFalse(w.state.confirmed)
