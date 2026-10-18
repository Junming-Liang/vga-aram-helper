"""Startup identity regressions with owned pixels, roster, and HTTP responses.

Production load/result, portrait loading, frame recognition, API parsing, and
identity state run unchanged. No network, client installation, or real game
screenshots are needed. This is not Windows capture evidence.

Baseline audit reproduced: one cold asset failure stayed unavailable forever,
warm verified portraits waited behind a remote versions request, and malformed
image records aborted capture before HUD/OCR. Their tests now require recovery.
Memory-only complete banks also provide a verified map without disk persistence.
The complete, strictly validated official roster now independently supplies the
API dictionary before portrait images finish. A partial image bank still never
becomes a HUD matcher, and fresh scoped API observations remain mandatory.
"""
import copy
import gc
import hashlib
import io
import json
import os
import ssl
import sys
import threading
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hero_portraits
from tests import test_native_capture_worker as fixtures
from tests import test_native_identity_diagnostics as diagnostics


# These bound owned test setup/delivery, not product capture freshness. The
# preparation really decodes and fsyncs 100 files, and can exceed the generic
# four-second UI wait on a busy Windows runner. API frame waits remain 4 seconds.
PREPARE_SECONDS = 30
DELIVERY_SECONDS = 5
OWNED_GATE_SECONDS = 60


class OwnedPortraitServer:
    """One transient remote asset failure or a controllably delayed response."""
    version = '16.20.1'

    def __init__(self, *, fail_once=None, block_suffix=None):
        from PIL import Image
        out = io.BytesIO()
        image = Image.new('RGB', (64, 64))
        image.putdata([(x * 3, y * 3, (x + y) * 2) for y in range(64) for x in range(64)])
        image.save(out, 'PNG')
        self.png = out.getvalue()
        self.roster = json.dumps({'version': self.version, 'data': {
            str(i): {'key': str(i), 'id': 'Owned' + str(i),
                     'image': {'full': 'Owned' + str(i) + '.png'}}
            for i in range(1, 101)
        }}).encode()
        self.fail_once = fail_once
        self.block_suffix = block_suffix
        self.entered = threading.Event()
        self.release = threading.Event()
        self.gate_expired = False
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, url, **kwargs):
        with self.lock:
            self.calls.append(url)
            fail = self.fail_once is not None and url.endswith(self.fail_once)
            if fail:
                self.fail_once = None
        if fail:
            raise TimeoutError('Owned one-time portrait timeout')
        if self.block_suffix and url.endswith(self.block_suffix):
            self.entered.set()
            if not self.release.wait(OWNED_GATE_SECONDS):
                self.gate_expired = True
                raise TimeoutError('Owned release not signalled')
        if url.endswith('versions.json'):
            return json.dumps([self.version]).encode()
        if url.endswith('champion.json'):
            return self.roster
        return self.png


@unittest.skipIf(fixtures.QtWidgets is None, 'Qt unavailable')
class IdentityColdStartAudit(unittest.TestCase):
    setUpClass = classmethod(fixtures.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp = fixtures.NativeCaptureWorkerTests.setUp
    wait = fixtures.NativeCaptureWorkerTests.wait
    events = diagnostics.NativeIdentityDiagnosticTests.events
    identity = diagnostics.NativeIdentityDiagnosticTests.identity

    def wait_stage(self, predicate, stage, seconds):
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        server = getattr(self, '_portrait_server', None)
        attempts = getattr(self, '_portrait_attempts', [])
        frames = sys._current_frames()
        stacks = {}
        for job in threading.enumerate():
            if job.name.startswith('vga') and job.ident in frames:
                stacks[job.name] = [f'{os.path.basename(row.filename)}:{row.lineno}:{row.name}'
                                    for row in traceback.extract_stack(frames[job.ident])[-6:]]
        detail = {'stage': stage, 'budget_s': seconds,
                  'elapsed_s': round(time.monotonic() - started, 3),
                  'responses': len(server.calls) if server else 0,
                  'server_gate_expired': server.gate_expired if server else False,
                  'cached_pngs': len(list((self.window.state_dir / 'hero-portraits').glob('*/*.png'))),
                  'attempts': [{'number': a.number, 'ready': a.ready.is_set(),
                                'released': a.release.is_set(), 'delivered': a.delivered.is_set(),
                                'outcome': a.outcome} for a in attempts],
                  'busy': self.window._portraits_busy,
                  'cancelled': self.window._cancel_workers.is_set(), 'threads': stacks}
        self.fail('Owned async fixture timeout: ' + json.dumps(detail, sort_keys=True))

    def dispose_window(self):
        """Release/drain before removing transport mocks, including failure paths."""
        w = self.window
        if w is None:
            return
        draining = getattr(self, '_fixture_draining', None)
        if draining is not None:
            draining.set()
        for event in self._release_events:
            event.set()
        overlay = w.overlay
        w.capture = None
        w.close()
        self.wait_stage(lambda: not w._workers, 'cleanup-worker-drain', PREPARE_SECONDS)
        inference = w.frame_inference_worker._thread
        if inference is not None:
            self.wait_stage(lambda: not inference.is_alive(), 'cleanup-inference-drain', DELIVERY_SECONDS)
        overlay.deleteLater()
        w.deleteLater()
        fixtures.QtCore.QCoreApplication.sendPostedEvents(None, fixtures.QtCore.QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(fixtures.isValid(overlay))
        self.assertFalse(fixtures.isValid(w))
        self.window = None
        gc.collect()
        self.app.processEvents()

    def prepare_game(self, *, warm_map=False):
        from PIL import Image
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        w = self.window
        self.meta = ProcessMetadata('C:/OWNED/League of Legends.exe', 12345)
        self.hero = next(iter(w.data['heroes']))
        w.data['heroes'][self.hero]['championId'] = '1'
        w.automatic_policy = SimpleNamespace(
            bound=SimpleNamespace(role='game', metadata=self.meta), stop=lambda: None)
        w.capture_metadata = lambda: self.meta
        png = io.BytesIO()
        Image.new('RGB', (1280, 720), (82, 92, 108)).save(png, 'PNG')

        class Capture:
            last_backend = 'window-dc'

            def capture(inner, *args, **kwargs):
                return png.getvalue(), ClientRect(0, 0, 1280, 720)

        class OCR:
            _engine = object()

            def recognize(inner, payload, vocabulary):
                with Image.open(io.BytesIO(payload)) as image:
                    return {'ocr_lines': [], 'candidates': [],
                            'image_size': {'width': image.width, 'height': image.height}}

        w.capture = Capture()
        w.ocr = OCR()
        if warm_map:
            diagnostics.write_roster(w.state_dir / 'hero-portraits')
        return w

    def start_portraits_through_load_result(self, server):
        """Invoke the same non-demo load-result branch as real startup."""
        w = self.window
        self._portrait_server = server
        self._portrait_attempts = []
        self._fixture_draining = threading.Event()
        progress_lock = threading.Lock()
        load = hero_portraits.load_portraits
        finish = w.finish_portrait_attempt

        def prepared_load(*args, **kwargs):
            attempt = SimpleNamespace(number=w._portraits_attempt, ready=threading.Event(),
                                      release=threading.Event(), delivered=threading.Event(),
                                      outcome='preparing', finish_before=None, finish_after=None)
            with progress_lock:
                self._portrait_attempts.append(attempt)
                self._release_events.append(attempt.release)
            error = None
            try:
                result = load(*args, **kwargs)
                attempt.outcome = result[1].get('state', 'unknown')
            except Exception as exc:
                error = exc
                attempt.outcome = type(exc).__name__
            finally:
                attempt.ready.set()
            # Separate real 100-image preparation from GUI publication. Tests
            # explicitly release this event; cleanup releases it on every exit.
            if self._fixture_draining.is_set():
                attempt.release.set()  # Also covers a worker dispatched during teardown.
            if not attempt.release.wait(OWNED_GATE_SECONDS):
                raise TimeoutError('Owned portrait publication was not released')
            if error is not None:
                raise error
            return result

        def observed_finish():
            attempt = next(a for a in self._portrait_attempts if a.number == w._portraits_attempt)
            attempt.finish_before = time.monotonic()
            try:
                return finish()
            finally:
                attempt.finish_after = time.monotonic()
                attempt.delivered.set()

        for target, name, callback in ((hero_portraits, 'load_portraits', prepared_load),
                                       (w, 'finish_portrait_attempt', observed_finish)):
            observed = patch.object(target, name, side_effect=callback)
            observed.start()
            self.addCleanup(observed.stop)
        network = patch.object(hero_portraits, 'fetch_bytes', side_effect=server)
        network.start()
        self.addCleanup(network.stop)
        updates = patch('updates.check_for_update', return_value={'state': 'owned', 'message': 'Owned'})
        updates.start()
        self.addCleanup(updates.stop)
        self._release_events.append(server.release)
        # unittest cleanup is LIFO: the window must drain while the mocks above
        # still exist. The original fixture cleanup later becomes a no-op.
        self.addCleanup(self.dispose_window)
        data = copy.deepcopy(w.data)
        data['metadata']['isDemo'] = False
        w.enable_updates = True
        w.task_result('load', {'data': data}, w.state.generation)
        self.app.processEvents()

    def portraits_settled(self):
        number = self.window._portraits_attempt
        self.wait_stage(lambda: any(a.number == number for a in self._portrait_attempts),
                        'portrait-dispatch', PREPARE_SECONDS)
        attempt = next(a for a in self._portrait_attempts if a.number == number)
        self.wait_stage(attempt.ready.is_set, 'portrait-prepare', PREPARE_SECONDS)
        attempt.release.set()
        self.wait_stage(lambda: attempt.delivered.is_set() and not self.window._portraits_busy
                        and not any(job.name == 'vga-portraits' for job in self.window._workers),
                        'portrait-qt-delivery', DELIVERY_SECONDS)
        self.assertFalse(self._portrait_server.gate_expired)
        return attempt

    def run_frame(self, *, failure=None, slug='Owned1'):
        w = self.window
        with patch('session_windows.process_metadata', return_value=self.meta), \
                patch('live_client_identity.ssl.create_default_context', return_value=ssl.create_default_context()), \
                patch('live_client_identity.http.client.HTTPSConnection',
                      side_effect=failure if failure is not None else diagnostics.connections(slug)) as http:
            w.capture_hidden(w.state.generation)
            self.wait_stage(lambda: not w.ocr_busy and not any(job.name == 'vga-ocr' for job in w._workers),
                            'fresh-api-frame', 4)
        return http

    def assert_fixture_drained(self):
        self.assertIsNone(self.window)
        self.assertFalse([job.name for job in threading.enumerate() if job.name.startswith('vga')])

    def test_fixture_prepared_result_requires_release_and_qt_delivery(self):
        original_fetch = hero_portraits.fetch_bytes
        with patch.object(hero_portraits, 'fetch_bytes', side_effect=AssertionError('Owned network escaped')) as escaped:
            try:
                w = self.prepare_game()
                self.start_portraits_through_load_result(OwnedPortraitServer())
                self.wait_stage(lambda: bool(self._portrait_attempts) and self._portrait_attempts[0].ready.is_set(),
                                'fixture-result-ready', PREPARE_SECONDS)
                attempt = self._portrait_attempts[0]
                self.assertEqual(attempt.outcome, 'fresh')
                self.assertFalse(attempt.release.is_set())
                self.assertFalse(attempt.delivered.is_set())
                self.assertTrue(w._portraits_busy)
                self.assertIsNone(w.hero_matcher)
                self.assertEqual(len(list((w.state_dir / 'hero-portraits/16.20.1').glob('*.png'))), 100)
                self.assertIs(self.portraits_settled(), attempt)
                self.assertTrue(attempt.release.is_set())
                self.assertTrue(attempt.delivered.is_set())
                self.assertEqual(len(w.hero_matcher.templates), 100)
            finally:
                self.assertTrue(self.doCleanups())
            escaped.assert_not_called()
        self.assertIs(hero_portraits.fetch_bytes, original_fetch)
        self.assert_fixture_drained()

    def test_fixture_prepare_timeout_releases_server_and_drains_before_unpatch(self):
        expected_transport = []
        mock_active_after_release = []

        class CheckedServer(OwnedPortraitServer):
            def __call__(inner, url, **kwargs):
                result = super().__call__(url, **kwargs)
                if url.endswith('/Owned2.png'):
                    mock_active_after_release.append(hero_portraits.fetch_bytes is expected_transport[0])
                return result

        with patch.object(hero_portraits, 'fetch_bytes', side_effect=AssertionError('Owned network escaped')) as escaped:
            try:
                w = self.prepare_game()
                server = CheckedServer(block_suffix='/Owned2.png')
                self.start_portraits_through_load_result(server)
                expected_transport.append(hero_portraits.fetch_bytes)
                self.wait_stage(server.entered.is_set, 'fixture-held-portrait', PREPARE_SECONDS)
                with self.assertRaisesRegex(AssertionError, '"stage": "injected-prepare-timeout"') as failure:
                    self.wait_stage(lambda: self._portrait_attempts[0].ready.is_set(),
                                    'injected-prepare-timeout', .02)
                self.assertIn('"ready": false', str(failure.exception))
                self.assertIn('vga-public-portrait', str(failure.exception))
                self.assertTrue(w._portraits_busy)
                self.assertIsNone(w.hero_matcher)
            finally:
                self.assertTrue(self.doCleanups())
            escaped.assert_not_called()
        self.assertEqual(mock_active_after_release, [True])
        self.assert_fixture_drained()

    def test_fixture_loader_exception_has_terminal_receipt_and_clean_exit(self):
        original_load = hero_portraits.load_portraits
        with patch.object(hero_portraits, 'fetch_bytes', side_effect=AssertionError('Owned network escaped')) as escaped, \
                patch.object(hero_portraits, 'load_portraits', side_effect=RuntimeError('Owned loader exception')):
            try:
                w = self.prepare_game()
                self.start_portraits_through_load_result(OwnedPortraitServer())
                attempt = self.portraits_settled()
                self.assertEqual(attempt.outcome, 'RuntimeError')
                self.assertTrue(attempt.delivered.is_set())
                self.assertFalse(w._portraits_busy)
                self.assertIsNone(w.hero_matcher)
                self.assertEqual(w._portraits_failures, 1)
            finally:
                self.assertTrue(self.doCleanups())
            escaped.assert_not_called()
        self.assertIs(hero_portraits.load_portraits, original_load)
        self.assert_fixture_drained()

    def test_healthy_map_retries_temporary_api_failure_and_recovers_without_restart(self):
        w = self.prepare_game(warm_map=True)
        for failure in (ConnectionRefusedError('Owned not ready'), TimeoutError('Owned slow')):
            self.run_frame(failure=failure)
            self.assertFalse(w.state.hero)
            self.assertFalse(w.hero_continuity.hero)
        self.run_frame()
        self.assertFalse(w.state.hero)
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)
        self.assertEqual(self.identity()['api_outcome'], 'verified')

    def test_cold_asset_failure_keeps_verified_api_and_retries_portraits_when_due(self):
        w = self.prepare_game()
        server = OwnedPortraitServer(fail_once='/Owned100.png')
        self.start_portraits_through_load_result(server)
        attempt = self.portraits_settled()
        self.assertIsNone(w.hero_matcher)
        self.assertFalse((w.state_dir / 'hero-portraits/manifest.json').exists())
        self.assertEqual(len(w.canonical_champion_map()), 100)
        self.assertIsNone(server.fail_once)  # All later server responses are healthy.
        self.assertFalse(w._portraits_busy)
        self.assertEqual(w._portraits_failures, 1)
        self.assertGreaterEqual(w._portraits_retry_at, attempt.finish_before + 30)
        self.assertLessEqual(w._portraits_retry_at, attempt.finish_after + 30)
        calls_after_failure = len(server.calls)
        for frame in range(3):
            http = self.run_frame()
            self.assertEqual(http.call_count, 4)
            self.assertEqual(w.state.hero, self.hero if frame else '')
            self.assertEqual(self.identity()['api_outcome'], 'verified')
            self.assertEqual(self.identity()['map_outcome'], 'verified_roster')
            self.assertEqual(self.identity()['hud_outcome'], 'templates_unavailable')
        self.assertEqual(len(server.calls), calls_after_failure)
        w.retry_portraits()
        self.assertEqual(len(server.calls), calls_after_failure)  # Backoff is respected.
        # Advance the owned due time, not the system clock or real network.
        w._portraits_retry_at = time.monotonic() - .01
        w.retry_portraits()
        self.portraits_settled()
        self.assertIsNotNone(w.hero_matcher)
        self.assertEqual(len(w.canonical_champion_map()), 100)
        self.assertEqual(w._portraits_failures, 0)
        self.assertIsNone(w._portraits_retry_at)
        self.run_frame()
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)

    def test_cold_verified_roster_enables_api_while_second_portrait_waits(self):
        w = self.prepare_game()
        server = OwnedPortraitServer(block_suffix='/Owned2.png')
        self.start_portraits_through_load_result(server)
        self.wait_stage(server.entered.is_set, 'second-portrait-gate', PREPARE_SECONDS)
        self.wait_stage(lambda: len(w._verified_roster_map) == 100, 'roster-qt-delivery', DELIVERY_SECONDS)
        self.assertIn('champion.json', server.calls[1])
        self.assertEqual(len(hero_portraits.parse_roster(server.roster, server.version)), 100)
        self.assertFalse((w.state_dir / 'hero-portraits/roster-16.20.1.json').exists())
        self.assertFalse((w.state_dir / 'hero-portraits/manifest.json').exists())
        self.assertIsNone(w.hero_matcher)
        self.assertEqual(len(w.canonical_champion_map()), 100)
        for frame in range(2):
            http = self.run_frame()
            self.assertEqual(http.call_count, 4)
            self.assertEqual(self.identity()['map_outcome'], 'verified_roster')
            self.assertEqual(self.identity()['api_outcome'], 'verified')
            self.assertEqual(self.identity()['hud_outcome'], 'templates_unavailable')
            self.assertEqual(w.state.hero, self.hero if frame else '')
            self.assertIsNone(w.hero_matcher)
            self.assertTrue(w._portraits_busy)
            self.assertFalse(server.release.is_set())
        self.assertEqual(w.hero_continuity.hero, self.hero)
        server.release.set()
        self.portraits_settled()
        self.assertEqual(len(w.canonical_champion_map()), 100)
        self.run_frame()
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)

    def test_warm_cache_is_ready_before_versions_response_and_keeps_same_matcher(self):
        w = self.prepare_game()
        server = OwnedPortraitServer()
        bank, status = hero_portraits.load_portraits(w.state_dir / 'hero-portraits', fetcher=server)
        self.assertEqual(status['state'], 'fresh')
        self.assertEqual(len(bank), 100)
        server.block_suffix = 'versions.json'
        self.start_portraits_through_load_result(server)
        self.wait_stage(server.entered.is_set, 'versions-response-gate', PREPARE_SECONDS)
        self.wait_stage(lambda: w.hero_matcher is not None, 'warm-cache-qt-delivery', DELIVERY_SECONDS)
        cached_matcher = w.hero_matcher
        cached_bank = w._portraits_bank
        cached_revision = w.portrait_bank.revision
        self.assertTrue(w._portraits_busy)
        self.assertEqual(len(w.canonical_champion_map()), 100)
        self.run_frame()
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)
        self.assertNotEqual(self.identity()['hud_outcome'], 'templates_unavailable')
        server.release.set()
        self.portraits_settled()
        self.assertIs(w.hero_matcher, cached_matcher)
        self.assertIs(w._portraits_bank, cached_bank)
        self.assertEqual(w.portrait_bank.revision, cached_revision)
        self.assertFalse(w._portraits_busy)

    def test_memory_only_portraits_and_roster_allow_fresh_api_without_disk_mapping(self):
        w = self.prepare_game()
        server = OwnedPortraitServer()
        with patch.object(hero_portraits, '_write_cache', side_effect=PermissionError('Owned read-only cache')):
            self.start_portraits_through_load_result(server)
            self.portraits_settled()
        self.assertIsNotNone(w.hero_matcher)
        self.assertEqual(len(w.hero_matcher.templates), 100)
        mapping = w.canonical_champion_map()
        self.assertEqual(len(mapping), 100)
        self.assertEqual(mapping['Owned1'], '1')
        mapping['Owned1'] = '999'
        self.assertEqual(w.canonical_champion_map()['Owned1'], '1')
        self.assertFalse((w.state_dir / 'hero-portraits/manifest.json').exists())
        self.run_frame(failure=ConnectionRefusedError('Owned initial API unavailable'))
        self.assertFalse(w.state.hero)
        http = self.run_frame()
        self.assertEqual(http.call_count, 4)
        self.assertFalse(w.state.hero)
        http = self.run_frame()
        self.assertEqual(http.call_count, 4)
        self.assertEqual(w.state.hero, self.hero)
        self.assertEqual(self.identity()['api_outcome'], 'verified')
        self.assertEqual(self.identity()['map_outcome'], 'verified_roster')

    def test_new_game_api_failure_never_carries_previous_identity_then_recovers(self):
        from session_windows import ProcessMetadata
        w = self.prepare_game(warm_map=True)
        second = list(w.data['heroes'])[1]
        w.data['heroes'][second]['championId'] = '2'
        self.run_frame()
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)
        self.meta = ProcessMetadata(self.meta.path, self.meta.created + 1)
        w.automatic_policy.bound.metadata = self.meta
        self.run_frame(failure=ConnectionRefusedError('Owned second game not ready'))
        self.assertFalse(w.state.hero)
        self.assertFalse(w.hero_continuity.hero)
        self.run_frame(slug='Owned2')
        self.assertFalse(w.state.hero)
        self.run_frame(slug='Owned2')
        self.assertEqual(w.state.hero, second)

    def test_malformed_image_field_abstains_from_api_without_aborting_capture_and_ocr(self):
        w = self.prepare_game(warm_map=True)
        cache = w.state_dir / 'hero-portraits'
        path = cache / 'roster-16.20.1.json'
        original = path.read_bytes()
        for invalid_image in (None, []):
            with self.subTest(image=invalid_image):
                payload = json.loads(original)
                payload['data']['1']['image'] = invalid_image
                raw = json.dumps(payload).encode()
                path.write_bytes(raw)
                (cache / 'manifest.json').write_text(json.dumps({
                    'version': '16.20.1', 'rosterSha256': hashlib.sha256(raw).hexdigest()}))
                for _ in range(2):
                    with patch.object(w.capture, 'capture', wraps=w.capture.capture) as capture, \
                            patch.object(w.ocr, 'recognize', wraps=w.ocr.recognize) as ocr:
                        http = self.run_frame()
                    http.assert_not_called()
                    capture.assert_called_once()
                    ocr.assert_called_once()
                    self.assertFalse(w.state.hero)
                    self.assertNotIn('截图或识别初始化失败', w.status.text())
                    self.assertEqual(self.identity()['map_outcome'], 'roster_invalid')
                    self.assertEqual(self.identity()['api_outcome'], 'map_invalid')
        diagnostics.write_roster(cache)
        self.run_frame()
        self.run_frame()
        self.assertEqual(w.state.hero, self.hero)

if __name__ == '__main__':
    unittest.main()
