"""Continuous identity/title refresh in a controlled, already-warm session.

The historical filename does not make this a cold WGC/startup test. Capture,
process identity, foreground and compositor checks are owned doubles, and the
visible-session double is already healthy before the first observed frame.
LocalOCR is warmed on owned pixels before the six measured observations. The
actual four-request live-client parser uses owned HTTP connections and a
hash-verified owned champion roster; no game or network is contacted.

The real Qt schedule_capture/capture_tick/check_target/task_result path must
confirm two independent frames and then keep four refreshes visible without
extending the unchanged four-second capture-time TTL. Both API and genuine OCR
take at least 1.1 seconds per observation. Missing portrait templates must not
serialize those independent jobs.

As in the shared offscreen fixture, replacing window.capture does NOT attach
that double to overlay.capture. Consequently this is not evidence for actual
overlay-triggered session cancellation, initial WGC enrollment, a yellow border,
Windows composition, real gameplay, or absence of real-game flicker.
"""
import json
import ssl
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_animated_augment_rounds as fixture
from tests import test_live_client_identity as transport
from tests import test_native_identity_diagnostics as identity_fixture


MINIMUM_WORK_SECONDS = 1.1
OBSERVATIONS = 6


class MinimumWorkLocalOCR(fixture.ObservedLocalOCR):
    """Delay genuine LocalOCR work if necessary; never synthesize OCR rows."""
    def __init__(self):
        super().__init__()
        self.intervals = []

    def recognize(self, image_bytes, vocabulary):
        started = time.monotonic()
        result = super().recognize(image_bytes, vocabulary)
        remaining = MINIMUM_WORK_SECONDS - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        self.intervals.append((started, time.monotonic(), threading.get_ident()))
        return result


@unittest.skipUnless(fixture.QtWidgets is not None and fixture.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class ColdIdentityContinuousTests(unittest.TestCase):
    # Method aliases, not TestCase inheritance: do not rediscover fixture tests.
    setUpClass = classmethod(fixture.AnimatedAugmentRoundTests.setUpClass.__func__)
    wait = fixture.AnimatedAugmentRoundTests.wait
    record_error = fixture.AnimatedAugmentRoundTests.record_error
    assert_confirmed = fixture.AnimatedAugmentRoundTests.assert_confirmed

    def setUp(self):
        from screen_capture import CapturePaused
        from session_windows import ProcessMetadata
        from synthetic_vision import encoded

        fixture.AnimatedAugmentRoundTests.setUp(self)
        w = self.window
        # Restore a real clock; do not change any product freshness threshold.
        real_clock = patch('native_ui.time', time)
        real_clock.start()
        self.addCleanup(real_clock.stop)
        w.ocr_reuse.clock = time.monotonic
        self.metadata = ProcessMetadata(r'C:\Owned Fixture\League of Legends.exe', 123456)
        process = patch('session_windows.process_metadata', return_value=self.metadata)
        process.start()
        self.addCleanup(process.stop)
        w.capture_metadata = lambda: self.metadata
        w.automatic_policy = SimpleNamespace(
            bound=SimpleNamespace(role='game', metadata=self.metadata), stop=lambda: None)
        w.hero_matcher = None
        w.data['heroes'][fixture.HERO]['championId'] = '1'
        identity_fixture.write_roster(w.state_dir / 'hero-portraits')
        self.assertEqual(w.canonical_champion_map()['Owned1'], '1')
        self.assertEqual(len(w.canonical_champion_map()), 100)
        self.assertTrue(w.live_identity_toggle.isChecked())

        w.ocr = MinimumWorkLocalOCR()
        # Warm model initialization without creating a state/display observation.
        w.ocr.recognize(encoded(self.scene.image().crop(fixture.ROI_BOX)),
                        tuple(w.data['augments']))
        w.ocr.records.clear()
        w.ocr.intervals.clear()
        self.assertFalse(w.state.confirmed)
        self.assertEqual(self.results, [])
        self.assertEqual(w.last_observation, 0.)

        self.capture_calls = []
        self.active_captures = 0
        self.maximum_active_captures = 0
        self.compositor_checks = []
        capture = w.capture
        self.assertIsNone(w.overlay.capture)  # Explicit offscreen-fixture limit.
        capture.can_request_visible_overlay = True
        capture.visible_capture_status = 'eligible'
        capture.has_live_visible_session = True
        capture.session_epoch = 1
        capture.last_capture_diagnostic = {}
        capture.prepare_capture_mode = lambda visible: True
        capture_lock = threading.Lock()

        def retire():
            capture.has_live_visible_session = False
            capture.session_epoch += 1

        def validate(target, rect, *, allow_visible_overlay=False):
            self.assertEqual(target.identity, w.target.identity)
            self.assertEqual(rect, self.rect)
            self.assertTrue(capture.foreground(target))
            self.compositor_checks.append((target.identity, rect, allow_visible_overlay))

        def acquire(target, roi, *, cancelled, expected_metadata, **options):
            self.assertEqual(target.identity, w.target.identity)
            self.assertEqual(expected_metadata, self.metadata)
            self.assertEqual(roi, (0., 0., 1., 1.))
            self.assertTrue(options.get('allow_visible_overlay'))
            self.assertTrue(capture.has_live_visible_session)
            is_cancelled = cancelled if callable(cancelled) else cancelled.is_set
            with capture_lock:
                self.active_captures += 1
                self.maximum_active_captures = max(self.maximum_active_captures,
                                                   self.active_captures)
            try:
                started = time.monotonic()
                while time.monotonic() - started < .035:
                    if is_cancelled():
                        raise CapturePaused('Owned cancelled acquisition')
                    time.sleep(.002)
                # Each acquisition animates owned pixels inside the OCR crop;
                # titles and HUD stay unchanged, but exact ROI reuse cannot pass.
                payload = encoded(self.scene.image(phase=len(self.capture_calls)))
                self.capture_calls.append((started, time.monotonic(), threading.get_ident()))
                return payload, self.rect
            finally:
                with capture_lock:
                    self.active_captures -= 1

        capture.retire_session = retire
        capture.validate_compositor = validate
        capture.capture = acquire
        self.receipts = []
        self.hidden = []
        self.connections = []
        self.trace = {}
        real_hide = w.overlay.hide

        def observed_hide(reason='unknown'):
            if len(self.results) >= 2 and w.overlay.isVisible():
                self.hidden.append({'reason': reason,
                    'age_s': round(time.monotonic() - w.last_observation, 4)})
            return real_hide(reason)

        w.overlay.hide = observed_hide

        class OwnedConnection(transport.Connection):
            def __init__(inner, index, context):
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)
                inner.started = time.monotonic()
                inner.thread = threading.get_ident()
                inner.index = index
                payload = (transport.NAME if index % 2 == 0
                           else [transport.row('Owned1')])
                super().__init__(transport.Response(json.dumps(payload).encode()))

            def getresponse(inner):
                time.sleep(MINIMUM_WORK_SECONDS / 4)
                return super().getresponse()

            def close(inner):
                super().close()
                inner.completed = time.monotonic()

        def connection_factory(host, port, *, timeout, context):
            self.assertEqual((host, port), ('127.0.0.1', 2999))
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, .45)
            connection = OwnedConnection(len(self.connections), context)
            self.connections.append(connection)
            return connection

        http = patch('live_client_identity.http.client.HTTPSConnection',
                     side_effect=connection_factory)
        http.start()
        self.addCleanup(http.stop)
        # Drain while process/transport/clock patches still exist (LIFO).
        self.addCleanup(self.dispose_window)

    def record_result(self, kind, value, generation):
        if kind != 'ocr':
            return
        self.results.append(value)
        w = self.window
        self.receipts.append({'confirmed': w.state.confirmed,
            'visible': w.overlay.isVisible(), 'hero': w.state.hero,
            'age_s': round(time.monotonic() - value['_capturedAt'], 4),
            'timings': dict(value['_timings'])})
        if len(self.results) == OBSERVATIONS:
            # Product task_result has already scheduled its next timer. Stop at
            # the observation boundary, without issuing a seventh recognition.
            w.monitor.stop()
            w.watchdog.stop()

    def dispose_window(self):
        w = self.window
        if w is None:
            return
        threads = (w.frame_inference_worker._thread, w.latest_capture._thread)
        fixture.AnimatedAugmentRoundTests.dispose_window(self)
        self.wait(lambda: all(job is None or not job.is_alive() for job in threads))

    def test_warm_visible_session_refreshes_without_serial_identity_ocr_expiry(self):
        w = self.window
        # The shared fixture disables scheduling; remove ONLY that test override.
        # Everything after this point runs on the autonomous production timers.
        del w.schedule_capture
        w.watchdog.start()
        w.schedule_capture(0)
        self.wait(lambda: self.errors or len(self.results) >= OBSERVATIONS, seconds=35)
        w.monitor.stop()
        w.watchdog.stop()
        self.wait(lambda: not w._workers and not w.ocr_busy and not w.capture_pending
                  and not w.latest_capture.busy and not w.frame_inference_worker._busy)

        api_intervals = [(self.connections[i].started,
                          self.connections[i + 3].completed)
                         for i in range(0, len(self.connections) - 3, 4)]
        ocr_intervals = w.ocr.intervals
        overlaps = [api_start < ocr_end and ocr_start < api_end
                    for (api_start, api_end), (ocr_start, ocr_end, _) in
                    zip(api_intervals, ocr_intervals)]
        self.trace = {'scope': 'controlled warmed visible-session double; not cold WGC or game',
            'receipts': self.receipts, 'visible_to_hidden': self.hidden,
            'api_work_s': [round(end - start, 4) for start, end in api_intervals],
            'ocr_work_s': [round(end - start, 4) for start, end, _ in ocr_intervals],
            'same_frame_overlap': overlaps, 'http_requests': len(self.connections),
            'captures': len(self.capture_calls), 'maximum_active_captures': self.maximum_active_captures,
            'workers_drained': not w._workers and not w.frame_inference_worker._busy
                               and not w.latest_capture.busy,
            'errors': self.errors}
        detail = json.dumps(self.trace, ensure_ascii=False, sort_keys=True)
        self.assertEqual(self.errors, [], detail)
        self.assertEqual(len(self.results), OBSERVATIONS, detail)
        self.assertFalse(self.receipts[0]['confirmed'], detail)
        self.assertTrue(all(row['confirmed'] and row['visible']
                            for row in self.receipts[1:]), detail)
        self.assertEqual(self.hidden, [], detail)
        self.assert_confirmed((0, 1, 2))
        self.assertIsNone(w.hero_matcher)
        self.assertEqual(len(self.connections), OBSERVATIONS * 4, detail)
        self.assertEqual(len(ocr_intervals), OBSERVATIONS, detail)
        self.assertEqual(overlaps, [True] * OBSERVATIONS, detail)
        self.assertEqual(w.ocr_reuse.hits, 0)
        self.assertEqual(len({row['digest'] for row in w.ocr.records}), OBSERVATIONS)
        self.assertEqual(self.maximum_active_captures, 1)
        self.assertTrue(all(thread != self.main_thread
                            for _, _, thread in self.capture_calls))
        self.assertTrue(all(end - start >= MINIMUM_WORK_SECONDS
                            for start, end in api_intervals))
        self.assertTrue(all(end - start >= MINIMUM_WORK_SECONDS
                            for start, end, _ in ocr_intervals))
        self.assertTrue(all(row.thread != self.main_thread for row in self.connections))
        self.assertTrue(all(thread != self.main_thread for _, _, thread in ocr_intervals))
        for index, connection in enumerate(self.connections):
            path = ('/liveclientdata/activeplayername' if index % 2 == 0
                    else '/liveclientdata/playerlist')
            self.assertEqual(connection.calls, [(('GET', path),
                                               {'headers': {'Accept': 'application/json'}})])
            self.assertTrue(connection.closed)
            self.assertNotEqual(connection.thread, ocr_intervals[index // 4][2])
        for result in self.results:
            hero = result['hero_observation']
            self.assertEqual((hero['hero'], hero['championId'], hero['method'], hero['confident']),
                             (fixture.HERO, '1', 'game-client-api', True))
            self.assertFalse(result['ocr_reused'])
            self.assertLessEqual(result['_completedAt'] - result['_capturedAt'], 4.)
            self.assertEqual(tuple(card['name'] for card in result['automatic_candidates']),
                             fixture.NAMES[:3])
        self.assertEqual(len({result['_captureSerial'] for result in self.results}), OBSERVATIONS)
        self.assertEqual(len({result['_capturedAt'] for result in self.results}), OBSERVATIONS)
        self.assertTrue(self.trace['workers_drained'])


if __name__ == '__main__':
    unittest.main()
