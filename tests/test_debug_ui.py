"""Local-only diagnostics through actual Qt controls and owned capture fakes."""
import gc
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class DebugUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def pump(self, predicate, seconds=4):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.app.processEvents()
            if predicate(): return
            time.sleep(.005)
        self.fail('Owned debug UI fixture did not settle')

    def setUp(self):
        from engine import load_data
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch('native_ui.Win32Capture', side_effect=CaptureUnavailable('owned portable fixture')):
            self.window = ControlWindow(
                lambda: {'data': load_data(Path(__file__).resolve().parents[1] / 'fixtures/demo.json')},
                state_dir=self.root, current_executable='/private/unused.exe',
                current_version='0.4.9', frozen=False, enable_updates=False)
        self.addCleanup(self.dispose)
        self.pump(lambda: self.window.data is not None and not self.window._workers)
        self.window.watchdog.stop(); self.window.monitor.stop()
        self.window.schedule_capture = lambda delay=None: None

    def dispose(self):
        window = self.window
        if window is None:return
        overlay = window.overlay
        window.capture = None; overlay.capture = None
        window.close()
        self.pump(lambda: not window._workers)
        overlay.deleteLater(); window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(window)); self.assertFalse(isValid(overlay))
        self.window = None; gc.collect(); self.app.processEvents()

    def exported(self):
        self.window.debug_export_button.click()
        path = self.root / 'debug-exports' / 'VGA-debug.zip'
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'events.jsonl', 'critical.jsonl', 'context.jsonl'})
            manifest = json.loads(archive.read('manifest.json'))
            text = archive.read('events.jsonl').decode()
            whole_archive = '\n'.join(archive.read(name).decode() for name in archive.namelist())
            self.assertEqual(manifest['schema'], 3)
            self.assertLessEqual(sum(entry.file_size for entry in archive.infolist()), 832 * 1024)
            # Incident originals overlap the sampled tail. Correlate exact
            # records by session/sequence; never pretend critical aggregates
            # are individual adjacent events.
            rows = [json.loads(line) for line in text.splitlines()]
            rows.extend(json.loads(line) for line in archive.read('context.jsonl').splitlines())
            unique = {(row['session'], row['sequence']): row for row in rows}
            events = sorted(unique.values(), key=lambda row: (row['session'], row['sequence']))
            return manifest, events, whole_archive

    def test_diagnostic_default_on_toggle_and_export_are_local_and_retain_prior_logs(self):
        w = self.window
        self.assertTrue(w.debug_toggle.isChecked()); self.assertTrue(w.debug_log.enabled)
        self.assertTrue(w.enable_visible_capture)
        self.assertTrue((self.root / 'local-debug').exists())
        w.debug_toggle.setChecked(True)
        self.assertTrue(w.debug_log.enabled)
        w.debug_toggle.setChecked(False)
        before = w.debug_log._path().read_bytes()
        w.invalidate_scene('PRIVATE_RAW_ERROR')
        self.assertEqual(before, w.debug_log._path().read_bytes())
        manifest, events, text = self.exported()
        self.assertIn('debug_enabled', [event['event'] for event in events])
        self.assertIn('debug_disabled', [event['event'] for event in events])
        self.assertEqual(manifest['config']['visible_capture'], True)
        self.assertIn(str(self.root / 'debug-exports' / 'VGA-debug.zip'), w.debug_status.text())
        self.assertNotIn(str(self.root), text + json.dumps(manifest))
        self.assertNotIn('PRIVATE_RAW_ERROR', text)

    def test_historical_settings_and_selection_gate_reach_critical_export(self):
        w = self.window
        self.assertFalse(w.lcu_toggle.isChecked())
        w.lcu_toggle.setChecked(True)
        w.state.start((123, 456, 'owned'))
        w.target = None
        w.capture_tick()
        manifest, _, text = self.exported()
        with zipfile.ZipFile(self.root / 'debug-exports' / 'VGA-debug.zip') as archive:
            critical = [json.loads(line) for line in archive.read('critical.jsonl').splitlines()]
        configs = [row for row in critical if row['event'] == 'config']
        self.assertFalse(configs[0]['lcu_selection'])
        self.assertTrue(configs[-1]['lcu_selection'])
        self.assertLess(configs[0]['sequence'], configs[-1]['sequence'])
        gate = next(row for row in critical if row.get('selection_gate') == 'target_missing')
        self.assertEqual(gate['selection_route'], 'blocked')
        self.assertTrue(gate['lcu_selection'])
        self.assertFalse(gate['target_present'])
        self.assertEqual(manifest['summary']['selection_gates']['target_missing']['observations'], 1)
        self.assertNotIn(str(self.root), text)

    def test_round_hero_freshness_and_ttl_transitions_exclude_names(self):
        w = self.window
        w.debug_toggle.setChecked(True)
        w.state.start((123, 456, 'PRIVATE_CLASS'))
        w.state.hero = 'PRIVATE_HERO_ONE'; w.state.observed = ('PRIVATE_A', 'PRIVATE_B', 'PRIVATE_C')
        w.last_observation = time.monotonic(); w.refresh_status_badge()
        w.state.hero = 'PRIVATE_HERO_TWO'; w.state.observed = ('PRIVATE_D', 'PRIVATE_E', 'PRIVATE_F')
        w.refresh_status_badge()
        generation = w.state.generation
        w.expire_game_display(); w.refresh_status_badge()
        self.assertEqual(w.state.generation, generation)
        _, events, text = self.exported()
        states = [event for event in events if event['event'] == 'state' and event['candidate_count'] == 3]
        self.assertGreaterEqual(len(states), 2)
        self.assertGreater(states[1]['hero_revision'], states[0]['hero_revision'])
        self.assertGreater(states[1]['candidate_revision'], states[0]['candidate_revision'])
        self.assertTrue(any(event.get('reason') == 'ttl_game' for event in events))
        self.assertNotIn('PRIVATE_', text)

    def test_overlay_visibility_records_explicit_reasons(self):
        w = self.window
        w.debug_toggle.setChecked(True)
        w.overlay._show_reason = 'confirmed'; w.overlay.show(); self.app.processEvents()
        w.overlay.hide('focus_lost'); self.app.processEvents()
        _, events, _ = self.exported()
        self.assertTrue(any(e['event'] == 'overlay' and e.get('visible') is True and e.get('reason') == 'confirmed' for e in events))
        self.assertTrue(any(e['event'] == 'overlay' and e.get('visible') is False and e.get('reason') == 'focus_lost' for e in events))

    def test_capture_records_timings_backend_dimensions_and_opaque_identity(self):
        from screen_capture import ClientRect, WindowInfo
        from session_windows import ProcessMetadata
        w = self.window; main_thread = threading.get_ident(); capture_threads = []
        class Capture:
            last_backend = 'window-dc'
            def capture(self, *args, **kwargs):
                capture_threads.append(threading.get_ident())
                return b'PRIVATE_IMAGE_BYTES', ClientRect(0, 0, 900, 600)
        w.capture = Capture(); w.target = WindowInfo(123456, 456789, 'PRIVATE_TITLE', 'PRIVATE_CLASS')
        w.target_allowed = lambda: True
        w.capture_metadata = lambda: ProcessMetadata('C:/Users/PRIVATE_USER/game.exe', 12345)
        w.captured_frame_current = lambda value: True
        w.check_target = lambda: None
        w.state.start(w.target.identity); w.debug_toggle.setChecked(True)
        def dpi():
            self.assertEqual(threading.get_ident(), main_thread)
            return 1.5
        with patch.object(w.overlay, 'devicePixelRatioF', side_effect=dpi), patch('hero_recognition.recognize_frame', return_value={'automatic_candidates': [], 'candidates': []}):
            w.capture_hidden(w.state.generation)
            self.pump(lambda: not w.ocr_busy and not w._workers)
        _, events, text = self.exported()
        acquired = next(e for e in events if e['event'] == 'capture' and e.get('phase') == 'acquired')
        completed = next(e for e in events if e['event'] == 'capture' and e.get('phase') == 'completed')
        self.assertEqual((acquired['width'], acquired['height'], acquired['dpi']), (900, 600, 144.))
        self.assertEqual(acquired['backend'], 'window-dc')
        self.assertRegex(acquired['window_id'], r'^[0-9a-f]{16}$')
        self.assertRegex(acquired['process_id'], r'^[0-9a-f]{16}$')
        self.assertGreaterEqual(completed['capture_ms'], 0); self.assertGreaterEqual(completed['inference_ms'], 0)
        self.assertNotEqual(capture_threads[0], main_thread)
        self.assertNotIn('PRIVATE_', text)
        self.assertNotIn('123456', text); self.assertNotIn('456789', text)

    def test_stop_generation_discards_worker_result_without_raw_error(self):
        w = self.window; entered = threading.Event(); release = threading.Event()
        self.addCleanup(release.set)
        w.state.start((123, 456, 'owned')); w.debug_toggle.setChecked(True)
        generation = w.state.generation
        def work():
            entered.set()
            if not release.wait(2):raise RuntimeError('PRIVATE_TIMEOUT')
            return {'candidates': [], 'automatic_candidates': []}
        w.spawn('ocr', work, generation)
        self.pump(entered.is_set); w.stop_monitor(); release.set()
        self.pump(lambda: not w._workers)
        self.app.processEvents()
        _, events, text = self.exported()
        self.assertTrue(any(e.get('reason') == 'stop' and e['event'] == 'cancel' for e in events))
        self.assertTrue(any(e.get('phase') == 'discarded' and e.get('generation') == generation for e in events))
        self.assertNotIn('PRIVATE_', text)

    def test_write_and_export_failure_do_not_stop_monitor_or_disclose_errors(self):
        w = self.window
        w.state.start((123, 456, 'owned')); w.debug_toggle.setChecked(True)
        with patch.object(w.debug_log, '_owned_directory', side_effect=OSError('PRIVATE_FAILURE_PATH')):
            w.debug_event('session', phase='started')
        w.refresh_status_badge()
        self.assertFalse(w.debug_toggle.isChecked()); self.assertFalse(w.debug_log.enabled)
        self.assertTrue(w.state.running)
        with patch.object(w.debug_log, 'export_zip', side_effect=OSError('PRIVATE_FAILURE_PATH')):
            w.debug_export_button.click()
        self.assertNotIn('PRIVATE_FAILURE_PATH', w.debug_status.text())
        self.assertTrue(w.state.running)

    def test_hidden_capture_fallback_is_correlated_with_actual_withdrawal(self):
        from types import SimpleNamespace
        w=self.window
        w.state.start((123,456,'owned'));w.state.confirmed=True
        w.last_observation=time.monotonic();w._capture_serial=40
        # This fixture exercises backend fallback from an already accepted
        # automatic frame, rather than the separate no-previous-authority gate.
        w._accepted_frame={'observed_at':w.last_observation}
        w.target=SimpleNamespace(identity=(123,456,'owned'))
        w.capture=SimpleNamespace(foreground=lambda target:True,
            visible_capture_status='backend_unavailable',can_request_visible_overlay=False)
        w.overlay._show_reason='confirmed';w.overlay.show();self.app.processEvents()
        with patch('native_ui.QtCore.QTimer.singleShot'):
            w.capture_tick()
        _,events,text=self.exported()
        request=next(e for e in events if e.get('phase')=='requested' and e.get('reason')=='backend_unavailable')
        hide=next(e for e in events if e.get('event')=='overlay' and e.get('reason')=='capture_pending')
        self.assertEqual(request['serial'],41);self.assertEqual(hide['serial'],41)
        self.assertEqual(request['generation'],hide['generation'])
        self.assertFalse(hide['visible']);self.assertLess(request['sequence'],hide['sequence'])
        self.assertTrue(any(e.get('serial')==41 and e.get('settle_ms',0)>0 for e in events))

    def test_slow_frame_rejection_has_age_and_phase_evidence_in_export(self):
        from screen_capture import ClientRect,WindowInfo
        w=self.window;w.target=WindowInfo(123,456,'owned','owned')
        w.state.start(w.target.identity);w._capture_serial=8
        w.captured_frame_current=lambda value:True;w.target_allowed=lambda:True
        w.capture_metadata=lambda:None;w.check_target=lambda:None
        class Capture:
            last_backend='window-dc'
            def capture(self,*args,**kwargs):return b'owned fixture',ClientRect(0,0,900,600)
        w.capture=Capture()
        def slow_recognition(*args,diagnostic_callback=None,**kwargs):
            started=time.monotonic();diagnostic_callback('ocr','started',0)
            time.sleep(4.05)
            diagnostic_callback('ocr','completed',(time.monotonic()-started)*1000)
            return {'automatic_candidates':[],'candidates':[]}
        with patch('hero_recognition.recognize_frame',side_effect=slow_recognition):
            w.capture_hidden(w.state.generation)
            self.pump(lambda:not w.ocr_busy and not w._workers,seconds=6)
        _,events,_=self.exported()
        rejected=next(e for e in events if e.get('phase')=='discarded' and e.get('reason')=='stale_frame')
        self.assertGreater(rejected['age_ms'],4000);self.assertEqual(rejected['ttl_ms'],4000)
        stage=next(e for e in events if e.get('event')=='inference' and e.get('phase')=='completed' and e.get('inference_stage')=='ocr')
        self.assertEqual(stage['inference_stage'],'ocr');self.assertGreaterEqual(stage['inference_ms'],4000)
        self.assertEqual(stage['serial'],rejected['serial']);self.assertFalse(w.state.confirmed)
        same_frame=[e for e in events if e.get('serial')==rejected['serial']]
        self.assertTrue(any(e.get('phase')=='acquired' for e in same_frame))
        self.assertTrue(any('queue_ms' in e for e in same_frame))
        self.assertTrue(any('dispatch_ms' in e for e in same_frame))


    def test_failed_worker_has_one_safe_category_and_separate_ui_receipt(self):
        w = self.window
        def fail(): raise KeyError('PRIVATE_WORKER_PAYLOAD')
        w.spawn('update', fail)
        self.pump(lambda: not w._workers)
        self.pump(lambda: w.debug_log._summary['reasons'].get('worker_error', {}).get('observations', 0) > 0)
        manifest, events, text = self.exported()
        errors = [row for row in events if row['event'] == 'job' and row.get('kind') == 'update' and row.get('phase') == 'error']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['worker_error_category'], 'key_error')
        self.assertTrue(any(row.get('kind') == 'update' and row.get('phase') == 'accepted' and row.get('reason') == 'worker_error' for row in events))
        self.assertEqual(sum(row['worker_errors'] for row in manifest['game_summaries']['games']), 1)
        self.assertNotIn('PRIVATE_WORKER_PAYLOAD', text)

    def test_verified_window_boundary_changes_only_diagnostic_scope(self):
        from types import SimpleNamespace
        w = self.window
        original_generation, original_running = w.state.generation, w.state.running
        first = w.debug_log.begin_game()
        a = SimpleNamespace(identity=('PRIVATE_WINDOW_A', 123))
        b = SimpleNamespace(identity=('PRIVATE_WINDOW_B', 456))
        w.note_verified_game_scope(a, 1)
        self.assertEqual(w.debug_log._game_generation, first)
        w.note_verified_game_scope(a, 1)
        self.assertEqual(w.debug_log._game_generation, first)
        w.note_verified_game_scope(b, 2)
        self.assertEqual(w.debug_log._game_generation, first + 1)
        self.assertEqual((w.state.generation, w.state.running), (original_generation, original_running))
        _, _, text = self.exported()
        self.assertNotIn('PRIVATE_WINDOW', text)

    def test_late_worker_failure_stays_with_scope_at_queue_time(self):
        w = self.window
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        first = w.debug_log.begin_game()
        def fail_later():
            started.set()
            if not release.wait(3): raise AssertionError('Owned fixture timed out')
            raise TimeoutError('PRIVATE_LATE_ERROR')
        w.spawn('update', fail_later)
        self.pump(started.is_set)
        second = w.debug_log.begin_game()
        release.set()
        self.pump(lambda: not w._workers)
        manifest, events, text = self.exported()
        games = {row['game_generation']: row for row in manifest['game_summaries']['games']}
        self.assertEqual(games[first]['worker_errors'], 1)
        self.assertEqual(games[second]['worker_errors'], 0)
        failure = next(row for row in events if row.get('worker_error_category') == 'timeout')
        self.assertEqual(failure['game_generation'], first)
        self.assertNotIn('PRIVATE_LATE_ERROR', text)


if __name__ == '__main__':
    unittest.main()
