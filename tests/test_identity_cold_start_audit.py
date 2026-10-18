"""Startup identity regressions with owned pixels, roster, and HTTP responses.

Production load/result, portrait loading, frame recognition, API parsing, and
identity state run unchanged. No network, client installation, or real game
screenshots are needed. This is not Windows capture evidence.

Baseline audit reproduced: one cold asset failure stayed unavailable forever,
warm verified portraits waited behind a remote versions request, and malformed
image records aborted capture before HUD/OCR. Their tests now require recovery.
Memory-only complete banks also provide a verified map without disk persistence.
The conservative boundary remains: a map arrives only after the whole bank is
verified, so an incomplete download never supplies identity evidence.
"""
import copy
import hashlib
import io
import json
import ssl
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hero_portraits
from tests import test_native_capture_worker as fixtures
from tests import test_native_identity_diagnostics as diagnostics


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
            if not self.release.wait(10):
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
    dispose_window = fixtures.NativeCaptureWorkerTests.dispose_window
    events = diagnostics.NativeIdentityDiagnosticTests.events
    identity = diagnostics.NativeIdentityDiagnosticTests.identity

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
        network = patch.object(hero_portraits, 'fetch_bytes', side_effect=server)
        network.start()
        self.addCleanup(network.stop)
        updates = patch('updates.check_for_update', return_value={'state': 'owned', 'message': 'Owned'})
        updates.start()
        self.addCleanup(updates.stop)
        self._release_events.append(server.release)
        data = copy.deepcopy(w.data)
        data['metadata']['isDemo'] = False
        w.enable_updates = True
        w.task_result('load', {'data': data}, w.state.generation)
        self.app.processEvents()

    def portraits_settled(self):
        self.wait(lambda: not any(job.name == 'vga-portraits' for job in self.window._workers))
        # A worker can retire immediately after queueing its Qt result.
        self.app.processEvents()

    def run_frame(self, *, failure=None, slug='Owned1'):
        w = self.window
        with patch('session_windows.process_metadata', return_value=self.meta), \
                patch('live_client_identity.ssl.create_default_context', return_value=ssl.create_default_context()), \
                patch('live_client_identity.http.client.HTTPSConnection',
                      side_effect=failure if failure is not None else diagnostics.connections(slug)) as http:
            w.capture_hidden(w.state.generation)
            self.wait(lambda: not w.ocr_busy and not any(job.name == 'vga-ocr' for job in w._workers))
        return http

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

    def test_cold_single_asset_failure_retries_when_due_and_restores_both_sources(self):
        w = self.prepare_game()
        server = OwnedPortraitServer(fail_once='/Owned100.png')
        self.start_portraits_through_load_result(server)
        self.portraits_settled()
        self.assertIsNone(w.hero_matcher)
        self.assertFalse((w.state_dir / 'hero-portraits/manifest.json').exists())
        self.assertEqual(w.canonical_champion_map(), {})
        self.assertIsNone(server.fail_once)  # All later server responses are healthy.
        self.assertFalse(w._portraits_busy)
        self.assertEqual(w._portraits_failures, 1)
        self.assertGreater(w._portraits_retry_at, time.monotonic() + 28)
        self.assertLess(w._portraits_retry_at, time.monotonic() + 31)
        calls_after_failure = len(server.calls)
        for _ in range(3):
            http = self.run_frame()
            http.assert_not_called()  # Healthy API is never tried without the map.
            self.assertFalse(w.state.hero)
            self.assertEqual(self.identity()['api_outcome'], 'map_invalid')
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

    def test_current_boundary_cold_map_waits_for_complete_portrait_bank(self):
        w = self.prepare_game()
        server = OwnedPortraitServer(block_suffix='/Owned100.png')
        self.start_portraits_through_load_result(server)
        self.wait(server.entered.is_set)
        self.assertIn('champion.json', server.calls[1])
        self.assertEqual(len(hero_portraits.parse_roster(server.roster, server.version)), 100)
        self.assertFalse((w.state_dir / 'hero-portraits/roster-16.20.1.json').exists())
        self.assertEqual(w.canonical_champion_map(), {})
        http = self.run_frame()
        http.assert_not_called()
        self.assertEqual(self.identity()['api_outcome'], 'map_invalid')
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
        self.wait(server.entered.is_set)
        self.wait(lambda: w.hero_matcher is not None)
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

    def test_memory_only_complete_portraits_allow_fresh_api_without_disk_mapping(self):
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
        self.assertEqual(self.identity()['map_outcome'], 'verified_memory')

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
