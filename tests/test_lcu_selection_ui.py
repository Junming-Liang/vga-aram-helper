"""Owned synthetic Qt checks. No actual League client or credentials accessed."""
import unittest
import threading
from unittest.mock import Mock,patch
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
    def test_default_client_dashboard_has_explicit_opt_in_and_restart(self):
        w=self.prepare_client();w.refresh_status_badge()
        self.assertFalse(w.lcu_toggle.isChecked());self.assertFalse(w.selection_optin.isHidden())
        self.assertFalse(w.advanced_panel.isAncestorOf(w.selection_optin_button))
        with patch.object(w,'start_monitor') as restart:w.selection_optin_button.click()
        self.assertTrue(w.lcu_toggle.isChecked());restart.assert_called_once()
        self.assertTrue(w.selection_optin.isHidden())
    def test_own_team_bench_literal_tiers(self):
        w=self.prepare();self.deliver(100.);self.assertFalse(w.overlay.isVisible());self.deliver(101.);text=' '.join(x.text() for x in w.overlay.tier_labels);self.assertIn('本人',text);self.assertIn('T5',text);self.assertIn('T2',text);self.assertIn('备选席',text)

    def test_read_only_selection_does_not_require_pixels_ocr_or_capture_mode(self):
        from screen_capture import CaptureUnavailable
        from session_windows import ProcessMetadata
        w=self.prepare();w.client_phase=lambda:True
        w.capture_metadata=lambda:ProcessMetadata(r'C:\League\LeagueClientUx.exe',1)
        w.capture.capture=Mock(side_effect=CaptureUnavailable('owned unavailable pixel backend'))
        w.capture.prepare_capture_mode=Mock(side_effect=AssertionError('API must not prepare pixel capture'))
        value={'scene':'assigned-selection','assigned':True,'championId':'9001',
               'teamChampionIds':('9001',),'benchChampionIds':('9002',),
               'method':'lcu-read-only','_lcuInstance':(12,100,1)}
        clock=Mock()
        with patch('lcu_selection.LocalSelectionReader') as reader,patch('local_ocr.LocalOCR') as ocr,patch('native_ui.time',clock):
            reader.return_value.read.side_effect=lambda **kwargs:dict(value)
            # Immediate mocked reads can share a coarse Windows clock tick.
            # Model separate observations without changing the real pump clock.
            for stamp in (100.,101.):
                clock.monotonic.return_value=stamp
                w.capture_tick();self.pump(lambda:not w.ocr_busy);w.monitor.stop()
            self.assertEqual(reader.return_value.read.call_count,2)
            w.capture.capture.assert_not_called();w.capture.prepare_capture_mode.assert_not_called()
            ocr.assert_not_called()
        self.assertTrue(w.overlay.isVisible());self.assertIsNotNone(w.lcu_snapshot.value)
        self.assertFalse(w.overlay._rechecking);self.assertFalse(w._visible_previous)

    def test_confirmed_selection_status_does_not_wait_for_in_game_hud(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        with patch('native_ui.time.monotonic',return_value=101.2):w.refresh_status_badge()
        self.assertIn('当前选人资料已确认',w.status_chip.text())
        self.assertIn('仍可交换',w.status_chip.text());self.assertNotIn('等待核对',w.status_chip.text())
        self.assertFalse(w.state.confirmed)  # Selection never confirms augment choices.

    def test_stop_discards_held_api_read_without_starting_pixel_fallback(self):
        from session_windows import ProcessMetadata
        w=self.prepare();w.client_phase=lambda:True
        w.capture_metadata=lambda:ProcessMetadata(r'C:\League\LeagueClientUx.exe',1)
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def read(**kwargs):
            entered.set()
            if not release.wait(2):raise RuntimeError('owned read did not release')
            return {'scene':'assigned-selection','assigned':True,'championId':'9001',
                    'teamChampionIds':('9001',),'method':'lcu-read-only'}
        with patch('lcu_selection.LocalSelectionReader') as reader:
            reader.return_value.read.side_effect=read
            w.capture_tick();self.pump(entered.is_set)
            w.stop_monitor();release.set();self.pump(lambda:not w.ocr_busy)
        self.assertFalse(w.state.running);self.assertFalse(w.state.hero)
        self.assertFalse(w.overlay.isVisible());self.assertFalse(w._lcu_pixel_fallback)

    def test_failed_api_polls_do_not_reset_independent_pixel_pair(self):
        w=self.prepare()
        def failure(stamp):
            value={'_lcuUnavailable':'lockfile_missing','_capturedAt':stamp,
                   '_sessionGeneration':w.selection_session.generation,
                   '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
            with patch('native_ui.time.monotonic',return_value=stamp+.1):
                w.task_result('selection',value,w.state.generation)
            w.monitor.stop()
        failure(100.);self.assertTrue(w._lcu_pixel_fallback)
        self.assertIn('lockfile',w.hero_status.text())
        self.deliver(101.,method='client-own-row-and-center-ocr')
        self.assertEqual(w.selection_session.candidate_frames,1)
        failure(102.)
        self.assertEqual(w.selection_session.candidate_frames,1)
        self.deliver(103.,method='client-own-row-and-center-ocr')
        self.assertEqual(w.selection_session.candidate_frames,2)
        self.assertTrue(w.overlay.isVisible());self.assertTrue(w._lcu_pixel_fallback)
        self.assertFalse(w.selection_retry.ready(103.1))

    def test_failed_api_retries_after_backoff_while_pixels_keep_running(self):
        w=self.prepare();w.client_phase=lambda:True
        value={'_lcuUnavailable':'local_client_timeout','_capturedAt':100.,
               '_sessionGeneration':w.selection_session.generation,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=100.1):
            w.task_result('selection',value,w.state.generation)
        w.monitor.stop()
        with patch.object(w,'capture_selection') as api,patch.object(w,'capture_hidden') as pixels, \
             patch('native_ui.QtCore.QTimer.singleShot',side_effect=lambda delay,fn:fn()):
            for stamp in (101.,102.,105.099):
                with patch('native_ui.time.monotonic',return_value=stamp):w.capture_tick()
                w.capture_pending=False
            self.assertEqual(pixels.call_count,3);api.assert_not_called()
            with patch('native_ui.time.monotonic',return_value=105.1):w.capture_tick()
            api.assert_called_once()
        self.deliver(106.)
        self.assertFalse(w._lcu_pixel_fallback);self.assertEqual(w.selection_retry.failures,0)

    def test_pixel_receipt_distinguishes_capture_from_recognition_failure(self):
        w=self.prepare_client();w.ocr_busy=True
        value={'_capturedAt':100.,'_captureSerial':w._capture_serial,
               '_sessionGeneration':w.selection_session.generation,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        w._selection_capture_state='capturing';w.refresh_status_badge()
        self.assertIn('准备选人截图',w.footer_note.text())
        with patch('native_ui.time.monotonic',return_value=100.1):
            w.task_result('selection-capture',value,w.state.generation)
        self.assertIn('截图已收到',w.footer_note.text())
        w.task_error('selection','owned OCR failure',w.state.generation);w.monitor.stop()
        self.assertIn('截图成功',w.footer_note.text());self.assertIn('识别失败',w.footer_note.text())

    def test_stale_capture_receipt_never_claims_current_pixels(self):
        w=self.prepare_client();w.ocr_busy=True
        value={'_capturedAt':100.,'_captureSerial':w._capture_serial,
               '_sessionGeneration':w.selection_session.generation,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        for changes,generation in (({},w.state.generation-1),({'_captureSerial':-1},w.state.generation)):
            with patch('native_ui.time.monotonic',return_value=100.1):
                w.task_result('selection-capture',{**value,**changes},generation)
            self.assertEqual(w._selection_capture_state,'waiting')

    def test_stop_clears_api_backoff_and_pixel_receipt(self):
        w=self.prepare();w.selection_retry.failed(100.);w._selection_capture_state='captured'
        w.stop_monitor()
        self.assertTrue(w.selection_retry.ready(100.));self.assertEqual(w._selection_capture_state,'waiting')

    def test_failed_pixel_work_preserves_api_backoff(self):
        w=self.prepare();w.selection_retry.failed(100.);w._lcu_pixel_fallback=True
        w._lcu_error='local_client_timeout';w._selection_capture_state='captured'
        with patch('native_ui.time.monotonic',return_value=101.):
            w.task_error('selection','owned OCR failure',w.state.generation)
        w.monitor.stop()
        self.assertEqual(w.selection_retry.retry_at,105.);self.assertFalse(w.selection_retry.ready(101.))
        self.assertTrue(w._lcu_pixel_fallback);self.assertEqual(w._lcu_error,'local_client_timeout')

    def test_unexpected_interface_failure_still_backs_off_to_pixels(self):
        w=self.prepare();w._selection_capture_state='interface'
        with patch('native_ui.time.monotonic',return_value=100.):
            w.task_error('selection','owned failure',w.state.generation)
        w.monitor.stop()
        self.assertEqual(w._selection_capture_state,'interface_failed')
        self.assertTrue(w._lcu_pixel_fallback);self.assertEqual(w.selection_retry.retry_at,105.)
        self.assertNotIn('截图成功',w.footer_note.text())

    def test_source_switch_counts_first_fresh_frame_but_requires_second(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        for stamp,method in ((102.,'client-own-row-and-center-ocr'),(104.,'lcu-read-only')):
            self.deliver(stamp,method=method)
            self.assertEqual(w.selection_session.candidate_frames,1)
            self.assertFalse(w.state.hero);self.assertFalse(w.overlay.isVisible())
            self.deliver(stamp+1,method=method)
            self.assertEqual(w.selection_session.candidate_frames,2)
            self.assertEqual(w.state.hero,self.hero);self.assertTrue(w.overlay.isVisible())

    def test_stale_source_cannot_clear_current_assignment_or_snapshot(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        current=w.selection_session.generation;source=w.last_selection_source;snapshot=w.lcu_snapshot.value
        value={'scene':'assigned-selection','assigned':True,'championId':'9002',
               'method':'client-own-row-and-center-ocr','_capturedAt':102.,
               '_sessionGeneration':current-1,'_windowIdentity':fixtures.CLIENT,
               '_captureRect':self.proof['rect']}
        for changes in ({},{'_sessionGeneration':current,'_capturedAt':100.5},
                        {'_sessionGeneration':current,'_capturedAt':97.},
                        {'_sessionGeneration':current,'_capturedAt':103.}):
            with patch('native_ui.time.monotonic',return_value=102.1):
                w.task_result('selection',{**value,**changes},w.state.generation)
            w.monitor.stop()
            self.assertEqual(w.selection_session.generation,current)
            self.assertEqual(w.last_selection_source,source);self.assertIs(w.lcu_snapshot.value,snapshot)
            self.assertEqual(w.state.hero,self.hero);self.assertTrue(w.overlay.isVisible())

    def test_old_selection_job_cannot_release_a_new_capture_lease(self):
        w=self.prepare();w.ocr_busy=True;w.capture_pending=True;w._capture_serial=12
        w._active_capture_generation=w.state.generation
        value={'scene':'assigned-selection','assigned':True,'championId':'9001',
               'method':'lcu-read-only','_capturedAt':100.,'_captureSerial':11,
               '_sessionGeneration':w.selection_session.generation-1,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=100.1):
            w.task_result('selection',value,w.state.generation)
        self.assertTrue(w.ocr_busy);self.assertTrue(w.capture_pending)
        self.assertEqual(w._active_capture_generation,w.state.generation)
        self.assertEqual(w.selection_session.candidate_frames,0)

    def test_current_job_with_revoked_selection_generation_releases_own_lease(self):
        w=self.prepare();w.ocr_busy=True;w.capture_pending=True;w._capture_serial=12
        value={'scene':'assigned-selection','assigned':True,'championId':'9001',
               'method':'lcu-read-only','_capturedAt':100.,'_captureSerial':12,
               '_sessionGeneration':w.selection_session.generation-1,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=100.1):
            w.task_result('selection',value,w.state.generation)
        w.monitor.stop()
        self.assertFalse(w.ocr_busy);self.assertFalse(w.capture_pending)
        self.assertEqual(w.selection_session.candidate_frames,0);self.assertFalse(w.state.hero)

    def test_failed_api_revokes_its_own_previous_assignment(self):
        w=self.prepare();self.deliver(100.);self.deliver(101.)
        self.assertTrue(w.overlay.isVisible())
        value={'_lcuUnavailable':'local_client_tls_error','_capturedAt':102.,
               '_sessionGeneration':w.selection_session.generation,
               '_windowIdentity':fixtures.CLIENT,'_captureRect':self.proof['rect']}
        with patch('native_ui.time.monotonic',return_value=102.1):
            w.task_result('selection',value,w.state.generation)
        w.monitor.stop()
        self.assertFalse(w.state.hero);self.assertFalse(w.overlay.isVisible())
        self.assertIsNone(w.lcu_snapshot.value);self.assertTrue(w._lcu_pixel_fallback)
        self.assertIn('证书',w.hero_status.text())
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
