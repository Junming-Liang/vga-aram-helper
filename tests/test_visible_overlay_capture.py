"""Default-off visible-overlay routing contracts, NOT Windows pixel proof."""
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
from ctypes import wintypes as W
from persistent_capture_adapter import PersistentCaptureAdapter
from screen_capture import Win32Capture, CapturePaused, ClientRect, WindowInfo
from wgc_capture import WgcError, WgcUnavailable
from test_persistent_capture_adapter import AdapterFixture, FakeSession, STYLE


class VisibleOverlayRoutingTests(AdapterFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.adapter.close()
        self.adapter = PersistentCaptureAdapter(self.proof, session_factory=self.factory,
                                                allow_visible_overlay=True)
        self.adapter.set_overlay(101, STYLE)
        self.addCleanup(self.adapter.close)
        def factory(**kwargs):
            item = FakeSession(self.image)
            self.sessions.append(item)
            return item
        self.factory.side_effect = factory
        self.api = object.__new__(Win32Capture)
        self.api._persistent = self.adapter
        self.api._capture_lock = threading.Lock()
        self.api._overlay_hwnd = 101
        self.api._wgc = SimpleNamespace(capture=Mock(return_value=self.image))
        self.api._wgc_error = None
        self.api.validate = Mock(return_value=self.rect)
        self.api.validate_compositor = Mock(return_value=self.rect)
        self.api.u = SimpleNamespace(IsWindowVisible=Mock(return_value=True),
                                     GetDC=Mock(), ReleaseDC=Mock())

    def visible(self):
        return self.api.capture(self.target, allow_visible_overlay=True)

    def assert_no_compatibility(self):
        self.api._wgc.capture.assert_not_called()
        self.api.u.GetDC.assert_not_called()

    def test_capability_does_not_opt_default_call_into_visible_capture(self):
        self.assertTrue(self.api.can_request_visible_overlay)
        with self.assertRaises(CapturePaused): self.api.capture(self.target)
        self.factory.assert_not_called()
        self.assert_no_compatibility()

    def test_request_without_constructor_capability_never_starts_capture(self):
        self.adapter._allow_visible_overlay = False
        self.assertFalse(self.api.can_request_visible_overlay)
        with self.assertRaises(CapturePaused): self.visible()
        self.factory.assert_not_called()
        self.assert_no_compatibility()

    def test_explicit_visible_request_only_calls_v2_and_reuses_exact_mode(self):
        for _ in range(3):
            data, rect = self.visible()
            self.assertEqual(Image.open(io.BytesIO(data)).size, self.image.size)
            self.assertEqual(rect, self.rect)
        self.factory.assert_called_once_with(allow_visible_overlay=True)
        self.assertEqual(self.sessions[0].capture.call_count, 3)
        self.assertEqual(self.proof.call_args.kwargs, {'allow_visible_overlay': True})
        self.assertEqual(self.api.validate_compositor.call_args.kwargs,
                         {'allow_visible_overlay': True})
        self.assert_no_compatibility()

    def test_both_mode_transitions_retire_and_drain_without_reusing_helper(self):
        for first in (False, True):
            with self.subTest(first=first):
                # Adapter-only exercise: screen hidden checks are independently tested.
                self.setUp()
                self.capture(allow_visible_overlay=first)
                old = self.sessions[-1]
                old.cleanup_pending = True
                with self.assertRaises(WgcError): self.capture(allow_visible_overlay=not first)
                self.assertTrue(self.adapter.cleanup_pending)
                self.assertFalse(self.adapter.can_request_visible_overlay)
                with self.assertRaises(WgcError): self.capture(allow_visible_overlay=not first)
                self.assertEqual(old.capture.call_count, 1)
                old.cleanup_pending = False
                self.ready()
                self.assertTrue(self.adapter.can_request_visible_overlay)
                self.capture(allow_visible_overlay=not first)
                self.assertEqual(len(self.sessions), 2)
                self.assertEqual(self.factory.call_args.kwargs,
                                 {'allow_visible_overlay': True} if not first else {})
                self.assert_no_compatibility()
                self.adapter.close()

    def test_missing_visible_helper_ends_request_then_allows_only_later_hidden_route(self):
        self.factory.side_effect = WgcUnavailable('missing-helper', 'missing')
        with self.assertRaises(CapturePaused): self.visible()
        self.assert_no_compatibility()
        self.ready()
        self.assertFalse(self.api.can_request_visible_overlay)
        with self.assertRaises(CapturePaused): self.visible()
        with self.assertRaises(CapturePaused): self.api.capture(self.target)  # Still visible.
        self.assert_no_compatibility()
        self.api.u.IsWindowVisible.return_value = False
        self.api.capture(self.target)
        self.api._wgc.capture.assert_called_once()

    def test_native_unsupported_visible_requires_hidden_and_drained_later_request(self):
        native = FakeSession(self.image)
        native.capture.side_effect = WgcUnavailable('unsupported', 'unsupported')
        native.cleanup_pending = True
        self.factory.side_effect = None
        self.factory.return_value = native
        with self.assertRaises(CapturePaused): self.visible()
        self.api.u.IsWindowVisible.return_value = False
        with self.assertRaises(CapturePaused): self.api.capture(self.target)
        self.assert_no_compatibility()
        native.cleanup_pending = False
        self.ready()
        self.api.capture(self.target)
        self.api._wgc.capture.assert_called_once()

    def test_visible_failure_and_changed_post_guard_never_retry_backend(self):
        for failure in ('stale', 'protected', 'invalid-reply', 'timeout', 'backend-error'):
            with self.subTest(failure=failure):
                self.setUp()
                native = FakeSession(self.image)
                native.capture.side_effect = WgcError(failure, failure)
                self.factory.side_effect = None
                self.factory.return_value = native
                with self.assertRaises(CapturePaused): self.visible()
                self.assert_no_compatibility()
                self.adapter.close()
        self.setUp()
        self.proof.side_effect = [None, WgcError('stale', 'changed during readback')]
        with self.assertRaises(CapturePaused): self.visible()
        self.assertIsNone(self.api.last_session_receipt)
        self.assert_no_compatibility()

    def test_gui_hint_is_read_only_and_can_expire_before_request(self):
        self.assertTrue(self.api.can_request_visible_overlay)
        self.proof.assert_not_called()
        self.factory.assert_not_called()
        self.adapter.set_overlay()
        self.assertFalse(self.api.can_request_visible_overlay)
        with self.assertRaises(CapturePaused): self.visible()
        self.factory.assert_not_called()
        self.assert_no_compatibility()

    def test_explicit_interactive_mode_blocks_visible_request_then_hidden_compatibility(self):
        self.visible()
        native = self.sessions[0]
        native.cleanup_pending = True
        self.api.set_interactive_overlay(True)
        self.assertFalse(self.api.can_request_visible_overlay)
        with self.assertRaises(CapturePaused): self.visible()
        self.assert_no_compatibility()
        native.cleanup_pending = False
        self.ready()
        with self.assertRaises(CapturePaused): self.api.capture(self.target)
        self.api.u.IsWindowVisible.return_value = False
        self.api.capture(self.target)
        self.api._wgc.capture.assert_called_once()

    def test_visible_call_never_falls_through_even_if_adapter_returns_none(self):
        self.adapter.capture = Mock(return_value=None)
        with self.assertRaises(CapturePaused): self.visible()
        self.assert_no_compatibility()

    def test_prepared_transition_drains_before_new_explicit_capture(self):
        self.capture()
        old = self.sessions[0]
        old.cleanup_pending = True
        epoch = self.adapter.epoch
        self.assertFalse(self.adapter.prepare_capture_mode(True))
        self.assertGreater(self.adapter.epoch, epoch)
        self.assertFalse(self.adapter.prepare_capture_mode(False))
        self.assertFalse(self.adapter.prepare_capture_mode(True))
        self.assertEqual(self.factory.call_count, 1)
        old.cleanup_pending = False
        self.ready()
        self.assertTrue(self.adapter.prepare_capture_mode(True))
        self.capture(allow_visible_overlay=True)
        self.assertEqual(self.factory.call_args.kwargs, {'allow_visible_overlay': True})
        self.assertEqual(old.capture.call_count, 1)

    def test_prepare_preserves_visible_session_across_presentation_hide_show(self):
        self.assertTrue(self.adapter.prepare_capture_mode(True))
        self.capture(allow_visible_overlay=True)
        old = self.sessions[0]
        owner = self.adapter._owner
        epoch = self.adapter.epoch
        with patch('ctypes.set_last_error', create=True), \
             patch('ctypes.get_last_error', return_value=0, create=True):
            for enrolled in (0x90000000, 0x80000000):
                old._overlay_window_style = enrolled
                for current in (0x80000000, 0x90000000, 0x80000000, 0x90000000):
                    with self.subTest(enrolled=enrolled, current=current):
                        self.api.get_long = Mock(return_value=current)
                        self.assertTrue(self.api.prepare_capture_mode(True))
                        self.assertIs(self.adapter._owner, owner)
                        self.assertFalse(owner.revoked.is_set())
                        self.assertEqual(self.adapter.epoch, epoch)
            self.assertEqual(old.capture.call_count, 1)
            self.assertEqual(self.factory.call_count, 1)
            old.close.assert_not_called()
        self.assert_no_compatibility()

    def test_prepare_retires_every_other_style_bit_without_capture_or_gui_wait(self):
        for bit in range(32):
            if 1 << bit == 0x10000000:  # Only WS_VISIBLE is presentation state.
                continue
            with self.subTest(bit=bit):
                self.setUp()
                self.assertTrue(self.adapter.prepare_capture_mode(True))
                self.capture(allow_visible_overlay=True)
                old = self.sessions[0]
                old._overlay_window_style = 0x90000000
                old.cleanup_pending = True
                self.api.get_long = Mock(return_value=0x90000000 ^ (1 << bit))
                with patch('ctypes.set_last_error', create=True), \
                     patch('ctypes.get_last_error', return_value=0, create=True):
                    self.assertFalse(self.api.prepare_capture_mode(True))
                    self.assertTrue(self.adapter._owner.revoked.is_set())
                    self.assertEqual(old.capture.call_count, 1)
                    self.assertEqual(self.factory.call_count, 1)
                    old.cleanup_pending = False
                    self.ready()
                    self.assertTrue(self.api.prepare_capture_mode(True))
                self.assert_no_compatibility()
                self.adapter.close()

    def test_visibility_mask_never_preserves_session_across_strict_hidden_transition(self):
        self.assertTrue(self.adapter.prepare_capture_mode(True))
        self.capture(allow_visible_overlay=True)
        old = self.sessions[0]
        old._overlay_window_style = 0x90000000
        old.cleanup_pending = True
        self.assertFalse(self.adapter.prepare_capture_mode(False, overlay_window_style=0x80000000))
        self.assertTrue(self.adapter._owner.revoked.is_set())
        self.assertEqual(old.capture.call_count, 1)
        self.assert_no_compatibility()

    def test_prepare_during_construction_revokes_owner_and_blocks_replacement(self):
        entered, release = threading.Event(), threading.Event()
        native = FakeSession(self.image)
        def factory():
            entered.set()
            release.wait(2)
            return native
        self.factory.side_effect = factory
        outcomes = []
        def run():
            try: self.capture()
            except BaseException as error: outcomes.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.adapter.prepare_capture_mode(True))
        self.assertFalse(self.adapter.prepare_capture_mode(False))
        self.assertTrue(self.adapter.cleanup_pending)
        self.factory.assert_called_once()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.ready()
        self.assertTrue(self.adapter.prepare_capture_mode(False))
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], WgcError)
        native.capture.assert_not_called()
        native.register_idle_overlay.assert_not_called()

    def test_prepare_reports_unavailable_and_closed_but_allows_unregistered_hidden(self):
        self.adapter.set_overlay()
        self.assertTrue(self.api.prepare_capture_mode(False))
        with self.assertRaises(CapturePaused): self.api.prepare_capture_mode(True)
        self.adapter.close()
        with self.assertRaises(CapturePaused): self.api.prepare_capture_mode(False)
        self.factory.assert_not_called()
        self.assert_no_compatibility()

    def test_prepare_live_style_error_is_unavailable_not_endless_cleanup_wait(self):
        self.api.get_long = Mock(return_value=0)
        with patch('ctypes.set_last_error', create=True), \
             patch('ctypes.get_last_error', return_value=5, create=True):
            with self.assertRaises(CapturePaused): self.api.prepare_capture_mode(True)
        self.factory.assert_not_called()
        self.assert_no_compatibility()

    def test_prepare_does_not_deadlock_legacy_cleanup_worker(self):
        process = SimpleNamespace(poll=Mock(return_value=None), communicate=Mock(),
                                  stdout=Mock(), stderr=Mock())
        self.api._wgc._pending_cleanup = process
        self.assertTrue(self.api.cleanup_pending)
        self.assertFalse(self.api.can_request_visible_overlay)
        self.assertTrue(self.api.prepare_capture_mode(False))
        self.api.u.IsWindowVisible.return_value = False
        with self.assertRaises(CapturePaused): self.api.capture(self.target)
        self.factory.assert_not_called()
        self.assert_no_compatibility()
        process.poll.return_value = 0
        self.assertTrue(self.api.prepare_capture_mode(False))
        self.api.capture(self.target)
        process.communicate.assert_called_once_with(timeout=0)
        self.assertEqual(self.factory.call_count, 1)

    def test_non_boolean_capability_and_request_rejected(self):
        for value in (1, 'yes', None):
            with self.assertRaises(TypeError):
                PersistentCaptureAdapter(self.proof, allow_visible_overlay=value)
            with self.assertRaises(TypeError):
                self.api.capture(self.target, allow_visible_overlay=value)
        self.factory.assert_not_called()
        self.assert_no_compatibility()


class VisibleOverlayCompositorTests(unittest.TestCase):
    def make(self, windows):
        api = object.__new__(Win32Capture)
        target = WindowInfo(100, 10, 'owned target', 'owned')
        rect = ClientRect(0, 0, 800, 600)
        overlay = SimpleNamespace(hwnd=101, extended_style=STYLE)
        api._persistent = SimpleNamespace(overlay=overlay, can_request_visible_overlay=True)
        api.validate = Mock(return_value=rect)
        api._check_session_overlay = Mock()
        api.enum_cb = lambda function: function
        def monitor(_, out):
            out._obj.monitor = W.RECT(0, 0, 1920, 1080)
            return True
        def window_rect(hwnd, out):
            out._obj.left, out._obj.top, out._obj.right, out._obj.bottom = (10, 10, 40, 40)
            return True
        def enum(callback, _):
            for hwnd in windows:
                if not callback(hwnd, 0): break
            return True
        api.u = SimpleNamespace(MonitorFromRect=lambda *_: 1, GetMonitorInfoW=monitor,
            IsWindowVisible=lambda _: True, IsIconic=lambda _: False,
            GetWindowRect=window_rect, EnumWindows=enum)
        return api, target, rect

    def test_only_exact_enrolled_hwnd_is_exempt(self):
        for windows, success in (([101, 100], True), ([102, 101, 100], False),
                                 ([101, 102, 100], False), ([101], False)):
            api, target, rect = self.make(windows)
            if success:
                self.assertEqual(api.validate_compositor(target, rect, allow_visible_overlay=True), rect)
                self.assertEqual(api._check_session_overlay.call_count, 2)
            else:
                with self.assertRaises(CapturePaused):
                    api.validate_compositor(target, rect, allow_visible_overlay=True)

    def test_changed_registration_at_exact_exemption_point_is_denied(self):
        api, target, rect = self.make([101, 100])
        api._check_session_overlay.side_effect = [None, WgcError('stale', 'lost exclusion')]
        with self.assertRaises(CapturePaused):
            api.validate_compositor(target, rect, allow_visible_overlay=True)
