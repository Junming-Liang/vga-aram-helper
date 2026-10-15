"""Portable Qt scheduling regression; not Windows capture or OCR evidence."""
import ast
import json
import os
from pathlib import Path
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    import native_smoke
    from native_ui import ControlWindow
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class NativeSmokeCadenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.monitor = QtCore.QTimer()
        self.monitor.setSingleShot(True)
        self.unsolicited = []
        self.monitor.timeout.connect(lambda: self.unsolicited.append(True))
        self.addCleanup(self.monitor.stop)
        self.control = SimpleNamespace(
            closed=False, current_version='owned-test',
            state=SimpleNamespace(running=True, generation=2, confirmed=False),
            ocr_busy=False, capture_pending=False, monitor=self.monitor,
            # The production scheduler selects zero delay near the freshness
            # boundary. The fixed clock below avoids a test-machine timing race.
            last_observation=100., selection_session=None,
            client_phase=lambda: False, client_strength_reference=lambda: None,
            overlay=SimpleNamespace(set_rechecking=lambda value: None),
            captured_frame_current=lambda value: False,
            refresh_status_badge=lambda: None)
        self.control.schedule_capture = MethodType(ControlWindow.schedule_capture, self.control)
        self.original_schedule = self.control.schedule_capture

    def complete_observation(self):
        # Use the real production handler, including its finally scheduling
        # path. The owned value is deliberately not claimed as a native frame.
        with patch('native_ui.time', SimpleNamespace(monotonic=lambda: 103.99)):
            ControlWindow.task_result(self.control, 'ocr', {'_capturedAt': 103.99}, 2)

    def test_stopping_monitor_once_does_not_prevent_completion_rearming(self):
        self.monitor.stop()
        self.complete_observation()
        self.assertTrue(self.monitor.isActive())
        self.assertEqual(self.monitor.interval(), 0)
        self.app.processEvents()
        self.assertEqual(self.unsolicited, [True])

    def test_manual_results_and_event_pumps_do_not_add_captures(self):
        self.monitor.start(0)
        restore = native_smoke._manual_smoke_cadence(self.control)
        self.addCleanup(restore)
        for _ in range(4):
            self.complete_observation()
            self.control.schedule_capture(0)
            self.app.processEvents()
            self.assertFalse(self.monitor.isActive())
        self.assertEqual(self.unsolicited, [])
        restore()
        self.assertIs(self.control.schedule_capture, self.original_schedule)
        self.complete_observation()
        self.assertTrue(self.monitor.isActive())  # Normal runtime is restored.

    def test_explicit_production_capture_tick_still_dispatches_its_capture(self):
        control = self.control
        dispatched = []
        control.target = object()
        control.capture = SimpleNamespace(foreground=lambda target: True)
        control.enable_visible_capture = False
        control._mode_wait_started = None
        control._capture_serial = 0
        control.debug_event = lambda *args, **kwargs: None
        control.overlay.isVisible = lambda: False
        control.overlay.hide = lambda reason: None
        control.overlay.hidden_settle_ms = lambda: 0
        control.capture_hidden = lambda *args, **kwargs: dispatched.append((args, kwargs))
        capture_tick = MethodType(ControlWindow.capture_tick, control)
        control.capture_tick = capture_tick
        restore = native_smoke._manual_smoke_cadence(control)
        self.addCleanup(restore)
        control.capture_tick()
        self.app.processEvents()
        self.assertIs(control.capture_tick, capture_tick)
        self.assertEqual(dispatched, [((2, 1), {'allow_visible_overlay': False})])
        self.assertEqual(self.unsolicited, [])
        self.complete_observation()
        self.assertFalse(self.monitor.isActive())

    def test_nested_duty_scheduler_restore_keeps_outer_manual_cadence(self):
        restore = native_smoke._manual_smoke_cadence(self.control)
        self.addCleanup(restore)
        outer_schedule = self.control.schedule_capture
        self.control.schedule_capture = lambda delay=None: None
        self.control.signals = SimpleNamespace(result=Mock(), error=Mock())
        # Execute the actual nested duty cleanup with owned adapters. It must
        # restore to this smoke's outer guard, not to the runtime scheduler.
        tree = ast.parse(Path(native_smoke.__file__).read_text(encoding='utf8'))
        duty = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == '_start_overlay_duty_mode')
        cleanup = next(node for node in duty.body
                       if isinstance(node, ast.FunctionDef) and node.name == 'cleanup')
        scope = dict(control=self.control, original_schedule=outer_schedule,
                     active=[None], overlay=Mock(), visibility_guard=Mock(),
                     capture_adapter=SimpleNamespace(), hero_recognition=SimpleNamespace(),
                     wgc_capture=SimpleNamespace(subprocess=SimpleNamespace()),
                     original_capture=object(), original_compositor=object(),
                     original_recognize=object(), original_popen=object(), original_job=object(),
                     observed=object(), observed_error=object())
        exec(compile(ast.Module(body=[cleanup], type_ignores=[]),
                     native_smoke.__file__, 'exec'), scope)
        scope['cleanup']()
        self.assertIs(self.control.schedule_capture, outer_schedule)
        self.complete_observation()
        self.app.processEvents()
        self.assertEqual(self.unsolicited, [])

    def test_successful_terminal_closure_restores_before_close(self):
        control = self.control
        restore = native_smoke._manual_smoke_cadence(control)
        self.addCleanup(restore)
        self.monitor.start(0)
        events = []
        def close():
            self.assertIs(control.schedule_capture, self.original_schedule)
            self.assertFalse(self.monitor.isActive())
            events.append('close')
        control.close = close
        control.isVisible = lambda: False
        control.hotkey_registered = False
        mock = SimpleNamespace(close=lambda: events.append('mock-close'), isVisible=lambda: False)
        overlay = SimpleNamespace(isVisible=lambda: False)
        report, checks, save, app = {}, [], Mock(), SimpleNamespace(exit=Mock())
        # Run the unchanged successful-close suffix of the production smoke
        # closure. Earlier Win32 assertions remain Windows-only evidence.
        tree = ast.parse(Path(native_smoke.__file__).read_text(encoding='utf8'))
        start = next(node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == 'start_smoke')
        verify = next(node for node in start.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'verify_overlay')
        index = next(index for index, node in enumerate(verify.body)
                     if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Name)
                     and node.value.func.id == 'restore_schedule')
        terminal = ast.Module(body=verify.body[index:], type_ignores=[])
        exec(compile(terminal, native_smoke.__file__, 'exec'),
             dict(control=control, mock=mock, overlay=overlay, report=report,
                  checks=checks, save=save, app=app, restore_schedule=restore))
        self.assertEqual(events, ['close', 'mock-close'])
        self.assertEqual(report, {'window_closed': True, 'status': 'passed'})
        save.assert_called_once_with()
        app.exit.assert_called_once_with(0)
        self.app.processEvents()
        self.assertEqual(self.unsolicited, [])
        self.monitor.start(0)
        restore()
        self.assertFalse(self.monitor.isActive())
        self.assertIs(self.control.schedule_capture, self.original_schedule)
        restore()  # Terminal cleanup is safe if a later callback fails too.
        self.app.processEvents()
        self.assertEqual(self.unsolicited, [])

    def test_smoke_failure_restores_after_nested_cleanup_and_before_close(self):
        events = []
        control = self.control
        def nested_cleanup():
            events.append('nested')
            control.schedule_capture = lambda delay=None: None
            self.monitor.start(0)
            raise RuntimeError('Owned nested cleanup failure')
        control._smoke_duty_cleanup = nested_cleanup
        control._smoke_duty_outer_cleanup = lambda: events.append('outer')
        def close():
            self.assertIs(control.schedule_capture, self.original_schedule)
            self.assertFalse(self.monitor.isActive())
            events.append('close')
        control.close = close
        app = SimpleNamespace(platformName=lambda: 'offscreen', exit=Mock())
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(native_smoke.QtWidgets.QApplication, 'instance', return_value=app):
            report = Path(directory)/'report.json'
            native_smoke.start_smoke(control, report, Path(directory)/'unused.png')
            value = json.loads(report.read_text(encoding='utf8'))
        self.assertEqual(value['status'], 'failed')
        self.assertIn('real Windows Qt platform', value['error'])
        self.assertEqual(events, ['nested', 'outer', 'close'])
        app.exit.assert_called_once_with(1)
        self.app.processEvents()
        self.assertEqual(self.unsolicited, [])


if __name__ == '__main__':
    unittest.main()
