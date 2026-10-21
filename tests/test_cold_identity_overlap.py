"""Owned cold-template API/OCR overlap through the real Qt capture pipeline.

Reconstructed after the original local candidate was lost. Capture pixels,
HTTP transport and OCR are controlled doubles; recognize_frame, the four-read
identity parser, cancellation, reconciliation and Qt delivery are production
code. These event-order tests are not Windows capture or actual-game evidence.
"""
import io
import ssl
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_native_capture_worker as fixture
from tests import test_native_identity_diagnostics as diagnostics


@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime is not installed')
class ColdIdentityOverlapTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    wait = fixture.NativeCaptureWorkerTests.wait
    events = diagnostics.NativeIdentityDiagnosticTests.events
    identity = diagnostics.NativeIdentityDiagnosticTests.identity

    def setUp(self):
        from PIL import Image
        from screen_capture import ClientRect
        from session_windows import ProcessMetadata
        fixture.NativeCaptureWorkerTests.setUp(self)
        w = self.window
        self.meta = ProcessMetadata('C:/OWNED/League of Legends.exe', 12345)
        self.current_meta = self.meta
        self.hero = next(iter(w.data['heroes']))
        w.data['heroes'][self.hero]['championId'] = '1'
        w.automatic_policy = SimpleNamespace(
            bound=SimpleNamespace(role='game', metadata=self.meta), stop=lambda: None)
        w.capture_metadata = lambda: self.meta
        w.hero_matcher = None
        diagnostics.write_roster(w.state_dir / 'hero-portraits')
        raw = io.BytesIO()
        Image.new('RGB', (1280, 720), (82, 92, 108)).save(raw, 'PNG')
        self.capture_calls = 0
        self.results = []
        self.errors = []
        self.ocr_threads = []
        self.active_ocr = 0
        self.max_active_ocr = 0
        self.lock = threading.Lock()
        owner = self

        class Capture:
            last_backend = 'window-dc'

            def capture(inner, *args, **kwargs):
                owner.capture_calls += 1
                return raw.getvalue(), ClientRect(0, 0, 1280, 720)

        class OCR:
            _engine = object()

            def recognize(inner, payload, vocabulary):
                with owner.lock:
                    owner.active_ocr += 1
                    owner.max_active_ocr = max(owner.max_active_ocr, owner.active_ocr)
                owner.ocr_threads.append(threading.get_ident())
                owner.ocr_entered.set()
                try:
                    if not owner.ocr_release.wait(8):
                        raise RuntimeError('Owned OCR gate was not released')
                    if owner.ocr_error:
                        raise RuntimeError('Owned OCR failure')
                    with Image.open(io.BytesIO(payload)) as image:
                        return {'ocr_lines': [], 'candidates': [],
                                'image_size': {'width': image.width, 'height': image.height}}
                finally:
                    with owner.lock:
                        owner.active_ocr -= 1

        w.capture = Capture()
        w.ocr = OCR()
        w.signals.result.connect(self.record_result)
        w.signals.error.connect(self.record_error)
        scope = patch('session_windows.process_metadata', side_effect=lambda pid: self.current_meta)
        scope.start()
        self.addCleanup(scope.stop)
        tls = patch('live_client_identity.ssl.create_default_context',
                    return_value=ssl.create_default_context())
        tls.start()
        self.addCleanup(tls.stop)
        transport = patch('live_client_identity.http.client.HTTPSConnection',
                          side_effect=self.connection)
        self.http = transport.start()
        self.addCleanup(transport.stop)
        # Drain before removing process/transport doubles, even on assertion failure.
        self.addCleanup(self.dispose_window)

    def dispose_window(self):
        w = self.window
        if w is None:
            return
        inference = w.frame_inference_worker
        fixture.NativeCaptureWorkerTests.dispose_window(self)
        thread = inference._thread
        if thread is not None:
            self.wait(lambda: not thread.is_alive())
        self.assertEqual(self.active_ocr, 0)

    def record_result(self, kind, value, generation):
        if kind == 'ocr':
            self.results.append(value)

    def record_error(self, kind, error, generation):
        if kind == 'ocr':
            self.errors.append(error)

    def connection(self, *args, **kwargs):
        self.assertEqual(args, ('127.0.0.1', 2999))
        self.assertEqual(kwargs['context'].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(kwargs['context'].check_hostname)
        item = self.connections[len(self.created)]
        self.created.append(item)
        original = item.getresponse
        first = len(self.created) == 1

        def response():
            if first:
                self.api_entered.set()
                if not self.api_release.wait(8):
                    raise RuntimeError('Owned API gate was not released')
                if self.api_error:
                    raise ConnectionRefusedError('Owned API unavailable')
            return original()

        item.getresponse = response
        return item

    def start_frame(self, *, hold_api=False, hold_ocr=False, api_error=False, ocr_error=False):
        self.api_entered, self.api_release = threading.Event(), threading.Event()
        self.ocr_entered, self.ocr_release = threading.Event(), threading.Event()
        self._release_events.extend((self.api_release, self.ocr_release))
        if not hold_api:
            self.api_release.set()
        if not hold_ocr:
            self.ocr_release.set()
        self.api_error, self.ocr_error = api_error, ocr_error
        self.connections, self.created = diagnostics.connections(), []
        self.window.capture_hidden(self.window.state.generation)

    def finish_frame(self):
        self.api_release.set()
        self.ocr_release.set()
        self.wait(lambda: not self.window.ocr_busy and not self.window._workers)
        self.assertEqual(self.active_ocr, 0)
        self.assertEqual(self.max_active_ocr, 1)
        self.assertTrue(all(item.closed for item in self.created))

    def require_overlap(self):
        self.wait(self.api_entered.is_set)
        # API is still held inside its first actual transport response. The
        # serial baseline cannot enter OCR until this independent gate opens.
        self.wait(self.ocr_entered.is_set, seconds=1)
        self.assertFalse(self.api_release.is_set())
        self.assertEqual(self.results, [])

    def test_missing_matcher_overlaps_api_and_two_fresh_frames_reuse_one_worker(self):
        w = self.window
        self.start_frame(hold_api=True, hold_ocr=True)
        self.require_overlap()
        self.finish_frame()
        first = self.results[-1]
        self.assertTrue(first['hero_observation']['confident'])
        self.assertEqual(first['hero_observation']['hero'], self.hero)
        self.assertFalse(w.state.hero)  # One observation cannot confirm identity.
        self.assertEqual(len(self.created), 4)
        self.assertEqual([c.calls[0][0] for c in self.created],
                         [('GET', '/liveclientdata/activeplayername'),
                          ('GET', '/liveclientdata/playerlist')] * 2)
        self.start_frame()
        self.finish_frame()
        self.assertEqual(w.state.hero, self.hero)
        self.assertEqual(self.capture_calls, 2)
        self.assertEqual(self.http.call_count, 8)
        self.assertLess(first['_captureSerial'], self.results[-1]['_captureSerial'])
        self.assertEqual(len(set(self.ocr_threads)), 1)
        self.assertNotEqual(self.ocr_threads[0], self.main_thread)
        self.assertEqual(self.errors, [])
        self.assertFalse(w.state.confirmed)  # Blank owned image has no card proof.

    def test_api_unavailable_abstains_and_drains_pending_titles(self):
        self.start_frame(hold_ocr=True, api_error=True)
        self.wait(self.ocr_entered.is_set)
        self.wait(self.api_entered.is_set)
        self.assertTrue(self.window.ocr_busy)
        self.assertEqual(self.results, [])
        self.finish_frame()
        self.assertFalse(self.results[-1]['hero_observation']['confident'])
        self.assertFalse(self.window.state.hero)
        self.assertEqual(self.identity()['api_outcome'], 'connection_failed')
        self.assertFalse(self.window.overlay.isVisible())

    def test_alternate_matcher_conflict_still_abstains(self):
        self.window.hero_matcher = SimpleNamespace(recognize=lambda payload: {
            'hero': 'Owned conflicting hero', 'championId': '2',
            'confident': True, 'method': 'own-hud-portrait', 'hudOutcome': 'recognized'})
        self.start_frame(hold_api=True, hold_ocr=True)
        self.require_overlap()
        self.finish_frame()
        self.assertEqual(self.identity()['identity_outcome'], 'api_hud_conflict')
        self.assertFalse(self.results[-1]['hero_observation']['confident'])
        self.assertFalse(self.window.state.hero)
        self.assertFalse(self.window.overlay.isVisible())

    def test_stop_while_api_and_ocr_pending_discards_late_result_and_drains(self):
        self.start_frame(hold_api=True, hold_ocr=True)
        self.require_overlap()
        old_generation = self.window.state.generation
        self.window.stop_monitor()
        self.assertGreater(self.window.state.generation, old_generation)
        self.finish_frame()
        self.assertFalse(self.window.state.running)
        self.assertFalse(self.window.state.hero)
        self.assertFalse(self.window.state.confirmed)
        self.assertFalse(self.window.overlay.isVisible())

    def test_process_scope_change_during_reads_rejects_identity(self):
        from session_windows import ProcessMetadata
        self.start_frame(hold_api=True, hold_ocr=True)
        self.require_overlap()
        self.current_meta = ProcessMetadata(self.meta.path, self.meta.created + 1)
        self.finish_frame()
        self.assertEqual(self.identity()['api_outcome'], 'scope_changed')
        self.assertFalse(self.results[-1]['hero_observation']['confident'])
        self.assertFalse(self.window.state.hero)
        self.assertFalse(self.window.overlay.isVisible())

    def test_identity_deadline_is_unchanged_and_late_api_cannot_authorize(self):
        from live_client_identity import BATCH_TIMEOUT
        self.start_frame(hold_api=True, hold_ocr=True)
        self.require_overlap()
        # The deadline began before the held first HTTP response, so waiting
        # a full budget from here cannot accidentally release it too early.
        began_waiting = time.monotonic()
        self.wait(lambda: time.monotonic() - began_waiting > BATCH_TIMEOUT + .05,
                  seconds=BATCH_TIMEOUT + 1)
        self.finish_frame()
        self.assertEqual(self.identity()['api_outcome'], 'timeout')
        self.assertFalse(self.results[-1]['hero_observation']['confident'])
        self.assertFalse(self.window.state.hero)
        self.assertFalse(self.window.state.confirmed)
        self.assertFalse(self.window.overlay.isVisible())

    def test_ocr_exception_is_joined_and_same_worker_accepts_next_frame(self):
        self.start_frame(hold_api=True, ocr_error=True)
        self.require_overlap()
        self.finish_frame()
        self.assertEqual(self.results, [])
        self.assertEqual(self.errors, ['Owned OCR failure'])
        self.assertFalse(self.window.state.confirmed)
        self.assertFalse(self.window.overlay.isVisible())
        self.start_frame()
        self.finish_frame()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(self.results[-1]['hero_observation']['confident'])
        self.assertEqual(len(set(self.ocr_threads)), 1)


if __name__ == '__main__':
    unittest.main()
