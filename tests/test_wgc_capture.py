"""Portable WGC protocol/guard tests, never presented as Windows OS evidence."""
import hashlib
import json
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
                         WgcError, WgcUnavailable, decode_frame, validate_request)


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
                               poll=Mock(return_value=code), kill=Mock(), stdout=Mock(), stdin=Mock())

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
        process.stdout.close.assert_not_called()
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
        process.stdout.close.assert_not_called(); process.kill.assert_called_once()

    def test_exited_process_with_active_pipe_reader_is_not_synchronously_closed(self):
        capture = self.wrapper(); process = self.process()
        process.communicate.side_effect = subprocess.TimeoutExpired('helper', .5)
        with patch('wgc_capture.time.monotonic', side_effect=[0., 2.1]), self.assertRaises(WgcError):
            self.invoke(capture, process)
        self.assertIs(capture._pending_cleanup, process)
        process.stdout.close.assert_not_called(); process.kill.assert_not_called()
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
