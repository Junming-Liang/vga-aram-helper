"""Cross-game causal retention without native identities, payloads or free text."""
from concurrent.futures import CancelledError
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import zipfile

from local_debug import LocalDebugLog, classify_worker_error


class ScopeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = LocalDebugLog(self.root / 'logs', version='0.4.13', max_bytes=4096)
        self.log.set_enabled(True)

    def exported(self, **filters):
        path = self.log.export_zip(self.root / 'export', config={}, **filters)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'events.jsonl', 'critical.jsonl', 'context.jsonl'})
            self.assertLessEqual(sum(i.file_size for i in archive.infolist()), self.log.max_bytes * 3 + 65536)
            self.assertLessEqual(path.stat().st_size, self.log.max_bytes * 3 + 65536)
            manifest = json.loads(archive.read('manifest.json'))
            lanes = {name: [json.loads(line) for line in archive.read(name).splitlines()]
                     for name in ('events.jsonl', 'critical.jsonl', 'context.jsonl')}
        self.assertLessEqual(sum(p.stat().st_size for p in self.log.directory.iterdir()), self.log.max_bytes * 3)
        return manifest, lanes

    def test_identity_enum_drift_and_independent_initial_card_binding_causes(self):
        from live_client_identity import API_OUTCOMES, MAP_OUTCOMES, IDENTITY_OUTCOMES
        from hero_recognition import HUD_OUTCOMES
        from local_debug import _IDENTITY_ENUMS
        for field, codes in (('api_outcome', API_OUTCOMES), ('map_outcome', MAP_OUTCOMES),
                             ('identity_outcome', IDENTITY_OUTCOMES), ('hud_outcome', HUD_OUTCOMES)):
            self.assertEqual(_IDENTITY_ENUMS[field], frozenset(codes))
            for code in codes:
                self.log.record('identity', **{field: code})
        for code in ('adopted', 'adoption_rejected', 'no_candidate', 'unchanged'):
            self.log.record('window_binding', binding_outcome=code, target_role='game')
        self.log.record('card_observation', reason='candidate_missing', hero_present=True,
                        card_geometry_proven=False, title_evidence_valid=False, candidate_count=0)
        manifest, lanes = self.exported()
        for field, codes in _IDENTITY_ENUMS.items():
            self.assertEqual(set(manifest['summary'][field + 's']), codes)
        self.assertEqual(len(manifest['summary']['binding_outcomes']), 4)
        cards = [row for row in lanes['critical.jsonl'] if row['event'] == 'card_observation']
        self.assertEqual(cards[0]['reason'], 'candidate_missing')
        self.assertTrue(cards[0]['hero_present'])
        self.assertFalse(cards[0]['card_geometry_proven'])

    def test_classifier_never_reads_messages_and_is_bounded_for_nested_causes(self):
        class PrivateError(Exception):
            def __str__(self):
                raise AssertionError('Do not inspect error messages')
        for cls, expected in ((CancelledError, 'cancelled'), (TimeoutError, 'timeout'),
                (ConnectionError, 'connection_error'), (PermissionError, 'permission_error'),
                (FileNotFoundError, 'file_missing'), (MemoryError, 'memory_error'),
                (ValueError, 'value_error'), (TypeError, 'type_error'), (KeyError, 'key_error'),
                (IndexError, 'index_error'), (AttributeError, 'attribute_error'),
                (RuntimeError, 'runtime_error'), (OSError, 'os_error'), (PrivateError, 'unknown')):
            self.assertEqual(classify_worker_error(cls('PRIVATE')), expected)
        self.assertEqual(classify_worker_error(PrivateError(), error_code='capture_paused'), 'capture_paused')
        self.assertEqual(classify_worker_error(PrivateError(), error_code='capture_unavailable'), 'capture_unavailable')
        certificate = ssl.SSLCertVerificationError(1, 'PRIVATE_CERT')
        wrapped = URLError('PRIVATE_URL'); wrapped.__cause__ = certificate
        outer = RuntimeError('PRIVATE_WRAPPER'); outer.__cause__ = wrapped
        self.assertEqual(classify_worker_error(outer), 'tls_verification_failed')
        self.assertEqual(classify_worker_error(URLError(certificate)), 'tls_verification_failed')
        self.assertEqual(classify_worker_error(ssl.SSLError('PRIVATE')), 'tls_error')
        self.assertEqual(classify_worker_error(HTTPError('PRIVATE_URL', 500, 'PRIVATE', {}, None)), 'http_error')
        self.assertEqual(classify_worker_error(URLError(TimeoutError())), 'timeout')
        self.assertEqual(classify_worker_error(URLError(ConnectionError())), 'connection_error')
        self.assertEqual(classify_worker_error(URLError('PRIVATE')), 'network_error')
        first = URLError(None); second = URLError(first); first.reason = second
        self.assertEqual(classify_worker_error(first), 'network_error')
        outer.__cause__ = outer
        self.assertEqual(classify_worker_error(outer), 'runtime_error')
        deep = certificate
        for unused in range(10): deep = URLError(deep)
        self.assertEqual(classify_worker_error(deep), 'network_error')

    def test_unknown_identity_failure_and_card_fields_never_reach_any_lane_or_manifest(self):
        self.log.record('identity', api_outcome='PRIVATE_API', hud_outcome='PRIVATE_HUD',
                        identity_outcome='PRIVATE_PLAYER', map_outcome='PRIVATE_PATH', payload='PRIVATE_JSON')
        self.log.record('job', phase='error', worker_error_category='PRIVATE_ERROR', raw_error='PRIVATE_MESSAGE')
        self.log.record('window_binding', binding_outcome='PRIVATE_TITLE', hwnd=123)
        self.log.record('card_observation', card_geometry_proven='PRIVATE', title_evidence_valid=1,
                        raw_ocr='PRIVATE_OCR', token='PRIVATE_TOKEN')
        manifest, lanes = self.exported()
        self.assertNotIn('PRIVATE', json.dumps(manifest) + json.dumps(lanes))
        self.assertNotIn('hwnd', json.dumps(lanes))

    def test_queued_scope_survives_late_worker_and_sample_flush_without_duplicate_failures(self):
        with patch.object(self.log, '_elapsed', return_value=10):
            first = self.log.begin_game(); worker = self.log.scoped()
            worker.record('job', phase='queued', kind='ocr', generation=1, serial=9)
        with patch.object(self.log, '_elapsed', return_value=20):
            second = self.log.begin_game()
            self.log.record('identity', api_outcome='verified', identity_outcome='api_verified')
            worker.record('identity', api_outcome='active_player_mismatch', identity_outcome='hud_abstained', generation=1, serial=9)
            worker.record('job', phase='error', kind='ocr', worker_error_category='key_error', generation=1, serial=9)
            self.log.record('job', phase='accepted', reason='worker_error')
            for duration in (10, 20, 30):
                worker.sample('capture', phase='completed', capture_ms=duration, generation=1, serial=9, game_generation=second)
            manifest, lanes = self.exported()
        games = {row['game_generation']: row for row in manifest['game_summaries']['games']}
        self.assertEqual(games[first]['worker_errors'], 1)
        self.assertEqual(games[second]['worker_errors'], 0)
        self.assertEqual(games[first]['causes']['api_outcome']['active_player_mismatch']['observations'], 1)
        self.assertNotIn('active_player_mismatch', games[second]['causes']['api_outcome'])
        summaries = [row for row in lanes['events.jsonl'] if row['event'] == 'sample_summary']
        self.assertEqual(len(summaries), 1)
        self.assertEqual((summaries[0]['game_generation'], summaries[0]['sample_count']), (first, 2))
        old = [row for rows in lanes.values() for row in rows if row.get('generation') == 1]
        self.assertTrue(old)
        self.assertTrue(all(row['game_generation'] == first for row in old))
        _, selected = self.exported(game_generation=second)
        self.assertFalse(any(row.get('worker_error_category') == 'key_error' for rows in selected.values() for row in rows))

    def test_reason_counts_first_last_and_explicit_whole_scope_eviction(self):
        from local_debug import _CAUSE_DIMENSIONS, _ENUMS, MAX_GAME_SUMMARIES, GAME_SUMMARY_BYTES
        first = self.log.begin_game(); old = self.log.scoped()
        with patch.object(self.log, '_elapsed', return_value=10):
            self.log.record('identity', api_outcome='tls_verification_failed', hud_outcome='templates_unavailable', identity_outcome='hud_abstained')
            self.log.record('job', phase='error', worker_error_category='key_error', reason='worker_error')
        with patch.object(self.log, '_elapsed', return_value=40):
            self.log.record('identity', api_outcome='active_player_mismatch', hud_outcome='score_low', identity_outcome='hud_abstained')
            self.log.record('recognition', reason='hero_unknown')
        manifest, _ = self.exported()
        game = next(row for row in manifest['game_summaries']['games'] if row['game_generation'] == first)
        self.assertEqual(game['first_causes']['api_outcome'], 'tls_verification_failed')
        self.assertEqual(game['last_causes']['api_outcome'], 'active_player_mismatch')
        self.assertEqual(game['causes']['identity_outcome']['hud_abstained'], {'observations': 2, 'first_elapsed_ms': 10, 'last_elapsed_ms': 40})
        self.assertEqual((game['first_reason'], game['last_reason']), ('worker_error', 'hero_unknown'))
        for unused in range(7):
            self.log.begin_game()
            for field in _CAUSE_DIMENSIONS:
                for code in _ENUMS[field]: self.log.record('identity', **{field: code})
        before = set(self.log._game_summaries)
        old.record('job', phase='error', worker_error_category='timeout')
        self.assertTrue(before <= set(self.log._game_summaries))
        if first in self.log._game_summaries:
            self.assertFalse(self.log._game_summaries[first]['complete_observed_scope'])
        manifest, _ = self.exported()
        ledger = manifest['game_summaries']; games = ledger['games']
        self.assertLessEqual(len(games), MAX_GAME_SUMMARIES)
        self.assertLessEqual(len(json.dumps(games, separators=(',', ':')).encode()), GAME_SUMMARY_BYTES)
        self.assertGreater(ledger['evicted_scope_summaries'], 0)
        self.assertGreater(ledger['evicted_observations'], 0)
        total = sum(row['observations'] for row in games) + ledger['evicted_observations']
        self.assertEqual(total, sum(row['observations'] for row in manifest['summary']['events'].values()))

    def test_45_minute_two_scope_errors_and_initial_card_gate_survive_rotation(self):
        now = [0.0]
        with patch('local_debug.LocalDebugLog._elapsed', lambda unused: now[0]):
            self.log = LocalDebugLog(self.root / 'long-game', version='0.4.13')
            self.log.set_enabled(True); first = self.log.begin_game()
            self.log.record('templates', template_outcome='unavailable', worker_error_category='connection_error', generation=1, error='PRIVATE_TRANSPORT')
            self.log.record('templates', template_outcome='retry_wait', ttl_ms=30000, generation=1)
            self.log.record('templates', template_outcome='ready', generation=2)
            self.log.record('window_binding', binding_outcome='adopted', target_role='client', generation=1, serial=0)
            self.log.record('selection_gate', selection_gate='client_pixels_ready', selection_route='selection_pixels', lcu_selection=False)
            for serial in range(2700):
                now[0] = serial * 1000
                if serial == 900: second = self.log.begin_game()
                context = {'serial': serial, 'generation': 1 if serial < 900 else 2}
                self.log.record('job', kind='ocr', phase='queued', **context)
                self.log.record('capture', phase='acquired', capture_ms=40, **context)
                self.log.record('inference', phase='started', inference_stage='hero_resolve', **context)
                failed = serial >= 900
                api = 'verified' if not failed else 'tls_verification_failed' if serial < 1500 else 'active_player_mismatch'
                hud = 'recognized' if not failed else 'templates_unavailable' if serial < 1200 else 'score_low'
                self.log.record('identity', api_outcome=api, hud_outcome=hud,
                                identity_outcome='hud_abstained' if failed else 'api_verified', map_outcome='verified', **context)
                self.log.record('inference', phase='completed', inference_stage='hero_resolve', inference_ms=25, **context)
                if serial == 0:
                    self.log.record('card_observation', reason='candidate_missing', hero_present=True, candidate_count=0, card_geometry_proven=False, title_evidence_valid=False, **context)
                self.log.record('recognition', reason='awaiting_confirmation' if serial == 0 else 'hero_unknown' if failed else 'recognized', hero_present=not failed, **context)
                if serial == 0:
                    self.log.record('overlay', phase='hidden', reason='unconfirmed', visible=False, **context)
                elif serial == 1:
                    self.log.record('overlay', phase='shown', reason='recognized', visible=True, **context)
                if 900 <= serial < 952:
                    self.log.record('job', kind='ocr', phase='error', error_code='worker_error',
                                    worker_error_category='key_error' if serial < 926 else 'timeout', **context)
                    self.log.record('job', kind='ocr', phase='accepted', reason='worker_error', **context)
                for offset in range(4): self.log.record('capture', capture_ms=offset, **context)
            manifest, lanes = self.exported()
        games = {row['game_generation']: row for row in manifest['game_summaries']['games']}
        self.assertEqual(games[first]['causes']['identity_outcome']['api_verified']['observations'], 900)
        bad = games[second]
        self.assertEqual(bad['causes']['identity_outcome']['hud_abstained']['observations'], 1800)
        self.assertEqual(bad['worker_errors'], 52)
        templates = [row for row in lanes['critical.jsonl'] if row['event']=='templates']
        self.assertEqual([row['template_outcome'] for row in templates], ['unavailable','retry_wait','ready'])
        self.assertEqual(templates[0]['worker_error_category'],'connection_error')
        self.assertEqual(templates[1]['ttl_ms'],30000)
        self.assertNotIn('PRIVATE_TRANSPORT',json.dumps([manifest,lanes]))
        for category in ('key_error', 'timeout'):
            self.assertEqual(bad['causes']['worker_error_category'][category]['observations'], 26)
        self.assertEqual(bad['causes']['api_outcome']['tls_verification_failed'], {'observations': 600, 'first_elapsed_ms': 900000, 'last_elapsed_ms': 1499000})
        self.assertEqual(bad['causes']['api_outcome']['active_player_mismatch']['observations'], 1200)
        self.assertEqual((bad['first_causes']['api_outcome'], bad['last_causes']['api_outcome']), ('tls_verification_failed', 'active_player_mismatch'))
        self.assertFalse(any(row.get('phase') == 'error' or row['event'] == 'card_observation' for row in lanes['events.jsonl']))
        errors = [row for row in lanes['critical.jsonl'] if row['event'] == 'job' and row.get('phase') == 'error']
        self.assertEqual(sum(row['occurrences'] for row in errors), 52)
        self.assertEqual({row['worker_error_category'] for row in errors}, {'key_error', 'timeout'})
        self.assertTrue(any(row['event'] == 'card_observation' and row.get('reason') == 'candidate_missing' for row in lanes['critical.jsonl']))
        self.assertTrue(any(row.get('selection_gate') == 'client_pixels_ready' for row in lanes['critical.jsonl']))
        self.assertTrue(any(row.get('game_generation') == first and row.get('identity_outcome') == 'api_verified' for row in lanes['critical.jsonl']))
        initial = sorted((row for row in lanes['context.jsonl'] if row.get('serial') == 0 and row.get('generation') == 1), key=lambda row: row['sequence'])
        chain = [row['event'] for row in initial if row['event'] in ('window_binding', 'identity', 'card_observation', 'recognition', 'overlay')]
        self.assertEqual(chain, ['window_binding', 'identity', 'card_observation', 'recognition', 'overlay'])
        exact = [row for row in lanes['context.jsonl'] if row.get('serial') == 951]
        for phase in ('queued', 'acquired', 'error'):
            self.assertTrue(any(row.get('phase') == phase for row in exact), phase)
        self.assertGreater(manifest['counters']['rotations'], 3)
        self.assertEqual(manifest['coverage']['critical_observation_loss'], 0)

    def test_initial_card_failure_keeps_frame_context_without_a_hide_event(self):
        now = [0.0]
        with patch.object(self.log, '_elapsed', side_effect=lambda: now[0]):
            self.log.begin_game()
            context = {'generation': 1, 'serial': 0}
            self.log.record('job', phase='queued', kind='ocr', **context)
            self.log.record('capture', phase='acquired', capture_ms=20, **context)
            self.log.record('identity', api_outcome='verified', identity_outcome='api_verified', **context)
            self.log.record('card_observation', reason='candidate_missing', hero_present=True, **context)
            for serial in range(1, 1000):
                now[0] = serial * 1000
                self.log.record('capture', generation=1, serial=serial, capture_ms=20)
            manifest, lanes = self.exported()
        initial = sorted((row for row in lanes['context.jsonl'] if row.get('serial') == 0), key=lambda row: row['sequence'])
        self.assertEqual([row['event'] for row in initial], ['job', 'capture', 'identity', 'card_observation'])
        self.assertFalse(any(row.get('serial') == 0 for row in lanes['events.jsonl']))
        self.assertEqual(manifest['summary']['overlay']['observed_hide_transitions'], 0)

    def test_saturated_vocabularies_and_manifest_guard_keep_existing_archive(self):
        from local_debug import _ENUMS, _EVENTS, _TIMINGS, _CAUSE_DIMENSIONS, GAME_SUMMARY_BYTES
        large = 2**53; metrics = {key: 86400000 for key in _TIMINGS}
        with patch.object(self.log, '_elapsed', return_value=large):
            for event in _EVENTS: self.log._observe(event, metrics, self.log._game_generation)
            for field, codes in _ENUMS.items():
                for code in codes: self.log._observe('identity', {field: code, **metrics}, self.log._game_generation)
            for dimension, buckets in self.log._summary.items():
                for bucket in buckets.values():
                    if dimension == 'timings': bucket.update(count=large, total_ms=large)
                    else:
                        bucket['observations'] = large
                        bucket['latency'].update(count=large, total_ms=large)
            for unused in range(4):
                scope = self.log.begin_game()
                for field in _CAUSE_DIMENSIONS:
                    for code in _ENUMS[field]: self.log._observe('identity', {field: code}, scope)
                for game in self.log._game_summaries.values():
                    game['observations'] = game['worker_errors'] = large
                    game['events'] = {event: large for event in _EVENTS - {'sample_summary'}}
                    for codes in game['causes'].values():
                        for bucket in codes.values(): bucket['observations'] = large
                self.log._observe('identity', {}, scope)
            manifest, _ = self.exported()
        self.assertLessEqual(len(json.dumps(manifest['game_summaries']['games'], separators=(',', ':')).encode()), GAME_SUMMARY_BYTES)
        target = self.root / 'export' / 'VGA-debug.zip'; before = target.read_bytes()
        with patch.object(self.log, '_summary_snapshot', return_value={'oversize': 'x' * 65536}):
            with self.assertRaisesRegex(ValueError, 'manifest budget'): self.exported()
        self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__': unittest.main()
