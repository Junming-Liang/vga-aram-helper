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
            'debug_enabled', 'overlay', 'capture', 'sample_summary', 'recognition', 'recognition', 'overlay'])
        summary = events[3]
        self.assertEqual(summary['sampled_event'], 'capture')
        self.assertEqual(summary['sample_count'], 2)
        self.assertEqual((summary['first_serial'], summary['last_serial']), (1, 2))
        self.assertEqual((summary['capture_ms_min'], summary['capture_ms_max'], summary['capture_ms_mean']), (20, 40, 30))
        self.assertEqual(manifest['counters']['aggregated_samples'], 2)
        self.assertEqual([item['sequence'] for item in events], list(range(1, 8)))
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
        self.assertEqual(manifest['diagnostic_profile'],'capture-stability-v1')

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
        self.assertIsNone(self.log._pending)
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
