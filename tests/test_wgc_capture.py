"""Portable WGC protocol/guard tests, never presented as Windows OS evidence."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from screen_capture import CapturePaused, ClientRect, Win32Capture, WindowInfo
from session_windows import ProcessMetadata
from wgc_capture import (HEADER, MAGIC, HELPER_NAME, MANIFEST_NAME, WgcCapture,
                         WgcError, WgcUnavailable, decode_frame, validate_request,
                         MAX_DIAGNOSTIC_BYTES, DIAGNOSTIC_PHASES, DIAGNOSTIC_CHECKS,
                         sanitize_native_diagnostic, decode_native_diagnostic)


class WgcTests(unittest.TestCase):
    def setUp(self):
        self.target = WindowInfo(123, 77, 'owned fixture', 'RiotWindowClass')
        self.rect = ClientRect(-1000, 60, 800, 600)
        self.roi = (100, 40, 32, 24)
        self.metadata = ProcessMetadata('c:\\owned\\fixture.exe', 133000000000000000)
        self.pixels = bytes([17, 23, 29, 255]) * (32 * 24)
        self.encoded = HEADER.pack(MAGIC, 1, 32, 24, len(self.pixels)) + self.pixels

    def wrapper(self):
        capture = object.__new__(WgcCapture)
        capture.helper_path = Path('/owned/native/vga-wgc-capture.exe')
        capture._verify_helper = Mock()
        return capture

    def process(self, code=0, data=None):
        return SimpleNamespace(returncode=code, communicate=Mock(return_value=(self.encoded if data is None else data, None)),
                               poll=Mock(return_value=code), kill=Mock(), stdout=Mock(), stderr=Mock(), stdin=Mock())

    def invoke(self, capture, process, **kwargs):
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.process_metadata', return_value=self.metadata), \
             patch('wgc_capture._CaptureJob'), \
             patch('wgc_capture.subprocess.Popen', return_value=process) as spawn:
            image = capture.capture(self.target, self.rect, self.roi, **kwargs)
        return image, spawn

    def test_exact_roi_bgra_protocol(self):
        image = decode_frame(self.encoded, self.roi)
        self.assertEqual(image.size, (32, 24))
        self.assertEqual(image.getpixel((0, 0)), (29, 23, 17))

    def test_protocol_never_accepts_trailing_missing_or_changed_dimensions(self):
        for data in (b'', self.encoded[:-1], self.encoded + b'x',
                     HEADER.pack(MAGIC, 1, 24, 32, len(self.pixels)) + self.pixels,
                     HEADER.pack(b'OTHER123', 1, 32, 24, len(self.pixels)) + self.pixels,
                     HEADER.pack(MAGIC, 2, 32, 24, len(self.pixels)) + self.pixels):
            with self.subTest(length=len(data)), self.assertRaises(WgcError) as error:
                decode_frame(data, self.roi)
            self.assertEqual(error.exception.status, 'invalid-reply')

    def test_invalid_roi_fails_before_process_or_metadata(self):
        capture = self.wrapper()
        for roi in ((-1, 0, 32, 24), (0, 0, 801, 600), (0, 0, 0, 20),
                    (0, 0, 32.0, 24), (False, 0, 32, 24), (0, 0, 32)):
            with self.subTest(roi=roi), patch('wgc_capture.process_metadata') as metadata, \
                 patch('wgc_capture.subprocess.Popen') as spawn, self.assertRaises(WgcError):
                capture.capture(self.target, self.rect, roi)
            metadata.assert_not_called(); spawn.assert_not_called()

    def test_precancel_event_never_starts_process(self):
        cancelled = threading.Event(); cancelled.set()
        with patch('wgc_capture.subprocess.Popen') as spawn, self.assertRaises(WgcError) as error:
            self.wrapper().capture(self.target, self.rect, self.roi, cancelled=cancelled)
        self.assertEqual(error.exception.status, 'cancelled'); spawn.assert_not_called()

    def test_exact_hwnd_and_creation_sent_without_shell_or_monitor(self):
        process = self.process()
        image, spawn = self.invoke(self.wrapper(), process)
        args = spawn.call_args.args[0]
        self.assertEqual(args[1:], ['--capture-v1', '123', '77', str(self.metadata.created),
            '-1000', '60', '800', '600', '100', '40', '32', '24', '800'])
        self.assertFalse(spawn.call_args.kwargs['shell'])
        self.assertEqual(spawn.call_args.kwargs['stdin'], subprocess.PIPE)
        self.assertEqual(spawn.call_args.kwargs['stderr'], subprocess.PIPE)
        self.assertEqual(image.size, (32, 24)); process.kill.assert_not_called()

    def test_native_start_gate_is_released_only_after_job_assignment(self):
        process = self.process(); job = Mock(); events = []
        job.assign.side_effect = lambda child: events.append(('assigned', child))
        process.stdin.write.side_effect = lambda value: events.append(('started', value))
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.process_metadata', return_value=self.metadata), \
             patch('wgc_capture._CaptureJob', return_value=job), patch('wgc_capture.subprocess.Popen', return_value=process):
            self.wrapper().capture(self.target, self.rect, self.roi)
        self.assertEqual(events, [('assigned', process), ('started', b'C')])
        job.close.assert_called_once()

    def test_failed_job_assignment_never_releases_capture_gate(self):
        process = self.process(); input_pipe = process.stdin; job = Mock()
        job.assign.side_effect = OSError('Cannot establish lifetime boundary')
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.process_metadata', return_value=self.metadata), \
             patch('wgc_capture._CaptureJob', return_value=job), patch('wgc_capture.subprocess.Popen', return_value=process), \
             self.assertRaises(WgcError) as error:
            self.wrapper().capture(self.target, self.rect, self.roi)
        self.assertEqual(error.exception.status, 'backend-error')
        input_pipe.write.assert_not_called(); job.close.assert_called_once()

    def test_unconfirmed_job_close_blocks_frame_and_next_spawn(self):
        capture = self.wrapper(); process = self.process(); job = Mock()
        job.close.return_value = False
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.process_metadata', return_value=self.metadata), \
             patch('wgc_capture._CaptureJob', return_value=job), patch('wgc_capture.subprocess.Popen', return_value=process), \
             self.assertRaises(WgcError) as error:
            capture.capture(self.target, self.rect, self.roi)
        self.assertEqual(error.exception.status, 'cleanup-pending')
        self.assertIs(capture._pending_job, job)
        with patch('wgc_capture.subprocess.Popen') as spawn, self.assertRaises(WgcError):
            capture.capture(self.target, self.rect, self.roi)
        spawn.assert_not_called()

    def test_only_unsupported_status_allows_fallback(self):
        for code, status in ((10, 'unsupported'), (11, 'timeout'), (12, 'stale'),
                             (13, 'protected'), (14, 'backend-error'), (99, 'backend-error')):
            with self.subTest(code=code), self.assertRaises(WgcError) as error:
                self.invoke(self.wrapper(), self.process(code))
            self.assertEqual(error.exception.status, status)
            self.assertEqual(isinstance(error.exception, WgcUnavailable), code == 10)

    def test_changed_process_creation_discards_success(self):
        process = self.process()
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.subprocess.Popen', return_value=process), \
             patch('wgc_capture._CaptureJob'), \
             patch('wgc_capture.process_metadata', side_effect=[self.metadata, ProcessMetadata(self.metadata.path, self.metadata.created + 1)]), \
             self.assertRaises(WgcError) as error:
            self.wrapper().capture(self.target, self.rect, self.roi)
        self.assertEqual(error.exception.status, 'stale')

    def test_original_process_binding_rejected_before_native_spawn(self):
        capture = self.wrapper()
        original = ProcessMetadata(self.metadata.path, self.metadata.created - 1)
        with patch('wgc_capture.os.name', 'nt'), patch('wgc_capture.process_metadata', return_value=self.metadata), \
             patch('wgc_capture.subprocess.Popen') as spawn, self.assertRaises(WgcError) as error:
            capture.capture(self.target, self.rect, self.roi, expected_metadata=original)
        self.assertEqual(error.exception.status, 'stale'); spawn.assert_not_called()

    def test_midflight_cancellation_kills_only_owned_helper(self):
        process = self.process(); process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired('helper', .05), (b'', None)]
        cancelled = Mock(side_effect=[False, False, True])
        with self.assertRaises(WgcError) as error:
            self.invoke(self.wrapper(), process, cancelled=cancelled)
        self.assertEqual(error.exception.status, 'cancelled'); process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_args.kwargs['timeout'], .5)

    def test_hard_deadline_kills_owned_helper(self):
        process = self.process(); process.poll.return_value = None
        with patch('wgc_capture.time.monotonic', side_effect=[0., 2.1]), self.assertRaises(WgcError) as error:
            self.invoke(self.wrapper(), process)
        self.assertEqual(error.exception.status, 'timeout'); process.kill.assert_called_once()

    def test_delayed_os_cleanup_never_blocks_on_pipe_or_accumulates_helpers(self):
        capture = self.wrapper(); process = self.process(); process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired('helper', .5)
        with patch('wgc_capture.time.monotonic', side_effect=[0., 2.1]), self.assertRaises(WgcError):
            self.invoke(capture, process)
        self.assertIs(capture._pending_cleanup, process)
        process.stdout.close.assert_not_called(); process.stderr.close.assert_not_called()
        with patch('wgc_capture.subprocess.Popen') as spawn, self.assertRaises(WgcError) as error:
            capture.capture(self.target, self.rect, self.roi)
        self.assertEqual(error.exception.status, 'cleanup-pending'); spawn.assert_not_called()

    def test_failed_termination_retains_only_owned_process(self):
        capture = self.wrapper(); process = self.process(); process.poll.return_value = None
        process.kill.side_effect = OSError('Termination delayed by OS')
        process.communicate.side_effect = subprocess.TimeoutExpired('helper', .5)
        with patch('wgc_capture.time.monotonic', side_effect=[0., 2.1]), self.assertRaises(WgcError):
            self.invoke(capture, process)
        self.assertIs(capture._pending_cleanup, process)
        process.stdout.close.assert_not_called(); process.stderr.close.assert_not_called(); process.kill.assert_called_once()

    def test_exited_process_with_active_pipe_reader_is_not_synchronously_closed(self):
        capture = self.wrapper(); process = self.process()
        process.communicate.side_effect = subprocess.TimeoutExpired('helper', .5)
        with patch('wgc_capture.time.monotonic', side_effect=[0., 2.1]), self.assertRaises(WgcError):
            self.invoke(capture, process)
        self.assertIs(capture._pending_cleanup, process)
        process.stdout.close.assert_not_called(); process.stderr.close.assert_not_called(); process.kill.assert_not_called()
        with self.assertRaises(WgcError) as error:
            capture.capture(self.target, self.rect, self.roi)
        self.assertEqual(error.exception.status, 'cleanup-pending')

    def test_missing_helper_is_optional_but_bad_manifest_is_not(self):
        with tempfile.TemporaryDirectory() as directory, patch('wgc_capture.helper_directory', return_value=Path(directory)):
            with self.assertRaises(WgcUnavailable): WgcCapture()
            (Path(directory) / HELPER_NAME).write_bytes(b'not an executable')
            with self.assertRaises(WgcError) as error: WgcCapture()
            self.assertNotIsInstance(error.exception, WgcUnavailable)
            self.assertEqual(error.exception.status, 'untrusted-helper')

    def test_hash_manifest_and_no_path_override(self):
        with tempfile.TemporaryDirectory() as directory, patch('wgc_capture.helper_directory', return_value=Path(directory)):
            path = Path(directory) / HELPER_NAME; path.write_bytes(b'owned test bytes')
            proof = {'schema_version': 1, 'protocol': 1, 'filename': HELPER_NAME,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size,
                     'source_sha256': 'a' * 64, 'build_recipe_sha256': 'b' * 64}
            (Path(directory) / MANIFEST_NAME).write_text(json.dumps(proof), encoding='utf-8')
            capture = WgcCapture(); self.assertEqual(capture.helper_path, path)
            path.write_bytes(b'changed test exe')
            with self.assertRaises(WgcError) as error: capture._verify_helper()
            self.assertEqual(error.exception.status, 'untrusted-helper')


class WgcDiagnosticTests(unittest.TestCase):
    def diagnostic(self):
        return {'schema_version': 1, 'code': 12, 'phase': 'item-size', 'check': 'item-dimensions',
                'hresult': 0, 'observed': [0, 0, 336, 279], 'expected': [0, 0, 322, 272],
                'window_rect': [20, 30, 336, 279], 'frame_rect': [27, 30, 322, 272],
                'style': 0, 'extended_style': 0}

    def encoded(self, value=None):
        return json.dumps(self.diagnostic() if value is None else value).encode('ascii')

    def test_allowlisted_native_failure_survives_exactly_and_is_detached(self):
        value = self.diagnostic()
        result = decode_native_diagnostic(self.encoded(value), 12)
        self.assertEqual(result, value)
        sanitized = sanitize_native_diagnostic(value)
        value['observed'][0] = 999
        self.assertEqual(sanitized['observed'][0], 0)
        error = WgcError('stale', 'safe message', sanitized)
        sanitized['observed'][0] = 888
        self.assertEqual(error.diagnostic['observed'][0], 0)
        self.assertEqual(str(error), 'safe message')

    def test_unknown_private_fields_or_ids_are_never_preserved(self):
        for key in ('title', 'path', 'pid', 'hwnd', 'pixels', 'stderr', 'environment'):
            value = dict(self.diagnostic(), **{key: 'must never appear'})
            with self.subTest(key=key):
                self.assertIsNone(sanitize_native_diagnostic(value))
                self.assertIsNone(decode_native_diagnostic(self.encoded(value), 12))
        for field in ('phase', 'check'):
            value = self.diagnostic(); value[field] = 'private arbitrary text'
            self.assertIsNone(sanitize_native_diagnostic(value))

    def test_missing_fields_bad_types_and_out_of_bounds_values_rejected(self):
        baseline = self.diagnostic()
        for field in baseline:
            value = dict(baseline); del value[field]
            with self.subTest(missing=field):
                self.assertIsNone(sanitize_native_diagnostic(value))
        for field, bad in (('schema_version', True), ('schema_version', 2), ('code', True),
                ('code', 0), ('code', 99), ('phase', []), ('check', {}), ('hresult', -1),
                ('hresult', 2**32), ('style', True), ('extended_style', '0'),
                ('observed', [0, 0, 32, True]), ('observed', [0, 0, 32, 2**32]),
                ('expected', [0, 0, 32]), ('window_rect', (0, 0, 32, 24)),
                ('frame_rect', [0, 0, 32, -(2**32)-1])):
            value = dict(baseline); value[field] = bad
            with self.subTest(field=field, bad=bad):
                self.assertIsNone(sanitize_native_diagnostic(value))

    def test_only_one_bounded_ascii_record_matching_exit_status_is_accepted(self):
        valid = self.encoded()
        self.assertIsNotNone(decode_native_diagnostic(valid, 12))
        for data in (None, '', b'', valid + valid, b'prefix ' + valid, b'\xff',
                     valid + b' ' * MAX_DIAGNOSTIC_BYTES, b'[' * 999,
                     valid.replace(b'"code": 12', b'"code": 12, "code": 12')):
            with self.subTest(data=str(data)[:80]):
                self.assertIsNone(decode_native_diagnostic(data, 12))
        self.assertIsNone(decode_native_diagnostic(valid, 14))
        self.assertIsNone(decode_native_diagnostic(valid, 0))

    def test_native_buffer_and_phase_check_ids_match_parser_contract(self):
        source = (Path(__file__).resolve().parents[1] / 'native/wgc_capture.cpp').read_text()
        self.assertIn('char data[1024]{};', source)
        self.assertEqual(set(re.findall(r'phase\("([a-z-]+)"\)', source)) | {'startup'}, DIAGNOSTIC_PHASES)
        identifiers = set(re.findall(r'(?:stale|unsupported|timed_out|protected_content|failed), "([a-z-]+)"', source))
        identifiers |= {'invariant', 'hresult', 'exception', 'occluder-query', 'occluder-overlap'}
        self.assertEqual(identifiers, DIAGNOSTIC_CHECKS)

    def test_native_mapping_keeps_one_origin_and_all_geometry_snapshots_bound(self):
        source = (Path(__file__).resolve().parents[1] / 'native/wgc_capture.cpp').read_text()
        self.assertIn('capture_model(geometry.window, geometry.frame, size.Width, size.Height)', source)
        self.assertIn('require(model != -1, stale, "capture-origin")', source)
        self.assertIn('capture_bounds = selected_model == 1 ? geometry.window : geometry.frame;', source)
        self.assertIn('same(g.window, expected->window)', source)
        self.assertIn('same(g.frame, expected->frame)', source)
        self.assertIn('same(g.client, expected->client)', source)
        self.assertIn('UINT(int64_t(p.x) - capture_bounds.left + p.left)', source)
        self.assertIn('UINT(int64_t(p.y) - capture_bounds.top + p.top)', source)
        self.assertIn('require(content.Width == content_width && content.Height == content_height', source)
        self.assertIn('content_model(geometry.window, geometry.frame, size.Width,', source)
        self.assertIn('require(selected_model != -2, stale, "content-in-pool")', source)
        self.assertIn('roi_inside(left, top, p.roi_width, p.roi_height, content.Width, content.Height)', source)
        self.assertIn('roi_inside(left, top, p.roi_width, p.roi_height, source.Width, source.Height)', source)
        self.assertIn('last_content_width, last_content_height, 0, 0, size.Width, size.Height', source)
        # These evaluate in the mandatory native compiler gate, not just Python.
        self.assertGreaterEqual(source.count('static_assert(capture_model('), 9)
        self.assertGreaterEqual(source.count('static_assert(content_model('), 6)
        self.assertGreaterEqual(source.count('static_assert(roi_inside('), 3)
        self.assertGreaterEqual(source.count('static_assert(!roi_inside('), 3)

    def test_native_failure_attaches_only_sanitized_evidence_and_closes_both_pipes(self):
        harness = WgcTests(); harness.setUp()
        process = harness.process(12)
        process.communicate.return_value = (b'', self.encoded())
        with self.assertRaises(WgcError) as error:
            harness.invoke(harness.wrapper(), process)
        self.assertEqual(error.exception.status, 'stale')
        self.assertEqual(error.exception.diagnostic, self.diagnostic())
        process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()
        for bad in (b'private stderr text', self.encoded(dict(self.diagnostic(), path='private'))):
            process = harness.process(12); process.communicate.return_value = (b'', bad)
            with self.assertRaises(WgcError) as error:
                harness.invoke(harness.wrapper(), process)
            self.assertEqual(error.exception.status, 'stale')
            self.assertIsNone(error.exception.diagnostic)
            self.assertNotIn('private', str(error.exception))

    def test_unknown_native_exit_remains_failure_with_numeric_evidence(self):
        harness = WgcTests(); harness.setUp()
        process = harness.process(3221225477)
        process.communicate.return_value = (b'partial-packet', b'private stderr')
        with self.assertRaises(WgcError) as error:
            harness.invoke(harness.wrapper(), process)
        self.assertEqual(error.exception.status, 'backend-error')
        self.assertEqual(error.exception.process_evidence,
            {'returncode':3221225477, 'stdout_bytes':14, 'stderr_bytes':14})
        self.assertIsNone(error.exception.diagnostic)
        self.assertNotIn('private', str(error.exception))
        process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()

    def test_success_ignores_stderr_and_closes_both_pipes(self):
        harness = WgcTests(); harness.setUp()
        process = harness.process()
        process.communicate.return_value = (harness.encoded, b'private stray stderr')
        image, _ = harness.invoke(harness.wrapper(), process)
        self.assertEqual(image.size, (32, 24))
        process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()

    def test_pending_cleanup_closes_both_pipes_only_after_communicate_finishes(self):
        harness = WgcTests(); harness.setUp()
        capture = harness.wrapper(); pending = harness.process()
        capture._pending_cleanup = pending
        harness.invoke(capture, harness.process())
        pending.communicate.assert_called_once_with(timeout=0)
        pending.stdout.close.assert_called_once(); pending.stderr.close.assert_called_once()
        self.assertIsNone(capture._pending_cleanup)


class WgcRoutingTests(unittest.TestCase):
    def setUp(self):
        self.capture = object.__new__(Win32Capture)
        self.target = WindowInfo(123, 77, 'owned', 'RiotWindowClass')
        self.rect = ClientRect(10, 20, 800, 600)
        self.capture.validate = Mock(return_value=self.rect)
        self.capture.validate_compositor = Mock(return_value=self.rect)
        self.capture.u = SimpleNamespace(GetDC=Mock(return_value=10), ReleaseDC=Mock())
        self.picture = Image.new('RGB', (800, 600), 'black'); self.picture.paste('red', (0, 0, 400, 300))
        self.capture._copy_pixels = Mock(return_value=self.picture)
        self.capture._wgc = SimpleNamespace(capture=Mock(return_value=self.picture))

    def test_wgc_success_never_acquires_screen_or_window_dc(self):
        self.capture.capture(self.target)
        self.assertEqual(self.capture.last_backend, 'windows-graphics-capture')
        self.capture.u.GetDC.assert_not_called(); self.capture._copy_pixels.assert_not_called()

    def test_wgc_denial_timeout_stale_never_calls_gdi(self):
        for status in ('protected', 'timeout', 'stale', 'invalid-reply', 'cancelled', 'backend-error'):
            with self.subTest(status=status):
                self.capture._wgc.capture.side_effect = WgcError(status, status)
                with self.assertRaises(CapturePaused): self.capture.capture(self.target)
                self.capture.u.GetDC.assert_not_called()

    def test_wgc_blank_is_not_circumvented_with_gdi(self):
        self.capture._wgc.capture.return_value = Image.new('RGB', (800, 600), 'black')
        with self.assertRaises(CapturePaused): self.capture.capture(self.target)
        self.capture.u.GetDC.assert_not_called()

    def test_geometry_or_occlusion_changed_after_wgc_discards_image(self):
        self.capture.validate_compositor.side_effect = [self.rect, CapturePaused('changed')]
        with self.assertRaises(CapturePaused): self.capture.capture(self.target)
        self.capture.u.GetDC.assert_not_called()

    def test_unsupported_uses_existing_guarded_hwnd_path(self):
        self.capture._wgc.capture.side_effect = WgcUnavailable('unsupported', 'unsupported')
        self.capture.capture(self.target)
        self.assertEqual(self.capture.last_backend, 'window-dc')
        self.capture.u.GetDC.assert_called_once_with(self.target.hwnd)

    def test_tampered_helper_fails_closed(self):
        self.capture._wgc_error = WgcError('untrusted-helper', 'changed')
        with self.assertRaises(CapturePaused): self.capture.capture(self.target)
        self.capture._wgc.capture.assert_not_called(); self.capture.u.GetDC.assert_not_called()

    def test_original_metadata_binding_blocks_wgc_and_gdi_before_pixel_access(self):
        original = ProcessMetadata('c:\\owned\\fixture.exe', 100)
        for backend in (self.capture._wgc, None):
            with self.subTest(wgc=backend is not None):
                self.capture._wgc = backend
                with patch('session_windows.process_metadata', return_value=ProcessMetadata(original.path, 101)), \
                     self.assertRaises(CapturePaused):
                    self.capture.capture(self.target, expected_metadata=original)
                self.capture.u.GetDC.assert_not_called(); self.capture._copy_pixels.assert_not_called()
                if backend is not None: backend.capture.assert_not_called()

    def test_known_window_capture_protection_blocks_all_backends(self):
        capture = object.__new__(Win32Capture)
        capture.rect = Mock(return_value=self.rect)
        capture.foreground = Mock(return_value=True)
        def protected(hwnd, pointer):
            pointer._obj.value = 0x11
            return True
        capture.u = SimpleNamespace(GetWindowDisplayAffinity=protected)
        with self.assertRaises(CapturePaused): capture.validate(self.target)


if __name__ == '__main__': unittest.main()
