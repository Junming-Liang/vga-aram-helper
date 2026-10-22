"""Extracted production GUI methods; synthetic routing, never Windows pixel proof."""
import ast
from pathlib import Path
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from latest_capture_frame import CapturedFrame
from screen_capture import CapturePaused, CaptureUnavailable, ClientRect, WindowInfo
from session_windows import ProcessMetadata


SOURCE = Path(__file__).resolve().parents[1] / 'native_ui.py'


def extracted_method(name, **context):
    tree = ast.parse(SOURCE.read_text(encoding='utf8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ControlWindow')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(CapturedFrame=CapturedFrame, CapturePaused=CapturePaused,
                     CaptureUnavailable=CaptureUnavailable, **context)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace[name]


class LatestCaptureUiTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.time = SimpleNamespace(monotonic=lambda: self.now)
        self.target = WindowInfo(100, 20, 'Owned target', 'OwnedClass')
        self.rect = ClientRect(20, 30, 80, 60)
        self.metadata = ProcessMetadata('C:/owned.exe', 12345)
        self.frame_scope = (self.target.identity, self.metadata, self.rect, (0., 0., 1., 1.),
                            ('owned title',), ('source',), (None, None))
        self.logger = SimpleNamespace(record=Mock())
        self.capture = SimpleNamespace(
            has_live_visible_session=True, can_request_visible_overlay=True,
            visible_capture_status='eligible', session_epoch=9,
            capture=Mock(return_value=(b'owned frame', self.rect)),
            foreground=Mock(return_value=True), rect=Mock(return_value=self.rect),
            prepare_capture_mode=Mock(return_value=True), last_capture_diagnostic={})
        self.slot = SimpleNamespace(busy=False, submit=Mock(return_value=True),
                                    take_failure=Mock(return_value=None), clear=Mock())
        self.overlay = SimpleNamespace(
            click_through=True, reference=False, isVisible=Mock(return_value=False),
            hide=Mock(), show_at=Mock(), set_rechecking=Mock(), hidden_settle_ms=Mock(return_value=0))
        self.control = SimpleNamespace(
            closed=False, state=SimpleNamespace(running=True, generation=7, confirmed=False),
            target=self.target, capture=self.capture, latest_capture=self.slot,
            overlay=self.overlay, enable_visible_capture=True, ocr_busy=True,
            capture_pending=False, _prefetch_last_attempt=0., _capture_serial=11,
            _current_capture_proof=(7, 11, {'_frameScope': self.frame_scope}),
            _capture_cancel=threading.Event(), _cancel_workers=threading.Event(),
            discovery_scope=3, client_phase=Mock(return_value=False),
            capture_metadata=Mock(return_value=self.metadata),
            debug_log=SimpleNamespace(enabled=False, scoped=lambda: self.logger, sample=Mock()),
            debug_event=Mock(), debug_selection_gate=Mock(), schedule_capture=Mock(),
            activate_idle_first_portraits=Mock(), client_selection_reference=Mock(return_value=None),
            current_partial_names=Mock(return_value=('', '', '')), last_observation=10.,
            _accepted_frame=None, _accepted_partial_frame=None, _visible_previous=False,
            _mode_wait_started=None, _restore_while_ocr=False, monitor=SimpleNamespace(stop=Mock()),
            refresh_status_badge=Mock(), capture_hidden=Mock(), invalidate_scene=Mock(),
            status=SimpleNamespace(text=Mock(return_value=''), setText=Mock()),
            queue_discovery=Mock(), advance_session_window=Mock(), target_allowed=Mock(return_value=True),
            ocr_started=100., ocr_timed_out=False, _partial_displayed=False,
            last_rect=self.rect, was_target_foreground=True, clear_partial_candidates=Mock())
        self.control.queue_latest_capture = MethodType(extracted_method('queue_latest_capture', time=self.time), self.control)
        self.timer = Mock()
        self.capture_tick = extracted_method('capture_tick', time=self.time,
            QtCore=SimpleNamespace(QTimer=SimpleNamespace(singleShot=self.timer)))

    def submit(self):
        self.control.queue_latest_capture(self.now, self.rect)
        self.slot.submit.assert_called_once()
        return self.slot.submit.call_args.args

    def test_capture_while_ocr_busy_only_acquires_exact_registered_scope(self):
        scope, acquire = self.submit()
        self.assertEqual(scope, (7, 3, self.frame_scope, 9))
        self.assertEqual(self.control._prefetch_last_attempt, 100.)
        self.assertEqual(acquire(lambda: False), CapturedFrame(b'owned frame', self.rect, 100., 100.))
        args, kwargs = self.capture.capture.call_args
        self.assertEqual(args, (self.target, (0., 0., 1., 1.)))
        self.assertEqual(kwargs['expected_metadata'], self.metadata)
        self.assertIs(kwargs['allow_visible_overlay'], True)
        self.assertFalse(kwargs['cancelled']())
        self.assertEqual(self.control.last_observation, 10.)
        self.assertFalse(self.control.state.confirmed)
        self.overlay.hide.assert_not_called()
        self.overlay.show_at.assert_not_called()
        self.overlay.set_rechecking.assert_not_called()

    def test_unenrolled_or_unproven_state_cannot_start_producer(self):
        mutations = (
            lambda c: setattr(c, 'ocr_busy', False),
            lambda c: setattr(c, 'capture_pending', True),
            lambda c: setattr(c.overlay, '_capture_retirement_pending', True),
            lambda c: setattr(c, 'client_phase', lambda: True),
            lambda c: setattr(c, 'enable_visible_capture', False),
            lambda c: setattr(c.overlay, 'click_through', False),
            lambda c: setattr(c.capture, 'has_live_visible_session', False),
            lambda c: setattr(c, '_prefetch_last_attempt', 99.5),
            lambda c: setattr(c.latest_capture, 'busy', True),
            lambda c: setattr(c, '_current_capture_proof', None),
            lambda c: setattr(c, '_current_capture_proof', (6, 11, {'_frameScope': self.frame_scope})),
            lambda c: setattr(c, '_current_capture_proof', (7, 10, {'_frameScope': self.frame_scope})),
            lambda c: setattr(c, '_current_capture_proof', (7, 11, {})),
            lambda c: setattr(c, 'target', WindowInfo(101, 20, 'Other', 'OwnedClass')),
            lambda c: setattr(c, 'capture_metadata', lambda: ProcessMetadata('C:/owned.exe', 54321)),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.setUp()
                mutate(self.control)
                self.control.queue_latest_capture(self.now, self.rect)
                self.slot.submit.assert_not_called()
                self.capture.capture.assert_not_called()
        self.setUp()
        self.control.queue_latest_capture(self.now, ClientRect(21, 30, 80, 60))
        self.slot.submit.assert_not_called()

    def test_rejected_submission_does_not_advance_rate_clock(self):
        self.slot.submit.return_value = False
        self.submit()
        self.assertEqual(self.control._prefetch_last_attempt, 0.)

    def test_cancellation_and_session_loss_before_worker_never_capture(self):
        for cause in ('slot_revoked', 'cancel', 'close', 'session'):
            with self.subTest(cause=cause):
                self.setUp()
                _, acquire = self.submit()
                if cause == 'cancel': self.control._capture_cancel.set()
                if cause == 'close': self.control._cancel_workers.set()
                if cause == 'session': self.capture.has_live_visible_session = False
                with self.assertRaises(CapturePaused): acquire(lambda: cause == 'slot_revoked')
                self.capture.capture.assert_not_called()

    def test_capture_post_guard_rejects_cancel_geometry_and_epoch_change(self):
        for cause in ('cancel', 'rect', 'epoch'):
            with self.subTest(cause=cause):
                self.setUp()
                _, acquire = self.submit()
                def changed(*args, **kwargs):
                    if cause == 'cancel': self.control._capture_cancel.set()
                    if cause == 'epoch': self.capture.session_epoch += 1
                    return b'owned frame', ClientRect(21, 30, 80, 60) if cause == 'rect' else self.rect
                self.capture.capture.side_effect = changed
                with self.assertRaises(CapturePaused): acquire(lambda: False)
                self.overlay.show_at.assert_not_called()

    def test_primary_capture_waits_for_producer_without_replacing_cancel_event(self):
        self.control.ocr_busy = False
        self.slot.busy = True
        original = self.control._capture_cancel
        self.capture_tick(self.control)
        self.control.schedule_capture.assert_called_once_with(50)
        self.capture.prepare_capture_mode.assert_not_called()
        self.timer.assert_not_called()
        self.assertIs(self.control._capture_cancel, original)

    def test_direct_capture_entry_waits_for_producer_without_swapping_cancellation(self):
        self.slot.busy = True
        original = self.control._capture_cancel
        entry = extracted_method('capture_hidden', time=self.time,
            QtCore=SimpleNamespace(QTimer=SimpleNamespace(singleShot=self.timer)))
        entry(self.control, 7, 11, allow_visible_overlay=True)
        self.timer.assert_called_once()
        self.assertEqual(self.timer.call_args.args[0], 50)
        self.assertEqual(self.control._capture_serial, 11)
        self.assertIs(self.control._capture_cancel, original)
        self.control.monitor.stop.assert_not_called()
        self.capture.capture.assert_not_called()
        self.timer.call_args.args[1]()
        self.control.capture_hidden.assert_called_once_with(7, 11, allow_visible_overlay=True)

    def test_ttl_hidden_overlay_continues_enrolled_mode_without_display_authority(self):
        self.control.ocr_busy = False
        self.capture_tick(self.control)
        self.capture.prepare_capture_mode.assert_called_once_with(True)
        self.assertTrue(self.control._visible_previous)
        self.assertFalse(self.control.state.confirmed)
        self.assertIsNone(self.control._accepted_frame)
        self.assertEqual(self.control.last_observation, 10.)
        self.overlay.show_at.assert_not_called()
        self.overlay.hide.assert_not_called()
        self.timer.assert_called_once()
        self.assertEqual(self.timer.call_args.args[0], 0)
        self.timer.call_args.args[1]()
        self.control.capture_hidden.assert_called_once_with(7, 12, allow_visible_overlay=True)

    def test_hidden_unproven_overlay_cannot_create_initial_visible_session(self):
        self.control.ocr_busy = False
        self.capture.has_live_visible_session = False
        self.capture_tick(self.control)
        self.capture.prepare_capture_mode.assert_called_once_with(False)
        self.overlay.hide.assert_called_once_with('capture_pending')
        self.timer.call_args.args[1]()
        self.control.capture_hidden.assert_called_once_with(7, 12, allow_visible_overlay=False)

    def test_route_flag_and_successful_prefetch_do_not_redisplay_expired_grade(self):
        self.control._visible_previous = True
        self.control.queue_latest_capture = Mock()
        check_target = extracted_method('check_target', time=self.time)
        check_target(self.control)
        self.control.queue_latest_capture.assert_called_once_with(100., self.rect)
        self.control.invalidate_scene.assert_not_called()
        self.overlay.show_at.assert_not_called()
        self.assertFalse(self.control.state.confirmed)
        self.assertEqual(self.control.last_observation, 10.)

    def test_producer_failure_invalidates_before_more_capture_or_display(self):
        self.slot.take_failure.return_value = (7, 3, self.frame_scope, 9)
        self.control.queue_latest_capture = Mock()
        extracted_method('check_target', time=self.time)(self.control)
        self.control.invalidate_scene.assert_called_once()
        self.control.queue_latest_capture.assert_not_called()
        self.overlay.show_at.assert_not_called()

    def test_repeated_hidden_prefetch_never_changes_observation_or_display(self):
        check_target = extracted_method('check_target', time=self.time)
        self.control._visible_previous = True
        for _ in range(6):
            self.slot.submit.reset_mock()
            check_target(self.control)
            self.slot.submit.assert_called_once()
            scope, acquire = self.slot.submit.call_args.args
            packet = acquire(lambda: False)
            self.assertEqual(scope, (7, 3, self.frame_scope, 9))
            self.assertEqual(packet.captured_at, self.now)
            self.assertFalse(self.control.state.confirmed)
            self.assertIsNone(self.control._accepted_frame)
            self.assertEqual(self.control.last_observation, 10.)
            self.now += .8
        self.assertEqual(self.capture.capture.call_count, 6)
        self.overlay.show_at.assert_not_called()
        self.overlay.hide.assert_not_called()
        self.control.invalidate_scene.assert_not_called()

    def test_retirement_clears_slot_and_routes_without_waiting_or_display(self):
        self.capture.retire_session = Mock()
        self.control._visible_previous = True
        extracted_method('retire_capture_session')(self.control)
        self.slot.clear.assert_called_once()
        self.capture.retire_session.assert_called_once()
        self.assertFalse(self.control._visible_previous)
        self.assertIsNone(self.control._mode_wait_started)
        self.overlay.show_at.assert_not_called()


class BufferedConsumptionTests(unittest.TestCase):
    def setUp(self):
        # Run the production acquisition prefix directly, excluding the unrelated
        # recognition pipeline and Qt setup. No duplicated guard implementation.
        tree = ast.parse(SOURCE.read_text(encoding='utf8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ControlWindow')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'capture_hidden')
        infer = next(node for node in ast.walk(method) if isinstance(node, ast.FunctionDef) and node.name == 'infer')
        start = next(i for i, node in enumerate(infer.body)
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id == 'captured_at')
        end = next(i for i, node in enumerate(infer.body)
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == 'pixels_at')
        self.code = compile(ast.Module(body=infer.body[start:end+1], type_ignores=[]), str(SOURCE), 'exec')
        self.rect = ClientRect(20, 30, 80, 60)
        self.metadata = ProcessMetadata('C:/owned.exe', 12345)
        self.capture = SimpleNamespace(has_live_visible_session=True, session_epoch=9,
            validate_compositor=Mock(), capture=Mock(), last_capture_diagnostic={})
        self.namespace = dict(prefetched=CapturedFrame(b'owned frame', self.rect, 99.3, 99.5),
            capture=self.capture, prefetch_scope=(7, 3, 'exact frame scope', 9),
            frame_window=WindowInfo(100, 20, 'Owned target', 'OwnedClass'),
            expected_metadata=self.metadata, CapturePaused=CapturePaused,
            time=SimpleNamespace(monotonic=lambda: 100.), logger=SimpleNamespace(record=Mock()),
            generation=7, serial=12)

    def test_consuming_slot_retains_original_timestamp_and_rechecks_live_binding(self):
        with patch('session_windows.process_metadata', return_value=self.metadata) as metadata:
            exec(self.code, self.namespace)
        metadata.assert_called_once_with(20)
        self.assertEqual(self.namespace['captured_at'], 99.3)
        self.assertEqual(self.namespace['image'], b'owned frame')
        self.assertEqual(self.namespace['rect'], self.rect)
        self.capture.validate_compositor.assert_called_once_with(
            self.namespace['frame_window'], self.rect, allow_visible_overlay=True)
        self.capture.capture.assert_not_called()

    def test_worker_delay_after_slot_take_rejects_expired_or_future_frame(self):
        for now in (101.3, 99.2):
            with self.subTest(now=now):
                self.namespace['time'] = SimpleNamespace(monotonic=lambda: now)
                with patch('session_windows.process_metadata', return_value=self.metadata):
                    with self.assertRaises(CapturePaused): exec(self.code, self.namespace)
                self.capture.validate_compositor.assert_not_called()
                self.capture.capture.assert_not_called()
                self.assertNotIn('image', self.namespace)

    def test_compositor_guard_duration_cannot_age_buffer_past_limit(self):
        now = [100.]
        self.namespace['time'] = SimpleNamespace(monotonic=lambda: now[0])
        self.capture.validate_compositor.side_effect = lambda *a, **kw: now.__setitem__(0, 100.2)
        with patch('session_windows.process_metadata', return_value=self.metadata):
            with self.assertRaises(CapturePaused): exec(self.code, self.namespace)
        self.capture.validate_compositor.assert_called_once()
        self.capture.capture.assert_not_called()
        self.assertNotIn('image', self.namespace)

    def test_live_process_change_rejects_buffer_without_new_capture(self):
        for changed in (ProcessMetadata('C:/owned.exe', 54321), ProcessMetadata('C:/other.exe', 12345)):
            with self.subTest(changed=changed):
                with patch('session_windows.process_metadata', return_value=changed):
                    with self.assertRaises(CapturePaused): exec(self.code, self.namespace)
                self.capture.validate_compositor.assert_not_called()
                self.capture.capture.assert_not_called()

    def test_lifecycle_or_compositor_failure_never_falls_back(self):
        for cause in ('revoked', 'epoch', 'compositor'):
            with self.subTest(cause=cause):
                self.setUp()
                if cause == 'revoked': self.capture.has_live_visible_session = False
                if cause == 'epoch': self.capture.session_epoch = 10
                if cause == 'compositor': self.capture.validate_compositor.side_effect = CapturePaused('Changed')
                with patch('session_windows.process_metadata', return_value=self.metadata):
                    with self.assertRaises(CapturePaused): exec(self.code, self.namespace)
                self.capture.capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
