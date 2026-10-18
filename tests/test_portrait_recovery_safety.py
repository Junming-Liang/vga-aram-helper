"""Public-portrait recovery safety with owned assets and Qt worker fixtures.

No live network, game/client process, Windows capture, or real screenshot is
used. Fake time advances retry deadlines without sleeping through backoff.
"""
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hero_portraits
from tests import test_native_capture_worker as fixtures


VERSION = '16.20.1'


def owned_roster():
    return {'version': VERSION, 'data': {
        str(i): {'key': str(i), 'id': 'Owned' + str(i),
                 'image': {'full': 'Owned' + str(i) + '.png'}}
        for i in range(1, 101)}}


def owned_fetch(url, **kwargs):
    if kwargs['hosts'] != hero_portraits.HOSTS:
        raise AssertionError('Public HTTPS host guard changed')
    if url.endswith('versions.json'):
        return json.dumps([VERSION]).encode()
    if url.endswith('champion.json'):
        return json.dumps(owned_roster()).encode()
    return b'owned-portrait-bytes'


class PortraitPublicationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name)
        decoder = patch.object(hero_portraits, 'decode_portrait',
                               side_effect=lambda payload: ('owned', payload))
        decoder.start()
        self.addCleanup(decoder.stop)

    def seed_cache(self):
        bank, status = hero_portraits.load_portraits(self.cache, fetcher=owned_fetch)
        self.assertEqual(len(bank), 100)
        self.assertEqual(status['state'], 'fresh')
        return bank, status

    def test_cache_callback_precedes_network_and_final_keeps_bank_identity(self):
        self.seed_cache()
        published = []
        def fetch(url, **kwargs):
            self.assertEqual(len(published), 1)
            self.assertEqual(len(published[0][0]), 100)
            return owned_fetch(url, **kwargs)
        bank, status = hero_portraits.load_portraits(
            self.cache, fetcher=fetch,
            cached_callback=lambda bank, status: published.append((bank, status)))
        self.assertIs(bank, published[0][0])
        self.assertEqual(status['state'], 'current')

    def test_corrupt_hash_or_partial_cache_never_publishes(self):
        self.seed_cache()
        asset = self.cache / VERSION / 'Owned100.png'
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    asset.unlink()
                else:
                    asset.write_bytes(b'owned-corrupt-bytes')
                published = []
                bank, status = hero_portraits.load_portraits(
                    self.cache, allow_download=False,
                    cached_callback=lambda *value: published.append(value))
                self.assertFalse(bank)
                self.assertEqual(status['state'], 'unavailable')
                self.assertEqual(published, [])

    def test_malformed_manifest_and_hash_shapes_fail_closed(self):
        self.seed_cache()
        manifest = json.loads((self.cache / 'manifest.json').read_bytes())
        malformed = [None, [], 12, 'owned']
        malformed.extend(dict(manifest, hashes=value) for value in (None, [], 12, 'owned'))
        for value in malformed:
            with self.subTest(value=value):
                (self.cache / 'manifest.json').write_text(json.dumps(value))
                published = []
                bank, status = hero_portraits.load_portraits(
                    self.cache, allow_download=False,
                    cached_callback=lambda *value: published.append(value))
                self.assertFalse(bank)
                self.assertEqual(status['state'], 'unavailable')
                self.assertEqual(published, [])

    def test_cancelled_cache_load_never_emits_or_fetches(self):
        self.seed_cache()
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(hero_portraits, 'fetch_bytes') as fetch:
            published = []
            bank, _ = hero_portraits.load_portraits(
                self.cache, cancelled=cancelled,
                cached_callback=lambda *value: published.append(value))
        self.assertFalse(bank)
        self.assertEqual(published, [])
        fetch.assert_not_called()

    def test_cancel_after_cache_publication_does_not_start_network(self):
        self.seed_cache()
        cancelled = threading.Event()
        published = []
        def receive(bank, status):
            published.append(bank)
            cancelled.set()
        with patch.object(hero_portraits, 'fetch_bytes') as fetch:
            bank, _ = hero_portraits.load_portraits(
                self.cache, cancelled=cancelled, cached_callback=receive)
        self.assertEqual(len(published), 1)
        self.assertFalse(bank)
        fetch.assert_not_called()

    def test_invalid_image_shapes_and_duplicate_canonical_slugs_rejected(self):
        for shape in (None, [], 12, 'owned'):
            with self.subTest(image=shape):
                roster = owned_roster()
                roster['data']['1']['image'] = shape
                with self.assertRaises(ValueError):
                    hero_portraits.parse_roster(json.dumps(roster).encode(), VERSION)
        roster = owned_roster()
        roster['data']['2']['id'] = 'Owned1'
        roster['data']['2']['image']['full'] = 'Owned1.png'
        with self.assertRaises(ValueError):
            hero_portraits.parse_roster(json.dumps(roster).encode(), VERSION)

    def test_memory_only_result_contains_complete_valid_canonical_map(self):
        from live_client_identity import _valid_map
        with patch.object(hero_portraits, '_write_cache', side_effect=PermissionError('owned')):
            bank, status = hero_portraits.load_portraits(self.cache, fetcher=owned_fetch)
        self.assertEqual(status['state'], 'memory-only')
        self.assertEqual(len(status['canonicalMap']), len(bank))
        self.assertEqual(set(status['canonicalMap'].values()), set(bank))
        self.assertTrue(_valid_map(status['canonicalMap']))
        self.assertFalse((self.cache / 'manifest.json').exists())


@unittest.skipIf(fixtures.QtWidgets is None, 'Optional Qt runtime is not installed')
class PortraitRecoveryQtSafetyTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    wait = fixtures.NativeCaptureWorkerTests.wait
    dispose_window = fixtures.NativeCaptureWorkerTests.dispose_window

    def setUp(self):
        fixtures.NativeCaptureWorkerTests.setUp(self)
        w = self.window
        w.data['metadata']['isDemo'] = False
        w.enable_updates = True
        w._portraits_retry_at = 100.0

    def bank(self):
        from PIL import Image
        image = Image.new('RGB', (64, 64), (40, 90, 130))
        return {str(i): image.copy() for i in range(1, 101)}

    def status(self, state='cached'):
        return {'state': state, 'version': VERSION, 'message': 'Owned portrait result',
                'canonicalMap': {'Owned' + str(i): str(i) for i in range(1, 101)}}

    def request(self):
        with patch.object(self.window, 'spawn') as spawn:
            self.window.request_portraits()
        spawn.assert_called_once()
        return self.window._portraits_attempt

    def test_retry_checks_all_gates_before_starting_worker(self):
        w = self.window
        for gate in ('closed', 'busy', 'matcher', 'updates', 'stopped', 'manual',
                     'no_deadline', 'not_due', 'demo', 'no_data'):
            with self.subTest(gate=gate):
                data = w.data
                w.closed = False
                w._portraits_busy = False
                w.hero_matcher = None
                w.enable_updates = True
                w.state.running = True
                w.hero_auto.blockSignals(True)
                w.hero_auto.setChecked(True)
                w.hero_auto.blockSignals(False)
                w._portraits_retry_at = 100.0
                data['metadata']['isDemo'] = False
                if gate == 'closed': w.closed = True
                elif gate == 'busy': w._portraits_busy = True
                elif gate == 'matcher': w.hero_matcher = object()
                elif gate == 'updates': w.enable_updates = False
                elif gate == 'stopped': w.state.running = False
                elif gate == 'manual':
                    w.hero_auto.blockSignals(True); w.hero_auto.setChecked(False); w.hero_auto.blockSignals(False)
                elif gate == 'no_deadline': w._portraits_retry_at = None
                elif gate == 'not_due': w._portraits_retry_at = 102.0
                elif gate == 'demo': data['metadata']['isDemo'] = True
                elif gate == 'no_data': w.data = None
                try:
                    with patch.object(w, 'spawn') as spawn, patch('native_ui.time.monotonic', return_value=101.0):
                        w.retry_portraits()
                    spawn.assert_not_called()
                finally:
                    w.closed = False
                    w.data = data

    def test_retry_serialized_and_backoff_capped_without_real_waits(self):
        w = self.window
        now = 100.0
        for failures, delay in enumerate((30, 60, 120, 300, 300), 1):
            with patch.object(w, 'spawn') as spawn, patch('native_ui.time.monotonic', return_value=now):
                w.retry_portraits()
                w.retry_portraits()
                w.request_portraits()
            spawn.assert_called_once()
            attempt = w._portraits_attempt
            self.assertTrue(w._portraits_busy)
            with patch('native_ui.time.monotonic', return_value=now):
                w.task_error('portraits', 'Owned transient failure', attempt)
            self.assertFalse(w._portraits_busy)
            self.assertEqual(w._portraits_failures, failures)
            self.assertEqual(w._portraits_retry_at, now + delay)
            now += delay

    def test_cache_then_same_final_reuses_matcher_and_empty_cannot_replace(self):
        w = self.window
        bank = self.bank()
        attempt = self.request()
        with patch('hero_recognition.PortraitMatcher', return_value=object()) as matcher:
            w.task_result('portraits-cache', (bank, self.status()), attempt)
            instance, revision = w.hero_matcher, w.portrait_bank.revision
            self.assertTrue(w._portraits_busy)
            w.retry_portraits()
            w.task_result('portraits', (bank, self.status('current')), attempt)
        matcher.assert_called_once()
        self.assertIs(w.hero_matcher, instance)
        self.assertEqual(w.portrait_bank.revision, revision)
        self.assertFalse(w._portraits_busy)
        self.assertIsNone(w._portraits_retry_at)
        self.assertEqual(w._portraits_failures, 0)
        attempt = self.request()
        w.task_result('portraits', ({}, self.status('unavailable')), attempt)
        self.assertIs(w.hero_matcher, instance)
        self.assertIs(w._portraits_bank, bank)
        self.assertEqual(w.portrait_bank.revision, revision)

    def test_old_result_error_and_duplicate_terminal_preserve_current_lease(self):
        w = self.window
        old = self.request()
        with patch('native_ui.time.monotonic', return_value=100.0):
            w.task_error('portraits', 'Owned first failure', old)
        due, failures = w._portraits_retry_at, w._portraits_failures
        w.task_error('portraits', 'Owned duplicate failure', old)
        w.task_result('portraits', ({}, self.status('unavailable')), old)
        self.assertEqual((w._portraits_retry_at, w._portraits_failures), (due, failures))
        current = self.request()
        status_text = w.hero_status.text()
        revision = w.portrait_bank.revision
        with patch('hero_recognition.PortraitMatcher') as matcher:
            w.task_result('portraits-cache', (self.bank(), self.status()), old)
            w.task_result('portraits', ({}, self.status('unavailable')), old)
            w.task_error('portraits', 'Owned stale error', old)
        matcher.assert_not_called()
        self.assertTrue(w._portraits_busy)
        self.assertEqual(w._portraits_attempt, current)
        self.assertEqual(w.hero_status.text(), status_text)
        self.assertEqual(w.portrait_bank.revision, revision)
        self.assertEqual(w._portraits_failures, failures)

    def test_stop_start_preserves_retry_deadline_and_active_asset_lease(self):
        w = self.window
        w.capture = SimpleNamespace(retire_session=lambda: None)
        w._portraits_failures = 3
        w._portraits_retry_at = 500.0
        with patch.object(w, 'queue_discovery'), patch.object(w, 'spawn') as spawn:
            for _ in range(3):
                w.start_monitor()
                w.monitor.stop()
                with patch('native_ui.time.monotonic', return_value=499.0):
                    w.retry_portraits()
                w.stop_monitor()
            spawn.assert_not_called()
        self.assertEqual((w._portraits_failures, w._portraits_retry_at), (3, 500.0))
        attempt = self.request()
        with patch.object(w, 'queue_discovery'), patch.object(w, 'spawn') as spawn:
            w.start_monitor(); w.monitor.stop()
            with patch('native_ui.time.monotonic', return_value=600.0):
                w.retry_portraits()
            spawn.assert_not_called()
        self.assertTrue(w._portraits_busy)
        self.assertEqual(w._portraits_attempt, attempt)
        w.task_result('portraits', ({}, self.status('unavailable')), attempt)
        self.assertFalse(w._portraits_busy)

    def test_close_drops_cache_and_final_signals_from_held_worker(self):
        w = self.window
        entered, release = threading.Event(), threading.Event()
        self._release_events.append(release)
        bank = self.bank()
        received = []
        w.signals.result.connect(lambda kind, *args: received.append(kind))
        def load(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Owned worker release timed out')
            kwargs['cached_callback'](bank, self.status())
            return bank, self.status('current')
        with patch.object(hero_portraits, 'load_portraits', side_effect=load):
            w.request_portraits()
            self.wait(entered.is_set)
            revision = w.portrait_bank.revision
            w.close()
            release.set()
            self.wait(lambda: not w._workers)
        self.assertTrue(w._cancel_workers.is_set())
        self.assertNotIn('portraits-cache', received)
        self.assertNotIn('portraits', received)
        self.assertEqual(w.portrait_bank.revision, revision)
        with patch.object(w, 'spawn') as spawn:
            w.retry_portraits(); w.request_portraits()
        spawn.assert_not_called()

    def test_matcher_failure_keeps_old_bank_and_releases_terminal_lease(self):
        w = self.window
        previous = self.bank()
        attempt = self.request()
        with patch('hero_recognition.PortraitMatcher', return_value=object()):
            w.task_result('portraits', (previous, self.status()), attempt)
        matcher, revision = w.hero_matcher, w.portrait_bank.revision
        attempt = self.request()
        with patch('hero_recognition.PortraitMatcher', side_effect=RuntimeError('Owned constructor failure')):
            w.task_result('portraits-cache', (self.bank(), self.status()), attempt)
            self.assertTrue(w._portraits_busy)
            w.task_result('portraits', (self.bank(), self.status('fresh')), attempt)
        self.assertFalse(w._portraits_busy)
        self.assertIs(w.hero_matcher, matcher)
        self.assertIs(w._portraits_bank, previous)
        self.assertEqual(w.portrait_bank.revision, revision)

    def test_first_matcher_failure_schedules_retry_without_partial_publication(self):
        w = self.window
        attempt = self.request()
        revision = w.portrait_bank.revision
        with patch('hero_recognition.PortraitMatcher', side_effect=RuntimeError('Owned constructor failure')):
            w.task_result('portraits', (self.bank(), self.status('fresh')), attempt)
        self.assertFalse(w._portraits_busy)
        self.assertIsNone(w.hero_matcher)
        self.assertIsNone(w._portraits_bank)
        self.assertEqual(w.portrait_bank.revision, revision)
        self.assertEqual(w._portraits_failures, 1)
        self.assertIsNotNone(w._portraits_retry_at)

    def test_memory_map_is_detached_and_normal_disk_invalidation_is_preserved(self):
        from live_client_identity import _valid_map
        w = self.window
        bank, status = self.bank(), self.status('memory-only')
        attempt = self.request()
        with patch('hero_recognition.PortraitMatcher', return_value=object()):
            w.task_result('portraits', (bank, status), attempt)
        self.assertIsInstance(w._portrait_memory_map, tuple)
        status['canonicalMap']['Owned1'] = '999'
        outcomes = []
        mapping = w.canonical_champion_map(diagnostic_callback=outcomes.append)
        self.assertEqual(outcomes, ['verified_memory'])
        self.assertTrue(_valid_map(mapping))
        self.assertEqual(mapping['Owned1'], '1')
        mapping['Owned1'] = '998'
        self.assertEqual(w.canonical_champion_map()['Owned1'], '1')
        attempt = self.request()
        with patch('hero_recognition.PortraitMatcher', return_value=object()):
            w.task_result('portraits', (self.bank(), self.status('fresh')), attempt)
        self.assertEqual(w._portrait_memory_map, ())
        self.assertEqual(w.canonical_champion_map(), {})


if __name__ == '__main__':
    unittest.main()
