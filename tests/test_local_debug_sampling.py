"""Bounded trace reconstruction, sampling, filtering and catalog privacy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from local_debug import LocalDebugLog


class DiagnosticTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = LocalDebugLog(self.root / 'logs', version='0.4.11', max_bytes=4096)
        self.log.set_enabled(True)

    def export(self, **options):
        path = self.log.export_zip(self.root / 'export', config={'hero_auto': True}, **options)
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read('manifest.json')), [json.loads(line) for line in archive.read('events.jsonl').splitlines()]

    def test_trace_preserves_hide_capture_recognition_show_and_timing(self):
        self.log.record('overlay', visible=False, reason='capture_proof')
        for serial, duration in enumerate((10, 20, 40)):
            self.log.sample('capture', phase='completed', backend='window-dc', serial=serial,
                            capture_ms=duration, settle_ms=5, generation=1)
        self.log.record('recognition', phase='ocr_started', serial=2, generation=1)
        self.log.record('recognition', phase='accepted', serial=2, generation=1, catalog_match=True)
        self.log.record('overlay', visible=True, reason='recognized')
        manifest, events = self.export()
        self.assertEqual([item['event'] for item in events], [
            'debug_enabled', 'overlay', 'capture', 'recognition', 'recognition', 'overlay', 'sample_summary'])
        summary = events[-1]
        self.assertEqual(summary['sampled_event'], 'capture')
        self.assertEqual(summary['sample_count'], 2)
        self.assertEqual((summary['first_serial'], summary['last_serial']), (1, 2))
        self.assertEqual((summary['capture_ms_min'], summary['capture_ms_max'], summary['capture_ms_mean']), (20, 40, 30))
        self.assertEqual(manifest['counters']['aggregated_samples'], 2)
        self.assertEqual([item['sequence'] for item in events], sorted({item['sequence'] for item in events}))
        self.assertEqual([item['sequence'] for item in events[:3]], [1, 2, 3])
        self.assertEqual(len({item['session'] for item in events}), 1)

    def test_stage_start_does_not_halve_latency_average(self):
        self.log.record('inference',inference_stage='ocr',phase='started',inference_ms=0)
        self.log.record('inference',inference_stage='ocr',phase='completed',inference_ms=50)
        manifest,_=self.export()
        bucket=manifest['summary']['inference_stages']['ocr']
        self.assertEqual(bucket['observations'],2)
        self.assertEqual(bucket['latency']['count'],1)
        self.assertEqual(bucket['latency']['total_ms'],50)
        self.assertEqual(manifest['summary']['timings']['inference_ms']['count'],1)

    def test_rechecking_snapshot_is_not_a_visibility_transition(self):
        self.log.record('overlay',phase='rechecking',visible=False,rechecking=True)
        manifest,events=self.export()
        self.assertEqual(manifest['summary']['overlay']['observed_hide_transitions'],0)
        self.assertEqual(events[-1]['phase'],'rechecking')
        self.assertEqual(manifest['diagnostic_profile'],'capture-stability-v2')

    def test_alternating_sample_state_never_erases_a_transition(self):
        for visible in (True, True, False, False, True):
            self.log.sample('overlay', visible=visible)
        _, events = self.export()
        self.assertEqual([item['visible'] for item in events if item['event'] == 'overlay'], [True, False, True])
        self.assertEqual([item['visible'] for item in events if item['event'] == 'sample_summary'], [True, False])

    def test_one_second_sampling_interval_flushes_bounded_summary(self):
        with patch.object(self.log, '_elapsed', return_value=0):
            self.log.sample('capture', capture_ms=1)
            self.log.sample('capture', capture_ms=2)
        with patch.object(self.log, '_elapsed', return_value=1001):
            self.log.sample('capture', capture_ms=3)
        self.assertTrue(all(stream['pending'] is None for stream in self.log._samples.values()))
        _, events = self.export()
        self.assertEqual(events[-1]['sample_count'], 2)
        self.assertEqual(events[-1]['first_elapsed_ms'], 0)
        self.assertEqual(events[-1]['last_elapsed_ms'], 1001)

    def test_local_game_and_recent_window_exclude_old_sessions(self):
        with patch.object(self.log, '_elapsed', return_value=1000):
            first = self.log.begin_game()
            self.log.record('capture', serial=10)
        with patch.object(self.log, '_elapsed', return_value=5000):
            second = self.log.begin_game()
            self.log.record('capture', serial=20)
            _, events = self.export(game_generation=second, recent_seconds=1)
        self.assertNotEqual(first, second)
        self.assertEqual([item['serial'] for item in events if 'serial' in item], [20])
        self.assertTrue(all(item['game_generation'] == second for item in events))
        other = LocalDebugLog(self.root / 'logs', version='0.4.11')
        other.set_enabled(True)
        with zipfile.ZipFile(other.export_zip(self.root / 'export', config={}, recent_seconds=60)) as archive:
            new_events = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
        self.assertEqual(len(new_events), 1)
        self.assertEqual(new_events[0]['event'], 'debug_enabled')

    def test_catalog_registry_and_export_revalidation(self):
        self.log.register_catalog(augment_names=['Scoped Weapons'], hero_names=['Ahri'])
        self.log.record('recognition', augment_name='Scoped Weapons', hero_name='Ahri', slot=2,
                        confidence=.96, threshold=.8, catalog_match=True, tier_present=False,
                        hero_source='hud', recognized_text='PRIVATE_OCR', player_name='PRIVATE_PLAYER')
        self.log.record('recognition', augment_name='PRIVATE_OCR', hero_name='PRIVATE_PLAYER', slot=3,
                        confidence=2, threshold=-1, hero_source='PRIVATE_SOURCE')
        _, events = self.export()
        self.assertEqual(events[-2]['augment_name'], 'Scoped Weapons')
        self.assertEqual(events[-2]['hero_name'], 'Ahri')
        self.assertEqual(events[-2]['slot'], 2)
        self.assertNotIn('PRIVATE', json.dumps(events))
        for key in ('augment_name', 'hero_name', 'slot', 'confidence', 'threshold', 'hero_source'):
            self.assertNotIn(key, events[-1])
        self.log.register_catalog()
        _, events = self.export()
        self.assertNotIn('Scoped Weapons', json.dumps(events))
        self.assertNotIn('Ahri', json.dumps(events))

    def test_rotation_and_dropped_values_report_loss(self):
        for serial in range(150):
            self.log.record('capture', serial=serial, arbitrary='PRIVATE')
        self.log.record('PRIVATE_EVENT')
        manifest, events = self.export()
        self.assertGreater(manifest['counters']['rotations'], 0)
        self.assertGreater(manifest['counters']['truncated_events'], 0)
        self.assertEqual(manifest['counters']['dropped_events'], 1)
        self.assertEqual(manifest['counters']['dropped_fields'], 150)
        self.assertLessEqual(sum(path.stat().st_size for path in self.log.directory.iterdir()), 3 * 4096)
        self.assertEqual(events[-1]['serial'], 149)

    def test_generated_context_cannot_be_overwritten(self):
        self.log.record('capture', elapsed_ms=123456, sequence=9999, game_generation=8888)
        _, events = self.export()
        self.assertEqual(events[-1]['sequence'], 2)
        self.assertEqual(events[-1]['game_generation'], 0)
        self.assertNotEqual(events[-1]['elapsed_ms'], 123456)

    def test_disable_flushes_pending_samples_before_disabled_transition(self):
        self.log.sample('state', state='idle')
        self.log.sample('state', state='idle')
        self.log.set_enabled(False)
        _, events = self.export()
        self.assertEqual([item['event'] for item in events[-2:]], ['sample_summary', 'debug_disabled'])
        self.assertFalse(self.log.sample('state', state='idle'))

    def test_inference_stage_fields_and_long_running_session_survive_export(self):
        with patch.object(self.log, '_elapsed', return_value=172800001):
            self.log.record('inference', inference_stage='hud_match', phase='completed',
                            inference_ms=15.25, generation=2, serial=4, reason='display_wait')
        _, events = self.export()
        value = events[-1]
        self.assertEqual(value['elapsed_ms'], 172800001)
        self.assertEqual(value['inference_stage'], 'hud_match')
        self.assertEqual(value['inference_ms'], 15.25)
        self.assertEqual(value['reason'], 'display_wait')

    def test_launch_summary_retains_old_hidden_cycles_after_rotation(self):
        with patch.object(self.log, '_elapsed', return_value=100):
            self.log.record('overlay', visible=False, reason='capture_proof')
            self.log.record('overlay', visible=False, reason='capture_proof')
        with patch.object(self.log, '_elapsed', return_value=175):
            self.log.record('overlay', visible=True, reason='recognized')
        for serial in range(200):
            self.log.record('inference', inference_stage='ocr', phase='completed',
                            reason='recognized', inference_ms=20, serial=serial)
        for serial in range(200):
            self.log.record('capture', serial=serial)
        manifest, events = self.export()
        self.assertFalse(any(item['event'] == 'overlay' for item in events))
        self.assertGreater(manifest['counters']['truncated_events'], 0)
        summary = manifest['summary']
        self.assertEqual(summary['events']['inference']['observations'], 200)
        self.assertEqual(summary['inference_stages']['ocr']['latency'],
                         {'count': 200, 'total_ms': 4000, 'max_ms': 20})
        self.assertEqual(summary['overlay']['observed_hide_transitions'], 1)
        self.assertEqual(summary['overlay']['observed_show_transitions'], 1)
        self.assertEqual(summary['overlay']['hidden_total_ms'], 75)
        self.assertEqual(summary['overlay']['hidden_max_ms'], 75)

    def test_summary_counts_each_sample_once_and_keeps_metric_totals(self):
        for duration in (10, 20, 40):
            self.log.sample('capture', phase='completed', reason='capture_proof',
                            capture_ms=duration, settle_ms=5)
        manifest, _ = self.export()
        summary = manifest['summary']
        self.assertEqual(summary['events']['capture']['observations'], 3)
        self.assertNotIn('sample_summary', summary['events'])
        self.assertEqual(summary['events']['capture']['latency'],
                         {'count': 3, 'total_ms': 70, 'max_ms': 40})
        self.assertEqual(summary['timings']['settle_ms'], {'count': 3, 'total_ms': 15, 'max_ms': 5})
        self.assertEqual(summary['reasons']['capture_proof']['observations'], 3)

    def test_hidden_time_stops_when_logging_disabled(self):
        with patch.object(self.log, '_elapsed', return_value=10):
            self.log.record('overlay', visible=False)
        with patch.object(self.log, '_elapsed', return_value=35):
            self.log.set_enabled(False)
        with patch.object(self.log, '_elapsed', return_value=1000):
            manifest, _ = self.export()
        self.assertEqual(manifest['summary']['overlay']['hidden_total_ms'], 25)
        self.assertEqual(manifest['summary']['overlay']['open_hidden_ms'], 0)

    def test_summary_has_fixed_enum_key_budget_and_never_keeps_names(self):
        from local_debug import _EVENTS, _ENUMS, _TIMINGS, _CAPTURE_ENUMS, EXPORT_OVERHEAD_BYTES
        self.log.register_catalog(augment_names=['Scoped Weapons'], hero_names=['Ahri'])
        metrics = {key: 123.456 for key in _TIMINGS}
        for reason in _ENUMS['reason']:
            for event in _EVENTS - {'sample_summary'}:
                self.log.record(event, reason=reason, hero_name='Ahri', augment_name='Scoped Weapons', **metrics)
        for stage in _ENUMS['inference_stage']:
            self.log.record('inference', inference_stage=stage, **metrics)
        for field, vocabulary in _CAPTURE_ENUMS.items():
            for value in vocabulary:
                self.log.record('capture', **{field: value}, **metrics)
        manifest, _ = self.export()
        summary = manifest['summary']
        self.assertEqual(set(summary['events']), _EVENTS - {'sample_summary'})
        self.assertEqual(set(summary['reasons']), _ENUMS['reason'])
        self.assertEqual(set(summary['inference_stages']), _ENUMS['inference_stage'])
        self.assertNotIn('Ahri', json.dumps(summary))
        self.assertNotIn('Scoped Weapons', json.dumps(summary))
        self.assertLess(len(json.dumps(manifest).encode()), EXPORT_OVERHEAD_BYTES)

    def test_capture_status_vocabulary_matches_routing_and_rejects_raw_errors(self):
        from screen_capture import CAPTURE_DIAGNOSTIC_ENUMS
        from local_debug import _CAPTURE_ENUMS
        self.assertEqual(_CAPTURE_ENUMS, CAPTURE_DIAGNOSTIC_ENUMS)
        self.log.record('capture', capture_status='ok', session_status='disabled',
                        oneshot_status='used', fallback_reason='session-disabled', capture_ms=50)
        self.log.record('capture', capture_status='PRIVATE_ERROR', fallback_reason='PRIVATE_PATH')
        manifest, events = self.export()
        self.assertEqual(events[-2]['fallback_reason'], 'session-disabled')
        self.assertNotIn('PRIVATE', json.dumps(manifest) + json.dumps(events))
        self.assertEqual(manifest['summary']['fallback_reasons']['session-disabled']['latency']['max_ms'], 50)

    def export_lanes(self, **options):
        path = self.log.export_zip(self.root / 'export', config={'hero_auto': True}, **options)
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read('manifest.json')), {
                name: [json.loads(line) for line in archive.read(name).splitlines()]
                for name in ('events.jsonl', 'critical.jsonl', 'context.jsonl')}

    def test_interleaved_lifecycle_records_do_not_reset_sample_streams(self):
        for serial in range(40):
            self.log.sample('capture', capture_mode='eligible', serial=serial)
            self.log.record('inference', inference_stage='ocr', phase='started', serial=serial)
            self.log.record('inference', inference_stage='ocr', phase='completed', serial=serial, inference_ms=10 + serial)
            self.log.record('recognition', reason='recognized', serial=serial)
        manifest, lanes = self.export_lanes()
        self.assertGreaterEqual(manifest['counters']['aggregated_samples'], 3 * 39)
        summaries = [row for row in lanes['events.jsonl'] if row['event'] == 'sample_summary']
        self.assertTrue(any(row.get('sampled_event') == 'capture' and row['sample_count'] == 39 for row in summaries))
        self.assertEqual(manifest['summary']['events']['inference']['observations'], 80)
        self.assertEqual(manifest['summary']['timings']['inference_ms']['count'], 40)
        self.assertLessEqual(len(self.log._samples), 64)

    def test_unproven_prior_frame_reason_survives_all_export_lanes(self):
        self.log.record('capture', phase='requested', reason='prior_frame_unproven', serial=1)
        self.log.record('overlay', phase='hidden', visible=False, reason='capture_pending', serial=1)
        _, lanes = self.export_lanes()
        for values in lanes.values():
            self.assertTrue(any(row.get('reason') == 'prior_frame_unproven' for row in values))

    def test_producer_selection_and_discovery_vocabulary_roundtrips(self):
        from automatic_windows import SELECTION_GATES, SELECTION_ROUTES, TARGET_ROLES, DISCOVERY_COUNT_FIELDS
        from local_debug import _ENUMS
        for field, values in (('selection_gate', SELECTION_GATES), ('selection_route', SELECTION_ROUTES), ('target_role', TARGET_ROLES)):
            self.assertEqual(set(values), set(_ENUMS[field]))
            for value in values:
                self.log.record('selection_gate', **{field: value})
        self.log.record('job', kind='windows', phase='completed', **{field: 3 for field in DISCOVERY_COUNT_FIELDS})
        manifest, lanes = self.export_lanes()
        self.assertEqual(set(manifest['summary']['selection_gates']), set(SELECTION_GATES))
        self.assertEqual(set(manifest['summary']['selection_routes']), set(SELECTION_ROUTES))
        self.assertEqual(set(manifest['summary']['target_roles']), set(TARGET_ROLES))
        discovery = next(row for row in lanes['critical.jsonl'] if row.get('kind') == 'windows')
        self.assertTrue(all(discovery[field] == 3 for field in DISCOVERY_COUNT_FIELDS))

    def test_config_is_historical_exact_and_redacted_in_every_lane(self):
        self.log.register_catalog(hero_names=['Ahri'])
        with patch.object(self.log, '_elapsed', return_value=10):
            self.log.record_config({'lcu_selection': False, 'hero_auto': True, 'roi_percent': [10, 20, 30, 40], 'path': 'PRIVATE_PATH'})
            self.log.record('overlay', phase='hidden', visible=False, reason='title_recheck', hero_name='Ahri', raw_ocr='PRIVATE_OCR', serial=1)
        with patch.object(self.log, '_elapsed', return_value=20):
            self.log.record_config({'lcu_selection': True})
        with patch.object(self.log, '_elapsed', return_value=30):
            self.log.record_config({'lcu_selection': False})
        self.log.register_catalog()
        manifest, lanes = self.export_lanes()
        configs = [row for row in lanes['critical.jsonl'] if row['event'] == 'config']
        self.assertEqual([row['lcu_selection'] for row in configs], [False, True, False])
        self.assertEqual([row['elapsed_ms'] for row in configs], [10, 20, 30])
        self.assertTrue(all(row['occurrences'] == 1 for row in configs))
        self.assertNotIn('PRIVATE', json.dumps(manifest) + json.dumps(lanes))
        self.assertNotIn('Ahri', json.dumps(lanes))

    def test_noncontiguous_critical_recurrences_are_explicit_not_adjacent(self):
        for now, visible in ((10, False), (20, True), (30, False), (40, True)):
            with patch.object(self.log, '_elapsed', return_value=now):
                self.log.record('overlay', phase='shown' if visible else 'hidden', visible=visible,
                                reason='recognized' if visible else 'capture_proof', serial=now)
        manifest, lanes = self.export_lanes()
        hidden = next(row for row in lanes['critical.jsonl'] if row.get('phase') == 'hidden')
        self.assertEqual(hidden['occurrences'], 2)
        self.assertEqual((hidden['first_elapsed_ms'], hidden['last_elapsed_ms']), (10, 30))
        self.assertEqual((hidden['first_serial'], hidden['last_serial']), (10, 30))
        self.assertLess(hidden['first_sequence'], hidden['last_sequence'])
        self.assertIn('noncontiguous', manifest['coverage']['critical_order'])
        exact = [row for row in lanes['context.jsonl'] if row['event'] == 'overlay']
        self.assertEqual([row['visible'] for row in exact], [False, True, False, True])

    def test_new_lanes_are_revalidated_and_never_follow_symlinks(self):
        self.log.record('overlay', phase='hidden', visible=False, reason='capture_proof', serial=1)
        self.log.flush()
        for name in ('critical.jsonl', 'context.jsonl'):
            path = self.log.directory / name
            path.write_text(json.dumps({'event': 'recognition', 'session': 'a' * 16,
                                        'reason': 'PRIVATE_RAW_ERROR', 'title': 'PRIVATE_TITLE',
                                        'player_name': 'PRIVATE_PLAYER', 'screenshot': 'PRIVATE_SCREEN',
                                        'path': 'PRIVATE_PATH', 'augment_name': 'PRIVATE_OCR',
                                        'hero_auto': 'PRIVATE_BOOLEAN', 'selection_gate': 'PRIVATE_GATE'}) + '\n{invalid\n')
        manifest, lanes = self.export_lanes()
        self.assertNotIn('PRIVATE', json.dumps(manifest) + json.dumps(lanes))
        self.assertEqual(manifest['coverage']['export_validation'], {'invalid_records': 2})
        private = self.root / 'private'
        private.write_text('PRIVATE_CONTENT')
        for name in ('critical.jsonl', 'context.jsonl'):
            path = self.log.directory / name
            path.unlink()
            try:
                path.symlink_to(private)
            except OSError as exc:
                import os
                if os.name == 'nt' and getattr(exc, 'winerror', None) in (1, 50, 1314):
                    self.skipTest('Symlink creation is not available for this Windows account')
                raise
            with self.assertRaises(OSError):
                self.export_lanes()
            self.assertEqual(private.read_text(), 'PRIVATE_CONTENT')
            path.unlink()
            path.write_bytes(b'')

    def test_oversized_history_file_is_explicitly_excluded_at_export(self):
        self.log.flush()
        (self.log.directory / 'critical.jsonl').write_bytes(b'PRIVATE' * 4096)
        manifest, lanes = self.export_lanes()
        self.assertEqual(lanes['critical.jsonl'], [])
        self.assertEqual(manifest['coverage']['export_validation'], {'oversized_files': 1})
        self.assertNotIn('PRIVATE', json.dumps(manifest) + json.dumps(lanes))

    def test_metric_counts_do_not_assume_every_recurrence_was_measured(self):
        self.log.record('recognition', reason='recognized', inference_ms=10)
        self.log.record('recognition', reason='recognized')
        self.log.record('recognition', reason='recognized', inference_ms=30)
        _, lanes = self.export_lanes()
        value = next(row for row in lanes['critical.jsonl'] if row['event'] == 'recognition')
        self.assertEqual(value['occurrences'], 3)
        self.assertEqual(value['inference_ms_count'], 2)
        self.assertEqual(value['inference_ms_mean'], 20)

    def test_repeated_benign_flicker_does_not_evict_distinct_error_frame(self):
        self.log = LocalDebugLog(self.root / 'error-context', version='0.4.11', max_bytes=32768)
        now = [0]
        with patch.object(self.log, '_elapsed', lambda: now[0]):
            self.log.set_enabled(True)
            self.log.record('job', kind='ocr', phase='queued', serial=1, generation=1)
            self.log.record('capture', phase='acquired', capture_ms=40, serial=1, generation=1)
            self.log.record('inference', inference_stage='ocr', phase='started', serial=1, generation=1)
            now[0] = 6500
            self.log.record('inference', inference_stage='ocr', phase='completed', inference_ms=6500, serial=1, generation=1)
            self.log.record('capture', phase='discarded', reason='stale_frame', age_ms=6500, ttl_ms=4000, serial=1, generation=1)
            self.log.record('overlay', phase='hidden', visible=False, reason='stale_frame', serial=1, generation=1)
            for serial in range(2, 502):
                now[0] += 700
                self.log.record('overlay', phase='hidden', visible=False, reason='capture_pending', serial=serial, generation=1)
                self.log.record('capture', phase='acquired', capture_ms=20, serial=serial, generation=1)
                self.log.record('overlay', phase='shown', visible=True, reason='recognized', serial=serial, generation=1)
            manifest, lanes = self.export_lanes()
        frame = [row for row in lanes['context.jsonl'] if row.get('serial') == 1]
        self.assertTrue(any(row.get('phase') == 'queued' for row in frame))
        self.assertTrue(any(row.get('phase') == 'acquired' for row in frame))
        self.assertTrue(any(row.get('inference_ms') == 6500 for row in frame))
        self.assertTrue(any(row.get('reason') == 'stale_frame' for row in frame))
        self.assertGreater(manifest['counters']['context_truncated_frames'], 0)
        self.assertLessEqual(len(self.log._context_causes), 16)
        self.assertLessEqual(sum(path.stat().st_size for path in self.log.directory.iterdir()), 3 * 32768)

    def test_critical_overflow_reports_lost_observations_without_unbounded_files(self):
        for generation in range(200):
            self.log.record('state', generation=generation, state='waiting')
        manifest, lanes = self.export_lanes()
        self.assertGreater(manifest['counters']['critical_truncated_observations'], 0)
        kept = sum(row['occurrences'] for row in lanes['critical.jsonl'])
        self.assertEqual(kept + manifest['coverage']['critical_observation_loss'], manifest['counters']['critical_observations'])
        self.assertLessEqual(sum(path.stat().st_size for path in self.log.directory.iterdir()), 3 * self.log.max_bytes)
        self.assertTrue(any(row.get('generation') == 199 for row in lanes['critical.jsonl']))

    def test_rotation_distinguishes_prior_launch_rows(self):
        other = LocalDebugLog(self.log.directory, version='0.4.11', max_bytes=4096)
        other.set_enabled(True)
        for serial in range(200):
            other.record('capture', serial=serial)
        with zipfile.ZipFile(other.export_zip(self.root / 'other-export', config={})) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        self.assertGreater(manifest['counters']['truncated_prior_launch_records'], 0)
        self.assertGreater(manifest['counters']['truncated_current_launch_records'], 0)
        self.assertEqual(manifest['summary']['events']['capture']['observations'], 200)

    def test_45_minute_interleaved_replay_retains_early_gate_and_late_causal_frame(self):
        # Entire replay is invented. No user's logs, images, account IDs, or OCR.
        # 15 normal observations per 600 ms frame reproduces ~25 events/second.
        now = [0.0]
        with patch('local_debug.LocalDebugLog._elapsed', lambda unused: now[0]):
            self.log = LocalDebugLog(self.root / 'long-logs', version='0.4.11')
            self.log.set_enabled(True)
            self.log.record_config({'hero_auto': True, 'client_follow': True, 'lcu_selection': False, 'visible_capture': True})
            game = self.log.begin_game()
            offset = 0
            late_serial = 4000
            for serial in range(4500):
                now[0] = serial * 600 + offset
                client = serial < 50
                context = {'generation': 1, 'serial': serial}
                if serial == 50:
                    self.log.record('session', phase='accepted', stage='game-verified', **context)
                if serial == 200:
                    self.log.record_config({'hero_auto': True, 'client_follow': True, 'lcu_selection': True, 'visible_capture': True})
                self.log.record('selection_gate', selection_gate='client_pixels_ready' if client else 'game_pixels_ready',
                                selection_route='selection_pixels' if client else 'game_pixels',
                                target_role='client' if client else 'game', lcu_selection=serial >= 200,
                                hero_auto=True, pixel_fallback=False, target_present=True, target_foreground=True, **context)
                self.log.sample('capture', capture_mode='eligible', **context)
                self.log.record('capture', phase='requested', reason='capture_wait', visible_capture=True, **context)
                self.log.record('job', kind='selection' if client else 'ocr', phase='queued', **context)
                self.log.record('job', kind='selection' if client else 'ocr', phase='started', queue_ms=2, **context)
                self.log.record('capture', phase='started', **context)
                self.log.record('capture', phase='acquired', capture_ms=40, backend='windows-graphics-capture-session', capture_status='ok', **context)
                self.log.record('inference', phase='started', inference_stage='hud_match', **context)
                self.log.record('inference', phase='completed', inference_stage='hud_match', inference_ms=12, **context)
                self.log.record('inference', phase='started', inference_stage='ocr', **context)
                if serial % 30 == 0:
                    self.log.record('overlay', phase='rechecking', visible=True, rechecking=True, reason='title_recheck', **context)
                if serial == late_serial:
                    now[0] += 6500
                    offset += 6500
                self.log.record('inference', phase='completed', inference_stage='ocr', inference_ms=6500 if serial == late_serial else 50, **context)
                self.log.record('capture', phase='completed', capture_ms=40, inference_ms=6512 if serial == late_serial else 62, **context)
                self.log.record('job', kind='selection' if client else 'ocr', phase='completed', dispatch_ms=1, **context)
                self.log.record('recognition', reason='recognized', hero_present=True, stage='assigned' if client else 'game-verified', **context)
                self.log.record('state', state='confirmed', stage='assigned' if client else 'game-verified', **context)
                if serial == late_serial:
                    self.log.record('capture', phase='discarded', reason='stale_frame', age_ms=6500, ttl_ms=4000, **context)
                    self.log.record('overlay', phase='hidden', visible=False, reason='stale_frame', **context)
                if serial == late_serial + 1:
                    self.log.record('overlay', phase='shown', visible=True, reason='recognized', **context)
                if serial % 30 == 0:
                    self.log.record('overlay', phase='rechecking', visible=True, rechecking=False, reason='title_recheck', **context)
            now[0] = 2700000 + offset
            manifest, lanes = self.export_lanes(game_generation=game)
        critical, exact, tail = (lanes[name] for name in ('critical.jsonl', 'context.jsonl', 'events.jsonl'))
        early = next(row for row in critical if row.get('selection_gate') == 'client_pixels_ready')
        self.assertFalse(early['lcu_selection'])
        self.assertEqual(early['selection_route'], 'selection_pixels')
        self.assertLess(early['first_elapsed_ms'], 30000)
        configs = [row for row in critical if row['event'] == 'config']
        self.assertEqual([row['lcu_selection'] for row in configs], [False, True])
        self.assertTrue(all(row['occurrences'] == 1 for row in configs))
        self.assertTrue(any(row['event'] == 'session' and row.get('stage') == 'game-verified' for row in critical))
        frame = [row for row in exact if row.get('serial') == late_serial]
        self.assertTrue(any(row.get('phase') == 'queued' and row['event'] == 'job' for row in frame))
        self.assertTrue(any(row.get('phase') == 'acquired' and row.get('capture_ms') == 40 for row in frame))
        slow = next(row for row in frame if row.get('inference_stage') == 'ocr' and row.get('phase') == 'completed')
        stale = next(row for row in frame if row.get('reason') == 'stale_frame' and row['event'] == 'capture')
        hidden = next(row for row in frame if row.get('phase') == 'hidden')
        self.assertEqual(slow['inference_ms'], 6500)
        self.assertGreater(stale['age_ms'], stale['ttl_ms'])
        self.assertLess(slow['sequence'], stale['sequence'])
        self.assertLess(stale['sequence'], hidden['sequence'])
        self.assertTrue(any(row.get('serial') == late_serial + 1 and row.get('phase') == 'shown' for row in exact))
        self.assertFalse(any(row.get('selection_gate') == 'client_pixels_ready' for row in tail))
        self.assertFalse(any(row.get('serial') == late_serial for row in tail))
        self.assertGreater(manifest['counters']['rotations'], 3)
        self.assertGreater(manifest['counters']['aggregated_samples'], 30000)
        self.assertEqual(manifest['coverage']['critical_observation_loss'], 0)
        self.assertEqual(manifest['summary']['events']['capture']['observations'], 4500 * 5 + 1)
        self.assertEqual(manifest['summary']['inference_stages']['ocr']['latency']['max_ms'], 6500)
        self.assertEqual(manifest['summary']['overlay']['observed_hide_transitions'], 1)
        self.assertEqual(manifest['summary']['overlay']['hidden_total_ms'], 600)
        self.assertLessEqual(sum(path.stat().st_size for path in self.log.directory.iterdir()), 768 * 1024)
        with zipfile.ZipFile(self.root / 'export' / 'VGA-debug.zip') as archive:
            self.assertLessEqual(sum(row.file_size for row in archive.infolist()), 832 * 1024)
        self.assertLessEqual(len(self.log._samples), 64)

    def test_invalid_export_filter_preserves_previous_archive(self):
        self.export()
        target = self.root / 'export' / 'VGA-debug.zip'
        before = target.read_bytes()
        for options in ({'recent_seconds': -1}, {'recent_seconds': float('nan')}, {'game_generation': True}):
            with self.assertRaises(ValueError):
                self.export(**options)
            self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
