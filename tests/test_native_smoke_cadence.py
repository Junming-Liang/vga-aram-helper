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
            client_phase=lambda: False, client_selection_reference=lambda: None,
            current_partial_names=lambda: ('', '', ''),
            overlay=SimpleNamespace(set_rechecking=lambda value: None),
            captured_frame_current=lambda value: False,
            refresh_status_badge=lambda: None)
        self.control.discard_stale_capture_callback = MethodType(ControlWindow.discard_stale_capture_callback, self.control)
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
        control.debug_log = SimpleNamespace(sample=lambda *args, **kwargs: None)
        control.overlay.click_through = True
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
                     result_dispatch=SimpleNamespace(restore=Mock()), observed_error=object())
        exec(compile(ast.Module(body=[cleanup], type_ignores=[]),
                     native_smoke.__file__, 'exec'), scope)
        scope['cleanup']()
        scope['result_dispatch'].restore.assert_called_once_with()
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


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class OwnedCapturePreflightTests(unittest.TestCase):
    def fixture(self, ready):
        self.clock=0.;self.events=[];self.evidence=[]
        def pump(): self.events.append('pump');self.clock+=.01
        def capture(target): self.events.append('capture');return b'owned', 'rect'
        overlay=SimpleNamespace(hide=Mock(),isVisible=lambda:False,winId=lambda:12,hidden_settle_ms=lambda:0)
        self.control=SimpleNamespace(closed=False,overlay=overlay,capture=SimpleNamespace(
            prepare_capture_mode=Mock(side_effect=ready),capture=Mock(side_effect=capture),
            u=SimpleNamespace(IsWindowVisible=lambda hwnd:False)))
        self.app=SimpleNamespace(processEvents=pump)
        return patch.object(native_smoke,'time',SimpleNamespace(monotonic=lambda:self.clock,sleep=lambda _:None))

    def test_waits_before_one_capture_and_timestamp_begins_after_readiness(self):
        with self.fixture([False,False,True]):
            pixels,rect,stamp=native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence)
        self.assertEqual((pixels,rect,stamp),(b'owned','rect',.02))
        self.assertEqual(self.events,['pump','pump','capture'])
        self.control.capture.capture.assert_called_once_with('target')
        self.assertEqual(self.evidence,[{'ready_before_capture':True,'hidden_settled':True,'polls':3,'wait_ms':20.}])

    def test_zero_elapsed_clock_tick_still_proves_readiness_order(self):
        with self.fixture([False,False,True]):
            # Several event-pump iterations may share one coarse Windows clock tick.
            self.app.processEvents=lambda:self.events.append('pump')
            native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence)
        self.assertEqual(self.events,['pump','pump','capture'])
        self.control.capture.capture.assert_called_once_with('target')
        self.assertEqual(self.evidence[0]['polls'],3)
        self.assertEqual(self.evidence[0]['wait_ms'],0.)

    def test_permanent_pending_has_deadline_without_capture_or_owner_reset(self):
        with self.fixture(lambda _:False),self.assertRaisesRegex(RuntimeError,'bounded deadline'):
            native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence,timeout=.025)
        self.control.capture.capture.assert_not_called();self.assertEqual(self.evidence,[])
        self.assertLessEqual(self.clock,.03)

    def test_readiness_error_and_capture_error_are_not_retried(self):
        error=RuntimeError('owned failure')
        for phase in ('readiness','capture'):
            with self.subTest(phase=phase),self.fixture(lambda _:True):
                if phase=='readiness':self.control.capture.prepare_capture_mode.side_effect=error
                else:self.control.capture.capture.side_effect=error
                with self.assertRaisesRegex(RuntimeError,'owned failure'):
                    native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence)
                self.assertEqual(self.control.capture.capture.call_count,0 if phase=='readiness' else 1)
                self.assertEqual(self.events,[]);self.assertEqual(self.evidence,[])

    def test_hidden_settle_and_closed_scope_prevent_early_capture(self):
        with self.fixture(lambda _:True):
            self.control.overlay.hidden_settle_ms=lambda:20 if self.clock<.02 else 0
            native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence)
        self.assertEqual(self.events,['pump','pump','capture'])
        with self.fixture(lambda _:True),self.assertRaisesRegex(RuntimeError,'stopped'):
            self.control.closed=True
            native_smoke._owned_hidden_capture(self.control,'target',app=self.app,evidence=self.evidence)
        self.control.capture.capture.assert_not_called()



from tests import test_persistent_capture_adapter as adapter_fixtures

@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class RealAdapterPreflightTests(adapter_fixtures.AdapterFixture, unittest.TestCase):
    def test_pending_retirement_blocks_direct_capture_then_preflight_waits_for_real_barrier(self):
        import threading
        from wgc_capture import WgcError
        self.capture()  # Establish an actual production adapter owner with a fake transport.
        old=self.sessions[0];release=threading.Event();entered=threading.Event();closed=threading.Event()
        def close():
            entered.set()
            if not release.wait(2):raise RuntimeError('Owned close was not released')
            old._close()
            closed.set()
        old.close.side_effect=close
        self.addCleanup(release.set)
        self.adapter.retire()
        self.assertTrue(entered.wait(1))
        with self.assertRaises(WgcError) as error:self.adapter.check_ready()
        self.assertEqual(error.exception.status,'cleanup-pending')
        calls=[];pumps=[]
        def capture_once(target):
            self.assertTrue(release.is_set());self.assertTrue(closed.is_set())
            self.assertFalse(self.adapter.cleanup_pending)
            calls.append(target)
            return self.adapter.capture(target,self.rect,(0,0,80,60),cancelled=lambda:False),self.rect
        def pump():
            pumps.append(True)
            self.assertEqual(calls,[])
            if len(pumps)==2:release.set()
        control=SimpleNamespace(closed=False,
            overlay=SimpleNamespace(hide=Mock(),isVisible=lambda:False,winId=lambda:101,hidden_settle_ms=lambda:0),
            capture=SimpleNamespace(prepare_capture_mode=self.adapter.prepare_capture_mode,capture=capture_once,
                u=SimpleNamespace(IsWindowVisible=lambda hwnd:False)))
        evidence=[]
        pixels,rect,stamp=native_smoke._owned_hidden_capture(control,self.target,
            app=SimpleNamespace(processEvents=pump),evidence=evidence)
        self.assertIs(pixels,self.image);self.assertEqual(rect,self.rect)
        self.assertEqual(calls,[self.target]);self.assertGreaterEqual(len(pumps),2)
        self.assertEqual(self.factory.call_count,2)
        self.assertTrue(old._transport.revoked.is_set());self.assertFalse(self.adapter.cleanup_pending)
        # Windows monotonic clock resolution can round a real short wait to zero.
        # Prove ordering/ownership directly instead of inferring it from duration.
        self.assertEqual(evidence[0]['polls'],len(pumps)+1)
        self.assertGreaterEqual(evidence[0]['polls'],3)



class DutyModeWaitSchedulingTests(unittest.TestCase):
    def test_readiness_delay_runs_only_before_first_acquisition(self):
        from native_smoke import _schedule_duty_mode_wait
        calls=[];queued=[]
        trace=SimpleNamespace(finished=False,error=None,capture_count=0);active=[trace]
        control=SimpleNamespace(_mode_wait_started=100.,capture_pending=False,ocr_busy=False,capture_tick=lambda:calls.append('capture'))
        schedule=lambda delay,callback:queued.append((delay,callback))
        run=lambda fn:fn()
        _schedule_duty_mode_wait(control,active,schedule,run,50)
        self.assertEqual(queued[0][0],50);self.assertEqual(calls,[])
        queued.pop()[1]();self.assertEqual(calls,['capture'])
        trace.capture_count=1
        _schedule_duty_mode_wait(control,active,schedule,run,50);self.assertEqual(queued,[])
    def test_late_readiness_timer_never_retries_failed_or_replaced_case(self):
        from native_smoke import _schedule_duty_mode_wait
        for mutation in ('finished','error','capture_count','replaced','busy','pending','ready'):
            with self.subTest(mutation=mutation):
                calls=[];queued=[];trace=SimpleNamespace(finished=False,error=None,capture_count=0);active=[trace]
                control=SimpleNamespace(_mode_wait_started=100.,capture_pending=False,ocr_busy=False,capture_tick=lambda:calls.append(True))
                _schedule_duty_mode_wait(control,active,lambda d,f:queued.append(f),lambda f:f(),50)
                if mutation=='replaced':active[0]=SimpleNamespace()
                elif mutation=='busy':control.ocr_busy=True
                elif mutation=='pending':control.capture_pending=True
                elif mutation=='ready':control._mode_wait_started=None
                else:setattr(trace,mutation,True)
                queued[0]();self.assertEqual(calls,[])


@unittest.skipIf(QtWidgets is None,'Optional Qt runtime is not installed')
class ActualBadgeVisibilityReceiptTests(unittest.TestCase):
    def test_hidden_parent_never_reports_relatively_visible_children(self):
        from native_smoke import visible_badge_slots
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        parent=QtWidgets.QWidget();self.addCleanup(parent.close)
        parent._badge_widgets=[QtWidgets.QWidget(parent) for _ in range(3)]
        parent.show();app.processEvents()
        self.assertEqual(visible_badge_slots(parent,True),[1,2,3])
        parent._badge_widgets[0].hide();parent._badge_widgets[1].hide()
        self.assertEqual(visible_badge_slots(parent,True),[3])
        parent.hide();app.processEvents()
        self.assertTrue(parent._badge_widgets[2].isVisibleTo(parent))
        self.assertEqual(visible_badge_slots(parent,False),[])
        self.assertEqual(visible_badge_slots(parent,True),[])
        parent.show();app.processEvents()
        self.assertEqual(visible_badge_slots(parent,False),[])
        self.assertEqual(visible_badge_slots(parent,True),[3])


if __name__ == '__main__':
    unittest.main()
