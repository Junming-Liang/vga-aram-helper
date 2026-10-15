"""Portable supplemental-only capture tracing and owned-fixture lifecycle tests."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import probe_capture_phases as phases
from scripts import probe_opencv_parity as probe
from screen_capture import ClientRect
from PIL import Image
import wgc_capture


class FakeCapture:
    def __init__(self, image=None):
        self.image = image or Image.new('RGB', (96, 64), 'red')
        self._wgc = None
        self.last_backend = 'window-dc'
        self.cleanup_pending = False
        self.calls = 0
        self.closed = False
        self.rect = ClientRect(20, 20, 96, 64)
    def capture(self, target, *, cancelled=None):
        self.calls += 1
        if cancelled and cancelled():
            raise wgc_capture.WgcError('cancelled', 'private text must not be emitted')
        out = io.BytesIO()
        self.image.save(out, format='PNG')
        return out.getvalue(), self.rect
    def info(self, hwnd):
        return SimpleNamespace(pid=os.getpid())
    def validate(self, target):
        return self.rect
    def close(self):
        self.closed = True


class CapturePhaseTests(unittest.TestCase):
    def test_supplemental_fixed_order_rows_exact_output_and_nested_phases(self):
        capture = FakeCapture()
        expected = phases.output_identity(capture.capture(None))
        caller = threading.get_ident()
        pumping = []
        gate = threading.Event()
        original_capture = capture.capture
        def gated_capture(*a, **kw):
            if threading.get_ident() != caller:
                gate.clear()
                self.assertTrue(gate.wait(1))
            return original_capture(*a, **kw)
        capture.capture = gated_capture
        def pump():
            self.assertEqual(threading.get_ident(), caller)
            pumping.append(True)
            gate.set()
        result = phases.run_supplemental(capture, None, expected, pump)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(capture.calls, 7)
        self.assertEqual([(r['context'], r['index']) for r in result['rows']],
                         [(c, i) for c in phases.CONTEXTS for i in range(3)])
        for row in result['rows']:
            self.assertEqual(row['output'], expected)
            self.assertEqual(row['phase_calls'], {'wgc_inclusive': 0, 'helper_verify': 0, 'frame_decode': 0, 'png_encode': 1})
            self.assertAlmostEqual(row['outer_residual_seconds'], row['total_seconds']-row['phase_seconds']['png_encode'])
            self.assertEqual(row['capture_on_caller_thread'], row['context'] == 'gui_blocked')
            self.assertTrue(row['worker_exited'])
        self.assertTrue(result['safe_to_close_fixture'])

    def test_worker_completion_without_observed_pump_fails_and_stops(self):
        capture = FakeCapture()
        expected = phases.output_identity(capture.capture(None))
        capture.calls = 0
        def immediate(operation, *, context, pump, cancelled):
            return {'value': operation(), 'error': None, 'worker_exited': True,
                    'cancelled': False, 'qt_pumps': 0, 'capture_on_caller_thread': context == 'gui_blocked'}
        result = phases.run_supplemental(capture, None, expected, lambda: None, invoke_call=immediate)
        self.assertEqual(capture.calls, 4)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual([row['status'] for row in result['rows']], ['passed'] * 3 + ['failed', 'not-run', 'not-run'])
        self.assertEqual(result['rows'][3]['qt_pumps'], 0)

    def test_wrappers_are_restored_after_success_and_exception(self):
        capture = FakeCapture()
        backend = SimpleNamespace(capture=lambda *a, **k: 'frame', _verify_helper=lambda: None)
        capture._wgc = backend
        original = (backend.capture, backend._verify_helper, wgc_capture.decode_frame,
                    Image.Image.save, wgc_capture.subprocess.Popen, wgc_capture._CaptureJob)
        for fail in (False, True):
            try:
                with phases.PhaseTrace(capture) as trace:
                    backend._verify_helper()
                    capture.capture(None)
                    if fail:
                        raise RuntimeError('test')
            except RuntimeError:
                pass
            self.assertEqual(original, (backend.capture, backend._verify_helper, wgc_capture.decode_frame,
                Image.Image.save, wgc_capture.subprocess.Popen, wgc_capture._CaptureJob))
            self.assertEqual(trace.calls['helper_verify'], 1)
            self.assertEqual(trace.calls['png_encode'], 1)

    def test_nested_helper_spans_are_explicit_not_added_to_parent(self):
        capture = FakeCapture()
        backend = SimpleNamespace(_verify_helper=lambda: time.sleep(.001))
        def helper_capture(*a, **k):
            backend._verify_helper()
            return wgc_capture.decode_frame(b'', (0, 0, 96, 64))
        backend.capture = helper_capture
        capture._wgc = backend
        with patch.object(wgc_capture, 'decode_frame', lambda *a: time.sleep(.001)):
            with phases.PhaseTrace(capture) as trace:
                backend.capture()
        row = trace.result()
        self.assertEqual(row['phase_calls']['wgc_inclusive'], 1)
        self.assertEqual(row['phase_calls']['helper_verify'], 1)
        self.assertEqual(row['phase_calls']['frame_decode'], 1)
        self.assertGreater(row['phase_seconds']['wgc_inclusive'],
                           row['phase_seconds']['helper_verify'] + row['phase_seconds']['frame_decode'])

    def test_error_stops_later_calls_preserves_row_and_sanitizes_message(self):
        capture = FakeCapture()
        expected = phases.output_identity(capture.capture(None))
        capture.capture = Mock(side_effect=wgc_capture.WgcError('protected', 'private path or identity'))
        original = Image.Image.save
        result = phases.run_supplemental(capture, None, expected, lambda: None)
        self.assertEqual(result['status'], 'failed')
        capture.capture.assert_called_once()
        self.assertEqual([r['status'] for r in result['rows']], ['failed'] + ['not-run'] * 5)
        self.assertEqual(result['rows'][0]['error'], {'type': 'WgcError', 'status': 'protected'})
        self.assertNotIn('private', json.dumps(result))
        self.assertIs(Image.Image.save, original)

    def test_output_mismatch_stops_without_retry_or_fast_selection(self):
        capture = FakeCapture()
        expected = {'image_sha256': '0' * 64, 'width': 96, 'height': 64}
        result = phases.run_supplemental(capture, None, expected, lambda: None)
        self.assertEqual(capture.calls, 1)
        self.assertEqual(result['rows'][0]['status'], 'failed')
        self.assertNotEqual(result['rows'][0]['output'], expected)
        self.assertTrue(all(r['status'] == 'not-run' for r in result['rows'][1:]))

    def test_worker_timeout_cancels_and_unknown_cleanup_prevents_next_call(self):
        release = threading.Event()
        cancelled = threading.Event()
        thread_ids = []
        caller = threading.get_ident()
        def stuck():
            thread_ids.append(threading.current_thread())
            release.wait(1)
            return 'late'
        try:
            run = phases.invoke(stuck, context='worker_qt_pumped', pump=lambda: self.assertEqual(threading.get_ident(), caller),
                                cancelled=cancelled, timeout=.01, grace=.01)
            self.assertTrue(cancelled.is_set())
            self.assertFalse(run['worker_exited'])
            self.assertTrue(thread_ids[0].daemon)
            self.assertFalse(run['capture_on_caller_thread'])
            capture = FakeCapture()
            expected = phases.output_identity(capture.capture(None))
            invoke = Mock(return_value=run)
            result = phases.run_supplemental(capture, None, expected, lambda: None, invoke_call=invoke)
            invoke.assert_called_once()
            self.assertFalse(result['safe_to_close_fixture'])
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(all(r['status'] == 'not-run' for r in result['rows'][1:]))
        finally:
            release.set()
            for worker in thread_ids:
                worker.join(1)

    def test_unknown_cleanup_is_not_false_and_fallback_reason_is_unrecorded(self):
        capture = SimpleNamespace(last_backend='window-dc', _wgc=None)
        row = phases.observation(capture)
        self.assertIsNone(row['cleanup_pending'])
        self.assertEqual(row['fallback_reason'], 'unrecorded')
        self.assertIsNone(row['one_shot_helper_sha256'])

    def test_unknown_cleanup_fails_first_row_and_stops_later_attempts(self):
        capture = FakeCapture()
        expected = phases.output_identity(capture.capture(None))
        del capture.cleanup_pending
        capture.calls = 0
        result = phases.run_supplemental(capture, None, expected, lambda: None)
        self.assertEqual(capture.calls, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['rows'][0]['cleanup_pending'])
        self.assertFalse(result['safe_to_close_fixture'])
        self.assertTrue(all(row['status'] == 'not-run' for row in result['rows'][1:]))

    def test_identity_snapshot_binds_loaded_bytes_actual_helper_and_verified_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in phases.SOURCE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('source:' + name, encoding='utf-8')
            native = root / 'cv2.pyd'
            native.write_bytes(b'loaded cv native')
            helper_root = root / 'build' / 'native'
            helper_root.mkdir(parents=True)
            modules = {name: SimpleNamespace(__file__=str(root / (name + '.py')))
                       for name in ('screen_capture', 'wgc_capture', 'wgc_session_capture',
                                    'persistent_capture_adapter', 'session_windows')}
            builders = []
            for kind, filename, manifest, protocol, source, recipe in (
                ('one_shot', 'vga-wgc-capture.exe', 'wgc-capture-build.json', 1, 'native/wgc_capture.cpp', 'scripts/build_wgc_capture.py'),
                ('session', 'vga-wgc-session-capture.exe', 'wgc-session-capture-build.json', 2, 'native/wgc_session_capture.cpp', 'scripts/build_wgc_session_capture.py')):
                (helper_root / filename).write_bytes(b'helper:' + kind.encode())
                (helper_root / manifest).write_bytes(b'proof:' + kind.encode())
                proof = {'protocol': protocol, 'source_commit': '1' * 40,
                         'source_sha256': phases.file_record(root / source)['sha256'],
                         'build_recipe_sha256': phases.file_record(root / recipe)['sha256']}
                builder = SimpleNamespace(FILENAME=filename, MANIFEST=manifest, verify_built_helper=Mock(return_value=proof))
                modules[recipe[:-3].replace('/', '.')] = builder
                builders.append(builder)
            helper = SimpleNamespace(helper_path=helper_root / 'vga-wgc-capture.exe',
                                     _digest=phases.file_record(helper_root / 'vga-wgc-capture.exe')['sha256'])
            with patch.dict(sys.modules, {'cv2': SimpleNamespace(_native=SimpleNamespace(__file__=str(native)))}), \
                    patch.object(phases.importlib, 'import_module', side_effect=modules.__getitem__):
                identity = phases.identity_snapshot(root, helper)
                self.assertEqual(identity['loaded']['cv2_native'], phases.file_record(native))
                self.assertEqual(identity['sources']['scripts/probe_capture_phases.py'], phases.file_record(root / 'scripts/probe_capture_phases.py'))
                self.assertEqual(identity['helpers']['one_shot']['binary']['sha256'], helper._digest)
                self.assertTrue(identity['bound_one_shot'])
                for builder in builders:
                    builder.verify_built_helper.assert_called_once_with(helper_root, root=root)
                helper._digest = '0' * 64
                with self.assertRaisesRegex(RuntimeError, 'Bound capture helper'):
                    phases.identity_snapshot(root, helper)
                helper._digest = identity['helpers']['one_shot']['binary']['sha256']
                helper.helper_path = root / 'different.exe'
                with self.assertRaisesRegex(RuntimeError, 'Bound capture helper'):
                    phases.identity_snapshot(root, helper)
                helper.helper_path = helper_root / 'vga-wgc-capture.exe'
                builders[1].verify_built_helper.side_effect = RuntimeError('source changed')
                with self.assertRaisesRegex(RuntimeError, 'source changed'):
                    phases.identity_snapshot(root, helper)
                builders[1].verify_built_helper.side_effect = None
                modules['screen_capture'].__file__ = str(root / 'different.py')
                with self.assertRaisesRegex(RuntimeError, 'outside the bound checkout'):
                    phases.identity_snapshot(root, helper)

    def fake_qt(self):
        app = SimpleNamespace(platformName=lambda: 'windows', processEvents=Mock(),
            primaryScreen=lambda: SimpleNamespace(devicePixelRatio=lambda: 1.0,
                availableGeometry=lambda: SimpleNamespace(x=lambda: 0, y=lambda: 0, contains=lambda r: True)))
        window = Mock()
        window.winId.return_value = 42
        window.frameGeometry.return_value = 'inside'
        class QWidget:
            def __new__(cls):
                return window
        QApplication = SimpleNamespace(instance=lambda: app)
        modules = {'PySide6': SimpleNamespace(),
            'PySide6.QtCore': SimpleNamespace(Qt=SimpleNamespace(WindowType=SimpleNamespace(WindowStaysOnTopHint=1, FramelessWindowHint=2))),
            'PySide6.QtGui': SimpleNamespace(QColor=Mock(), QPainter=Mock()),
            'PySide6.QtWidgets': SimpleNamespace(QApplication=QApplication, QWidget=QWidget)}
        return app, window, modules

    def test_authoritative_calls_unwrapped_and_samples_retained_on_diagnostic_failure(self):
        app, window, modules = self.fake_qt()
        capture = FakeCapture()
        original_save = Image.Image.save
        original_capture = capture.capture
        def authoritative(*a, **kw):
            self.assertIs(Image.Image.save, original_save)
            self.assertEqual(kw, {})
            return original_capture(*a, **kw)
        capture.capture = Mock(side_effect=authoritative)
        diagnostic = {'status': 'failed', 'safe_to_close_fixture': True, 'rows': []}
        def identity(*a):
            self.assertEqual(capture.capture.call_count, 27)
            return {'bound': True}
        def supplemental(*a, **kw):
            self.assertEqual(capture.capture.call_count, 27)
            return diagnostic
        with patch.dict(sys.modules, modules), patch('screen_capture.Win32Capture', return_value=capture), \
                patch.object(phases, 'identity_snapshot', side_effect=identity), \
                patch.object(phases, 'run_supplemental', side_effect=supplemental), \
                patch.object(probe.importlib.metadata, 'version', return_value='6.11.2'), patch.object(probe.time, 'sleep'):
            result = probe.capture_benchmark(samples=7, warmups=2)
        self.assertEqual(len(result['samples_seconds']), 7)
        self.assertTrue(all(value > 0 for value in result['samples_seconds']))
        self.assertEqual(result['warmups'], 2)
        self.assertEqual(result['iterations_per_sample'], 3)
        self.assertEqual(len(result['capture_diagnostics']['authoritative_observations']), 27)
        expected = phases.output_identity(original_capture(None))
        self.assertEqual(result['output_sha256'], probe.sha256(probe.canonical(expected).encode('utf-8')))
        self.assertEqual(result['capture_diagnostics']['status'], 'failed')
        window.close.assert_called_once()

    def test_failed_preprobe_identity_skips_all_supplemental_calls_keeps_samples(self):
        app, window, modules = self.fake_qt()
        capture = FakeCapture()
        with patch.dict(sys.modules, modules), patch('screen_capture.Win32Capture', return_value=capture), \
                patch.object(phases, 'identity_snapshot', side_effect=RuntimeError('private mismatch details')), \
                patch.object(phases, 'run_supplemental') as supplemental, \
                patch.object(probe.importlib.metadata, 'version', return_value='6.11.2'), patch.object(probe.time, 'sleep'):
            result = probe.capture_benchmark(samples=7, warmups=2)
        supplemental.assert_not_called()
        self.assertEqual(capture.calls, 27)
        self.assertEqual(len(result['samples_seconds']), 7)
        diagnostic = result['capture_diagnostics']
        self.assertEqual(diagnostic['status'], 'failed')
        self.assertEqual(len(diagnostic['supplemental']['rows']), 6)
        self.assertTrue(all(row['status'] == 'not-run' for row in diagnostic['supplemental']['rows']))
        self.assertNotIn('private', json.dumps(diagnostic))
        window.close.assert_called_once()

    def test_previous_unresolved_fixture_blocks_even_programmatic_reentry(self):
        app, window, modules = self.fake_qt()
        with patch.dict(sys.modules, modules), patch.object(probe, '_RETAINED_CAPTURE_FIXTURES', [object()]), \
                patch('screen_capture.Win32Capture') as make_capture:
            with self.assertRaisesRegex(RuntimeError, 'refusing a replacement'):
                probe.capture_benchmark(samples=7, warmups=2)
        make_capture.assert_not_called()
        window.show.assert_not_called()

    def test_authoritative_cleanup_pending_exception_retains_fixture(self):
        app, window, modules = self.fake_qt()
        capture = FakeCapture()
        retained = []
        def fail(*a, **kw):
            capture.cleanup_pending = True
            raise wgc_capture.WgcError('cleanup-pending', 'owned helper still closing')
        capture.capture = fail
        with patch.dict(sys.modules, modules), patch('screen_capture.Win32Capture', return_value=capture), \
                patch.object(probe, '_RETAINED_CAPTURE_FIXTURES', retained), \
                patch.object(phases, 'run_supplemental') as supplemental, patch.object(probe.time, 'sleep'):
            with self.assertRaises(wgc_capture.WgcError):
                probe.capture_benchmark(samples=7, warmups=2)
        supplemental.assert_not_called()
        window.close.assert_not_called()
        self.assertEqual(retained, [(app, window, capture)])
        self.assertFalse(capture.closed)

    def test_unconfirmed_cleanup_retains_qt_fixture_and_original_timings(self):
        app, window, modules = self.fake_qt()
        capture = FakeCapture()
        retained = []
        with patch.dict(sys.modules, modules), patch('screen_capture.Win32Capture', return_value=capture), \
                patch.object(phases, 'identity_snapshot', return_value={'bound': True}), \
                patch.object(phases, 'run_supplemental', return_value={'status': 'failed', 'safe_to_close_fixture': False}), \
                patch.object(probe.importlib.metadata, 'version', return_value='6.11.2'), patch.object(probe.time, 'sleep'), \
                patch.object(probe, '_RETAINED_CAPTURE_FIXTURES', retained):
            result = probe.capture_benchmark(samples=7, warmups=2)
        self.assertEqual(len(result['samples_seconds']), 7)
        self.assertEqual(result['capture_diagnostics']['status'], 'failed')
        window.close.assert_not_called()
        self.assertEqual(retained, [(app, window, capture)])
        self.assertFalse(capture.closed)


if __name__ == '__main__':
    unittest.main()
