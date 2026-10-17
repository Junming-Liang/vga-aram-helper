"""Portable production routing/lifetime contracts; not live Windows evidence."""
import io
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from persistent_capture_adapter import PersistentCaptureAdapter
from screen_capture import Win32Capture, WindowInfo, ClientRect, CapturePaused
from session_windows import ProcessMetadata
from wgc_capture import WgcError, WgcUnavailable
from PIL import Image

STYLE = 0x00080000 | 0x08000000 | 0x80 | 0x8 | 0x20
METADATA = ProcessMetadata(r'C:\owned\fixture.exe', 12345)


def eventually(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError('Condition did not become true')


class FakeSession:
    def __init__(self, image):
        self._transport = SimpleNamespace(revoked=threading.Event())
        self.cleanup_pending = False
        self.close = Mock(side_effect=self._close)
        self.register_idle_overlay = Mock()
        self.capture = Mock(return_value=image)

    def _close(self):
        self._transport.revoked.set()


class AdapterFixture:
    def setUp(self):
        self.metadata_patch = patch('persistent_capture_adapter.process_metadata', return_value=METADATA)
        self.metadata = self.metadata_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.target = WindowInfo(100, 20, 'owned target', 'FixtureClass')
        self.rect = ClientRect(20, 30, 80, 60)
        self.image = Image.new('RGB', (80, 60), 'red')
        self.image.paste('blue', (0, 0, 40, 30))
        self.sessions = []
        def factory():
            session = FakeSession(self.image)
            self.sessions.append(session)
            return session
        self.factory = Mock(side_effect=factory)
        self.proof = Mock()
        self.adapter = PersistentCaptureAdapter(self.proof, session_factory=self.factory)
        self.adapter.set_overlay(101, STYLE)
        self.addCleanup(self.adapter.close)

    def capture(self, **kwargs):
        return self.adapter.capture(self.target, self.rect, (0, 0, 80, 60), cancelled=lambda: False, **kwargs)

    def ready(self):
        eventually(lambda: not self.adapter.cleanup_pending)


class AdapterTests(AdapterFixture, unittest.TestCase):
    def test_compatibility_reason_is_allowlisted_and_read_only(self):
        epoch=self.adapter.epoch
        self.assertEqual(self.adapter.compatibility_status,'unknown')
        self.adapter._unavailable='private path or stderr'
        self.assertEqual(self.adapter.compatibility_status,'unknown')
        for reason in ('missing-helper','unsupported'):
            self.adapter._unavailable=reason
            self.assertEqual(self.adapter.compatibility_status,reason)
        self.adapter._unavailable=None;self.adapter._overlay=None
        self.assertEqual(self.adapter.compatibility_status,'exclusion-unregistered')
        self.adapter._interactive_overlay=True
        self.assertEqual(self.adapter.compatibility_status,'interactive')
        self.adapter._enabled=False
        self.assertEqual(self.adapter.compatibility_status,'disabled')
        self.assertEqual(self.adapter.epoch,epoch)
        self.factory.assert_not_called();self.proof.assert_not_called()

    def test_visible_mode_reason_is_read_only_and_does_not_grant_capture(self):
        self.assertEqual(self.adapter.visible_capture_status,'disabled')
        self.adapter._allow_visible_overlay=True
        self.assertEqual(self.adapter.visible_capture_status,'eligible')
        self.adapter._interactive_overlay=True
        self.assertEqual(self.adapter.visible_capture_status,'interactive')
        self.adapter._interactive_overlay=False;self.adapter._overlay=None
        self.assertEqual(self.adapter.visible_capture_status,'exclusion_unregistered')
        self.adapter._unavailable='owned failure'
        self.assertEqual(self.adapter.visible_capture_status,'backend_unavailable')
        self.adapter.close()
        self.assertEqual(self.adapter.visible_capture_status,'stopped')
        self.factory.assert_not_called();self.proof.assert_not_called()

    def test_same_binding_reuses_instance_and_registration(self):
        for _ in range(3):
            self.assertIs(self.capture(), self.image)
        self.factory.assert_called_once()
        session = self.sessions[0]
        session.register_idle_overlay.assert_called_once_with(101, STYLE, 1)
        self.assertEqual(session.capture.call_count, 3)
        self.assertEqual(self.proof.call_count, 6)
        self.assertEqual(session.capture.call_args.kwargs['expected_metadata'], METADATA)

    def test_title_change_reuses_but_exact_class_or_target_change_retires(self):
        self.capture()
        self.target = WindowInfo(100, 20, 'new title', 'FixtureClass')
        self.capture()
        self.assertEqual(len(self.sessions), 1)
        self.target = WindowInfo(100, 20, 'new title', 'OtherClass')
        with self.assertRaisesRegex(WgcError, '窗口或进程'):
            self.capture()
        self.ready()
        self.capture()
        self.assertEqual(len(self.sessions), 2)
        self.assertEqual(self.sessions[0].capture.call_count, 2)

    def test_target_pid_creation_path_or_geometry_change_never_retargets(self):
        for mutation in ('hwnd', 'pid', 'created', 'path', 'move', 'resize'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.capture()
                if mutation == 'hwnd': self.target = WindowInfo(200, 20, 'owned', 'FixtureClass')
                if mutation == 'pid': self.target = WindowInfo(100, 21, 'owned', 'FixtureClass')
                if mutation == 'created': self.metadata.return_value = ProcessMetadata(METADATA.path, 12346)
                if mutation == 'path': self.metadata.return_value = ProcessMetadata(r'C:\other.exe', 12345)
                if mutation == 'move': self.rect = ClientRect(21, 30, 80, 60)
                if mutation == 'resize': self.rect = ClientRect(20, 30, 81, 60)
                with self.assertRaises(WgcError): self.capture()
                self.assertEqual(self.sessions[0].capture.call_count, 1)
                self.ready()
                self.capture()
                self.assertEqual(len(self.sessions), 2)
                self.adapter.close()

    def test_missing_optional_helper_allows_preuse_compatibility(self):
        self.factory.side_effect = WgcUnavailable('missing-helper', 'missing')
        self.assertIsNone(self.capture())
        self.assertIsNone(self.capture())
        self.assertFalse(self.adapter.cleanup_pending)
        self.factory.assert_called_once()

    def test_corrupt_helper_fails_closed_even_if_overlay_is_then_unavailable(self):
        self.factory.side_effect = WgcError('untrusted-helper', 'corrupt')
        with self.assertRaisesRegex(WgcError, 'corrupt'): self.capture()
        self.ready()
        self.adapter.set_overlay()
        with self.assertRaises(WgcError): self.capture()
        self.assertEqual(self.factory.call_count, 1)

    def test_native_unsupported_retires_before_later_compatibility(self):
        session = FakeSession(self.image)
        session.capture.side_effect = WgcUnavailable('unsupported', 'unsupported')
        session.cleanup_pending = True
        self.factory.side_effect = None; self.factory.return_value = session
        with self.assertRaises(WgcError): self.capture()
        with self.assertRaises(WgcError) as error: self.capture()
        self.assertEqual(error.exception.status, 'cleanup-pending')
        session.cleanup_pending = False; self.ready()
        self.assertIsNone(self.capture())
        self.factory.assert_called_once()

    def test_unsupported_after_prior_output_cannot_downgrade(self):
        self.capture()
        self.sessions[0].capture.side_effect = WgcUnavailable('unsupported', 'changed')
        with self.assertRaises(WgcError): self.capture()
        self.ready(); self.adapter.set_overlay()
        with self.assertRaises(WgcError): self.capture()

    def test_any_denied_session_never_enables_compatibility(self):
        for status in ('stale', 'protected', 'invalid-reply', 'timeout', 'backend-error', 'cancelled'):
            with self.subTest(status=status):
                self.setUp()
                session = FakeSession(self.image)
                session.capture.side_effect = WgcError(status, status)
                self.factory.side_effect = None; self.factory.return_value = session
                with self.assertRaises(WgcError): self.capture()
                self.ready(); self.adapter.set_overlay()
                with self.assertRaises(WgcError): self.capture()
                self.factory.assert_called_once()
                self.adapter.close()

    def test_pending_native_cleanup_retains_instance_and_prevents_replacement(self):
        self.capture(); session = self.sessions[0]; session.cleanup_pending = True
        self.adapter.retire()
        eventually(lambda: session.close.called)
        for _ in range(3):
            with self.assertRaises(WgcError) as error: self.capture()
            self.assertEqual(error.exception.status, 'cleanup-pending')
        self.assertIs(self.adapter._owner.session, session)
        self.factory.assert_called_once()
        session.cleanup_pending = False; self.ready(); self.capture()
        self.assertEqual(len(self.sessions), 2)
        session.close.assert_called_once()

    def test_idle_native_revocation_replaces_instance_not_its_transport(self):
        self.capture(); session = self.sessions[0]
        session._transport.revoked.set()
        try: self.capture()
        except WgcError as error: self.assertEqual(error.status, 'cleanup-pending')
        self.ready(); self.capture()
        self.assertEqual(len(self.sessions), 2)
        self.assertEqual(session.capture.call_count, 1)

    def test_registered_overlay_change_retires_before_new_registration(self):
        self.capture(); session = self.sessions[0]; session.cleanup_pending = True
        self.adapter.set_overlay(102, STYLE)
        self.assertTrue(self.adapter._owner.revoked.is_set())
        with self.assertRaises(WgcError): self.capture()
        session.cleanup_pending = False; self.ready(); self.capture()
        self.sessions[1].register_idle_overlay.assert_called_once_with(102, STYLE, 2)

    def test_failed_live_overlay_proof_never_starts_helper(self):
        self.proof.side_effect = WgcError('stale', 'style/affinity changed')
        with self.assertRaises(WgcError): self.capture()
        self.factory.assert_not_called()

    def test_stop_during_blocked_constructor_returns_promptly_and_prevents_capture(self):
        entered, release = threading.Event(), threading.Event()
        session = FakeSession(self.image)
        def factory():
            entered.set(); release.wait(2); return session
        self.factory.side_effect = factory
        outcome = []
        def capture():
            try: self.capture()
            except BaseException as error: outcome.append(error)
        thread = threading.Thread(target=capture)
        thread.start(); self.assertTrue(entered.wait(1))
        start = time.monotonic(); self.adapter.retire()
        self.assertLess(time.monotonic() - start, .25)
        self.assertTrue(self.adapter.cleanup_pending)
        with self.assertRaises(WgcError): self.adapter.check_ready()
        self.factory.assert_called_once()
        release.set(); thread.join(2); self.assertFalse(thread.is_alive())
        self.ready(); self.assertEqual(len(outcome), 1)
        session.capture.assert_not_called(); session.register_idle_overlay.assert_not_called()
        session.close.assert_called_once()

    def test_real_frozen_wrapper_held_state_lock_cannot_block_retire(self):
        from wgc_session_capture import WgcSessionCapture
        session = object.__new__(WgcSessionCapture)
        session._state = threading.Lock()
        session._closed = False
        session.last_timing = None
        session._overlay = session._parent = None
        revoked = threading.Event(); ready = threading.Event(); ready.set()
        session._transport = SimpleNamespace(revoked=revoked, ready_for_replacement=ready,
                                             revoke=lambda *_: revoked.set())
        session.register_idle_overlay = Mock()
        entered, release = threading.Event(), threading.Event()
        def blocked_capture(*args, **kwargs):
            entered.set(); release.wait(2); return self.image
        session.capture = blocked_capture
        self.factory.side_effect = None; self.factory.return_value = session
        outcome = []
        def capture():
            try: outcome.append(self.capture())
            except BaseException as error: outcome.append(error)
        thread = threading.Thread(target=capture); thread.start()
        self.assertTrue(entered.wait(1)); session._state.acquire()
        try:
            start = time.monotonic(); self.adapter.retire()
            self.assertLess(time.monotonic() - start, .25)
            self.assertTrue(self.adapter.cleanup_pending)
            self.assertFalse(self.adapter._owner.close_done.is_set())
        finally:
            session._state.release(); release.set()
        thread.join(2); self.assertFalse(thread.is_alive()); self.ready()
        self.assertTrue(session._closed)
        self.assertEqual(len(outcome), 1); self.assertIsInstance(outcome[0], WgcError)

    def test_held_wrapper_state_close_and_late_result_never_block_gui(self):
        entered, release_capture, close_started, release_close = (threading.Event() for _ in range(4))
        session = FakeSession(self.image)
        def slow_capture(*args, **kwargs):
            entered.set(); release_capture.wait(2); return self.image
        def slow_close():
            close_started.set(); release_close.wait(2)
        session.capture.side_effect = slow_capture; session.close.side_effect = slow_close
        self.factory.side_effect = None; self.factory.return_value = session
        outcome = []
        def capture():
            try: outcome.append(self.capture())
            except BaseException as error: outcome.append(error)
        thread = threading.Thread(target=capture)
        thread.start(); self.assertTrue(entered.wait(1))
        start = time.monotonic(); self.adapter.retire(); self.adapter.close()
        self.assertLess(time.monotonic() - start, .25)
        self.assertTrue(close_started.wait(1)); self.assertTrue(self.adapter.cleanup_pending)
        # Even after wrapper close returns/native cleanup clears, the outstanding
        # caller is a barrier until its possible late image is discarded.
        release_close.set(); eventually(lambda: self.adapter._owner.close_done.is_set())
        self.assertTrue(self.adapter.cleanup_pending)
        release_capture.set(); thread.join(2); self.assertFalse(thread.is_alive())
        self.ready(); self.assertEqual(len(outcome), 1); self.assertIsInstance(outcome[0], WgcError)
        session.close.assert_called_once()
        self.factory.assert_called_once()
        with self.assertRaises(WgcError): self.capture()


class ProductRoutingTests(AdapterFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.capture_api = object.__new__(Win32Capture)
        self.capture_api._persistent = self.adapter
        self.capture_api._capture_lock = threading.Lock()
        self.capture_api._overlay_hwnd = 101
        self.capture_api._wgc = SimpleNamespace(capture=Mock(return_value=self.image))
        self.capture_api._wgc_error = None
        self.capture_api.validate = Mock(return_value=self.rect)
        self.capture_api.validate_compositor = Mock(return_value=self.rect)
        self.capture_api.u = SimpleNamespace(IsWindowVisible=Mock(return_value=False),
            GetDC=Mock(return_value=10), ReleaseDC=Mock())
        self.capture_api._copy_pixels = Mock(return_value=self.image)

    def test_explicit_disabled_baseline_never_constructs_session(self):
        self.adapter.close()
        self.adapter = PersistentCaptureAdapter(self.proof, session_factory=self.factory, enabled=False)
        self.capture_api._persistent = self.adapter
        self.adapter.set_overlay(101, STYLE)
        self.capture_api.capture(self.target)
        self.factory.assert_not_called()
        self.capture_api._wgc.capture.assert_called_once()
        self.assertEqual(self.capture_api.last_backend, 'windows-graphics-capture')
        self.assertIsNone(self.capture_api.last_session_receipt)
        self.capture_api.close()
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)

    def test_product_success_preserves_png_rect_and_never_uses_v1_or_gdi(self):
        png, rect = self.capture_api.capture(self.target)
        self.assertEqual(Image.open(io.BytesIO(png)).size, (80, 60))
        self.assertEqual(rect, self.rect)
        self.assertEqual(self.capture_api.last_backend, 'windows-graphics-capture-session')
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()

    def test_visible_exact_owned_overlay_denies_all_cpu_backends(self):
        self.capture_api.u.IsWindowVisible.return_value = True
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.factory.assert_not_called()
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()

    def test_focus_or_whole_client_occlusion_rejection_retires_idle_helper(self):
        self.capture_api.capture(self.target)
        self.capture_api.validate_compositor.side_effect = CapturePaused('foreign occluder')
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        eventually(lambda: self.sessions[0].close.called)
        self.assertEqual(self.sessions[0].capture.call_count, 1)
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()

    def test_blank_or_malformed_size_retires_without_fallback(self):
        for image in (None, Image.new('RGB', (80, 60), 'black'), Image.new('RGB', (81, 60), 'red')):
            with self.subTest(size=getattr(image,'size',None)):
                self.setUp()
                session = FakeSession(image)
                self.factory.side_effect = None; self.factory.return_value = session
                with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
                eventually(lambda: session.close.called)
                self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()
                self.adapter.close()

    def test_failed_post_compositor_check_discards_session_image(self):
        self.capture_api.validate_compositor.side_effect = [self.rect, CapturePaused('geometry changed')]
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()

    def test_no_exact_exclusion_and_missing_helper_preserve_one_shot_fallback(self):
        self.adapter.set_overlay()
        self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_called_once()
        self.factory.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()
        self.capture_api._wgc.capture.reset_mock()
        self.adapter.set_overlay(101, STYLE)
        self.factory.side_effect = WgcUnavailable('missing-helper', 'missing')
        self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_called_once()

    def test_one_shot_unsupported_preserves_original_gdi_route(self):
        self.adapter.set_overlay()
        self.capture_api._wgc.capture.side_effect = WgcUnavailable('unsupported', 'unsupported')
        self.capture_api.capture(self.target)
        self.capture_api.u.GetDC.assert_called_once_with(self.target.hwnd)
        self.assertEqual(self.capture_api.last_backend, 'window-dc')

    def test_pending_one_shot_cleanup_blocks_session_until_complete(self):
        process = SimpleNamespace(poll=Mock(return_value=None), communicate=Mock(),
                                  stdout=Mock(), stderr=Mock())
        self.capture_api._wgc._pending_cleanup = process
        self.assertTrue(self.capture_api.cleanup_pending)
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.factory.assert_not_called(); self.capture_api._wgc.capture.assert_not_called()
        process.poll.return_value = 0
        self.capture_api.capture(self.target)
        process.communicate.assert_called_once_with(timeout=0)
        process.stdout.close.assert_called_once(); process.stderr.close.assert_called_once()
        self.factory.assert_called_once()
        self.assertFalse(self.capture_api.cleanup_pending)

    def test_pending_session_cleanup_blocks_even_otherwise_eligible_v1(self):
        self.capture_api.capture(self.target)
        self.sessions[0].cleanup_pending = True
        self.adapter.set_overlay()
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()
        self.sessions[0].cleanup_pending = False

    def test_receipt_published_only_after_all_product_post_guards(self):
        receipt = dict(request_id=1, session_generation=2)
        with patch.object(self.adapter, '_receipt', return_value=receipt):
            self.capture_api.capture(self.target)
        self.assertEqual(dict(self.capture_api.last_session_receipt), receipt)
        self.adapter.set_overlay(102, STYLE)
        self.assertIsNone(self.capture_api.last_session_receipt)
        self.ready()
        self.capture_api.validate_compositor.side_effect = [self.rect, CapturePaused('changed')]
        with patch.object(self.adapter, '_receipt', return_value=receipt):
            with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.assertIsNone(self.capture_api.last_session_receipt)

    def test_explicit_interactive_mode_waits_for_native_cleanup_then_uses_strict_v1(self):
        self.capture_api.capture(self.target)
        session = self.sessions[0]; session.cleanup_pending = True
        self.capture_api.set_interactive_overlay(True)
        self.assertIsNone(self.adapter.overlay)
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_not_called()
        session.cleanup_pending = False; self.ready()
        self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_called_once()
        self.assertEqual(self.capture_api.last_backend, 'windows-graphics-capture')
        self.assertEqual(len(self.sessions), 1)
        self.capture_api.u.IsWindowVisible.return_value = True
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.assertEqual(self.capture_api._wgc.capture.call_count, 1)

    def test_affinity_loss_never_selects_explicit_interactive_route(self):
        self.capture_api.capture(self.target)
        self.adapter.set_overlay()  # Simulates failed exact0x11 enrollment.
        self.ready()
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_not_called()
        self.assertFalse(self.adapter._interactive_overlay)

    def test_toggle_back_requires_new_registration_and_creates_fresh_session(self):
        self.capture_api.capture(self.target)
        self.capture_api.set_interactive_overlay(True); self.ready()
        self.capture_api.capture(self.target)
        self.capture_api.set_interactive_overlay(False)
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.assertEqual(self.capture_api._wgc.capture.call_count, 1)
        self.adapter.set_overlay(101, STYLE)
        self.capture_api.capture(self.target)
        self.assertEqual(len(self.sessions), 2)
        self.assertEqual(self.sessions[0].capture.call_count, 1)
        self.assertEqual(self.capture_api.last_backend, 'windows-graphics-capture-session')

    def test_explicit_mode_does_not_erase_prior_sticky_failure(self):
        session = FakeSession(self.image); session.capture.side_effect = WgcError('stale', 'stale')
        self.factory.side_effect = None; self.factory.return_value = session
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.capture_api.set_interactive_overlay(True); self.ready()
        self.capture_api.capture(self.target)
        self.capture_api.set_interactive_overlay(False)
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.assertEqual(self.capture_api._wgc.capture.call_count, 1)

    def test_mode_change_cancels_old_request_without_same_request_fallback(self):
        session = FakeSession(self.image); entered, release = threading.Event(), threading.Event()
        def slow_capture(*args, **kwargs):
            entered.set(); release.wait(2); return self.image
        session.capture.side_effect = slow_capture
        self.factory.side_effect = None; self.factory.return_value = session
        results = []
        def capture():
            try: results.append(self.capture_api.capture(self.target))
            except BaseException as error: results.append(error)
        thread = threading.Thread(target=capture); thread.start(); self.assertTrue(entered.wait(1))
        self.capture_api.set_interactive_overlay(True)
        release.set(); thread.join(2); self.assertFalse(thread.is_alive()); self.ready()
        self.assertEqual(len(results), 1); self.assertIsInstance(results[0], CapturePaused)
        self.capture_api._wgc.capture.assert_not_called()
        self.capture_api.capture(self.target)
        self.capture_api._wgc.capture.assert_called_once()

    def test_toggle_back_waits_for_active_one_shot_worker_before_v2(self):
        self.capture_api.set_interactive_overlay(True)
        entered, release = threading.Event(), threading.Event()
        def slow_capture(*args, **kwargs):
            entered.set(); release.wait(2); return self.image
        self.capture_api._wgc.capture.side_effect = slow_capture
        results = []
        def capture():
            try: results.append(self.capture_api.capture(self.target))
            except BaseException as error: results.append(error)
        thread = threading.Thread(target=capture); thread.start(); self.assertTrue(entered.wait(1))
        self.capture_api.set_interactive_overlay(False); self.adapter.set_overlay(101, STYLE)
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target)
        self.factory.assert_not_called()
        release.set(); thread.join(2); self.assertFalse(thread.is_alive())
        self.assertIsInstance(results[0], CapturePaused)
        self.capture_api.capture(self.target)
        self.factory.assert_called_once()

    def test_mode_toggle_is_typed_and_idempotent(self):
        with self.assertRaises(TypeError): self.capture_api.set_interactive_overlay('yes')
        self.capture_api.set_interactive_overlay(True)
        epoch = self.adapter.epoch
        self.capture_api.set_interactive_overlay(True)
        self.assertEqual(self.adapter.epoch, epoch)

    def test_precancelled_and_cancel_during_png_serialization_discard(self):
        event = threading.Event(); event.set()
        with self.assertRaises(CapturePaused): self.capture_api.capture(self.target, cancelled=event)
        self.factory.assert_not_called()
        event.clear()
        original_save = self.image.save
        def save(*args, **kwargs):
            original_save(*args, **kwargs); event.set()
        with patch.object(self.image, 'save', side_effect=save):
            with self.assertRaises(CapturePaused): self.capture_api.capture(self.target, cancelled=event)
        self.capture_api._wgc.capture.assert_not_called(); self.capture_api.u.GetDC.assert_not_called()


class ReceiptTests(AdapterFixture, unittest.TestCase):
    def make_receipt_session(self):
        session = FakeSession(self.image)
        session.last_timing = dict(request_cutoff_100ns=10, frame_100ns=11,
            idle_enter_100ns=12, request_id=1, session_generation=77)
        session._transport.generation = 77
        session._transport.process = SimpleNamespace(pid=234, poll=Mock(return_value=None))
        session._overlay = (101, STYLE, 445566)
        return session

    def test_receipt_is_exact_bounded_detached_and_immutable(self):
        session = self.make_receipt_session()
        self.factory.side_effect = None; self.factory.return_value = session
        with patch('wgc_session_capture._window_api', return_value=SimpleNamespace(GetPropW=Mock(return_value=445566))):
            self.capture()
        receipt = self.adapter.last_receipt
        self.assertEqual(dict(receipt), dict(session.last_timing, helper_pid=234,
            helper_created=METADATA.created, overlay_hwnd=101, overlay_extended_style=STYLE,
            overlay_affinity=17, overlay_registration_valid=True))
        self.assertNotIn('token', str(list(receipt)))
        self.assertNotIn('path', receipt)
        session.last_timing['request_id'] = 999
        self.assertEqual(receipt['request_id'], 1)
        with self.assertRaises(TypeError): receipt['request_id'] = 2
        self.adapter.retire(); self.assertIsNone(self.adapter.last_receipt)

    def test_receipt_rejects_unverified_registration_or_exited_helper(self):
        session = self.make_receipt_session()
        overlay = self.adapter.overlay
        with patch('wgc_session_capture._window_api', return_value=SimpleNamespace(GetPropW=lambda *_: 1)):
            self.assertIsNone(self.adapter._receipt(session, overlay))
        session._transport.process.poll.return_value = 0
        with patch('wgc_session_capture._window_api') as api:
            self.assertIsNone(self.adapter._receipt(session, overlay)); api.assert_not_called()

    def test_receipt_rejects_boolean_unknown_or_nonmonotonic_timing(self):
        for mutation in ({'request_id': True}, {'private_path': 'private'}, {'frame_100ns': 9}):
            session = self.make_receipt_session(); session.last_timing.update(mutation)
            self.assertIsNone(self.adapter._receipt(session, self.adapter.overlay))

    def test_receipt_rejects_helper_exit_during_metadata_read(self):
        session = self.make_receipt_session()
        session._transport.process.poll.side_effect = [None, 0]
        with patch('wgc_session_capture._window_api', return_value=SimpleNamespace(GetPropW=lambda *_: 445566)):
            self.assertIsNone(self.adapter._receipt(session, self.adapter.overlay))


if __name__ == '__main__':
    unittest.main()
