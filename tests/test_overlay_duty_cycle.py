"""Portable probe regressions only; owned fake capture is NOT Windows evidence.

The native smoke separately calls this same diagnostic with real HWNDs, actual
capture/helper processes, and the concrete PortraitMatcher plus local OCR.
"""
import gc
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import isValid
    from native_smoke import OverlayDutyTrace, _start_overlay_duty_mode
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Optional Qt runtime is not installed')
class DutyTraceTests(unittest.TestCase):
    def test_sampled_durations_do_not_claim_an_old_executable_baseline(self):
        now=[20.]
        trace=OverlayDutyTrace('owned',clock=lambda:now[0])
        trace.sample(True)
        now[0]=20.01;trace.sample(False,capturing=True);trace.mark('capture_start')
        now[0]=20.11;trace.sample(False,capturing=True);trace.mark('capture_return')
        now[0]=20.12;trace.sample(True)
        now[0]=20.82;trace.mark('final');trace.sample(True)
        value=trace.summary()
        self.assertEqual(value['sampled_hidden_ms'],110)
        self.assertEqual(value['sampled_visible_ms'],710)
        self.assertEqual(value['sampled_inference_visible_ms'],700)
        self.assertEqual(value['capture_visible_samples'],0)
        self.assertEqual(value['capture_samples'],2)
        self.assertEqual(value['max_sample_gap_ms'],700)
        self.assertEqual(value['old_hide_until_final_policy_counterfactual_ms'],820)
        self.assertIn('not a measured baseline executable',value['comparison_scope'])

    def test_pre_capture_visibility_is_not_counted_as_early_restoration(self):
        now=[0.];trace=OverlayDutyTrace('changed_hud',clock=lambda:now[0])
        trace.sample(True)
        now[0]=.004;trace.sample(False)
        now[0]=.1;trace.mark('capture_return');trace.sample(False)
        now[0]=.8;trace.mark('final');trace.sample(False)
        value=trace.summary()
        self.assertEqual(value['sampled_visible_ms'],4)
        self.assertEqual(value['sampled_inference_visible_ms'],0)

    def test_an_actual_visible_acquisition_sample_cannot_disappear_in_summary(self):
        now=[0.];trace=OverlayDutyTrace('bad_capture',clock=lambda:now[0])
        trace.sample(False,capturing=True)
        now[0]=.1;trace.sample(True,capturing=True)
        now[0]=.2;trace.mark('capture_return');trace.mark('final');trace.sample(False)
        value=trace.summary()
        self.assertEqual(value['capture_visible_samples'],1)
        self.assertEqual(value['capture_samples'],2)
    def test_v1_cleanup_accepts_only_documented_cleared_stdin(self):
        from native_smoke import _duty_one_shot_process_closed
        process=SimpleNamespace(poll=lambda:0,stdin=None,stdout=SimpleNamespace(closed=True),stderr=SimpleNamespace(closed=True))
        self.assertTrue(_duty_one_shot_process_closed(process))
        process.stdin=SimpleNamespace(closed=True);self.assertTrue(_duty_one_shot_process_closed(process))
        process.stdin.closed=False;self.assertFalse(_duty_one_shot_process_closed(process));process.stdin=None
        for key in ('stdout','stderr'):
            original=getattr(process,key);setattr(process,key,None)
            self.assertFalse(_duty_one_shot_process_closed(process));setattr(process,key,original)
            original.closed=False;self.assertFalse(_duty_one_shot_process_closed(process));original.closed=True
        process.poll=lambda:None;self.assertFalse(_duty_one_shot_process_closed(process))

    def test_eventual_stop_cleanup_requires_process_pipes_job_and_owner(self):
        from native_smoke import _duty_session_cleanup
        import threading
        def event():
            result=threading.Event();result.set();return result
        owner=SimpleNamespace(revoked=event(),close_done=event(),call_done=event())
        process=SimpleNamespace(pid=22,poll=lambda:1,stdin=SimpleNamespace(closed=True),
            stdout=SimpleNamespace(closed=True),stderr=SimpleNamespace(closed=True))
        transport=SimpleNamespace(process=process,generation=4,revoked=event(),io_done=event(),stderr_done=event(),
            ready_for_replacement=event(),job=SimpleNamespace(handle=None),job_closed=True,termination_requested_while_alive=True,diagnostic=bytearray())
        capture=SimpleNamespace(cleanup_pending=False)
        receipt=dict(helper_pid=22,helper_created=333,session_generation=4)
        def observed():
            with patch('native_smoke._duty_process_created',return_value=333):
                return _duty_session_cleanup(capture,owner,transport,receipt,observed_ms=800.)
        self.assertIsNotNone(observed())
        for obj,key in ((owner,'revoked'),(owner,'close_done'),(owner,'call_done'),(transport,'revoked'),
                        (transport,'io_done'),(transport,'stderr_done'),(transport,'ready_for_replacement')):
            getattr(obj,key).clear();self.assertIsNone(observed());getattr(obj,key).set()
        process.poll=lambda:None;self.assertIsNone(observed());process.poll=lambda:1
        for key in ('stdin','stdout','stderr'):
            getattr(process,key).closed=False;self.assertIsNone(observed());getattr(process,key).closed=True
        transport.job.handle=123;self.assertIsNone(observed());transport.job.handle=None
        transport.job_closed=False;self.assertIsNone(observed());transport.job_closed=True
        capture.cleanup_pending=True;self.assertIsNone(observed());capture.cleanup_pending=False
        process.pid=23
        with self.assertRaisesRegex(AssertionError,'different helper'):observed()

    def test_full_two_mode_report_with_actual_widget_layout_fits_original_budget(self):
        # Real Qt layout, synthetic report envelope. This is a budget regression,
        # not an observed Windows capture/process acceptance report.
        from engine import load_data
        from native_ui import Overlay
        from native_state import display_cards
        from native_smoke import inspect_smoke_layout
        from screen_capture import ClientRect
        from synthetic_vision import configure_data
        from tests.test_native_packaging import overlay_duty_fixture,NativePackagingTests
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        data=load_data(Path(__file__).resolve().parents[1]/'fixtures/demo.json');configure_data(data)
        overlay=Overlay();names=['星火共鸣','晶盾回路','风步微光']
        try:
            overlay.set_cards('星火术士（演示）',display_cards(data,'星火术士（演示）',names),
                '2026-10-14','数据包 演示 / 游戏资料 演示','英雄/候选连续高置信自动识别')
            overlay._fit_layout(ClientRect(20,20,960,600),1);overlay.show();app.processEvents()
            value=overlay_duty_fixture();value.update(NativePackagingTests.geometry_fixture())
            value.update(overlay_layout_widgets=inspect_smoke_layout(overlay),
                status='failed',error='X'*2000,error_traceback='T'*4000,error_type='AssertionError',
                checks=['Completed exact owned-native diagnostic check '+str(i)+' x'*80 for i in range(25)],
                screenshot='C:/owned-synthetic-report/windows-native-scale200-overlay.png',
                screenshot_method='Qt QWidget.grab of our synthetic mock and overlay only, composited locally; OS capture/OCR separately asserted',
                hero_transition_observations=[dict(hero='星火术士（演示）',confident=True)]*2)
            duty=value['overlay_duty_cycle']
            # Real Windows handles/creation/QPC values are wider than tiny fixture IDs.
            for section in (duty,duty['baseline']):
                for row in section['cases']:
                    for phase in row['phases']:
                        phase['window_identity']=[4294967295,4294967295,'Q'*256]
                        phase['current_window_identity']=phase['window_identity']
                        for state in ('state_before','state_at_phase'):
                            for key in phase[state]:phase[state][key]=1000000000.123456
            duty['active_mode']='persistent';duty['active_case']=copy.deepcopy(duty['cases'][-1])
            duty['active_case']['phase_state']='stop-cleanup'
            encoded=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            self.assertGreater(len(encoded),100_000)
            self.assertLessEqual(len(encoded),128*1024)
        finally:
            overlay.close();overlay.deleteLater()
            QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete);app.processEvents()


@unittest.skipIf(QtWidgets is None or importlib.util.find_spec('cv2') is None or importlib.util.find_spec('rapidocr') is None,
                 'Optional Qt, OpenCV and local OCR runtime are not installed')
class DutyProbeOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def wait(self,predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            self.app.processEvents()
            if predicate():return
            time.sleep(.003)
        self.fail('Owned portable duty fixture did not finish')

    def test_actual_matcher_ocr_phases_and_stop_with_explicit_fake_capture(self):
        from PIL import Image
        from engine import load_data
        from hero_recognition import PortraitMatcher
        from local_ocr import LocalOCR
        from native_ui import ControlWindow
        from screen_capture import CaptureUnavailable,ClientRect,WindowInfo
        from synthetic_vision import portraits,configure_data,frame,encoded
        import hero_recognition
        import wgc_capture
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            with patch('native_ui.Win32Capture',side_effect=CaptureUnavailable('owned portable fixture')):
                control=ControlWindow(lambda:{'data':load_data(root/'fixtures/demo.json')},state_dir=Path(directory),
                    current_executable=Path('/unused.exe'),current_version='test',frozen=False,enable_updates=False)
            original_recognize=hero_recognition.recognize_frame;original_popen=wgc_capture.subprocess.Popen
            try:
                self.wait(lambda:control.data is not None)
                control.watchdog.stop();control.monitor.stop()
                configure_data(control.data);bank=portraits();pixels=[None]
                control.hero_matcher=PortraitMatcher(bank,control.data['heroes'])
                control.ocr=LocalOCR()
                def paint(key='9001',*,gray=False,changed_roi=False):
                    portrait=bank[key].convert('L').convert('RGB') if gray else bank[key]
                    canvas=frame(portrait,width=960,height=600)
                    cards=Image.open(root/'fixtures/auto-scene.png').convert('RGB').resize((960,600),Image.Resampling.LANCZOS)
                    canvas.paste(cards.crop((0,0,960,480)),(0,0))
                    if changed_roi:canvas.paste((75,60,85),(192,162,204,174))
                    pixels[0]=encoded(canvas)
                paint()
                u=SimpleNamespace(IsWindowVisible=lambda hwnd:control.overlay.isVisible())
                rect=ClientRect(20,20,960,600)
                class OwnedCapture:
                    last_backend='owned-portable-fixture'
                    def capture(self,*args,**kwargs):
                        time.sleep(.03)
                        return pixels[0],rect
                    def rect(self,target):return rect
                    def foreground(self,target):return True
                    def validate_compositor(self,target,expected):
                        if control.overlay.isVisible():raise AssertionError('Compositor proof must precede overlay restoration')
                        return rect
                capture=OwnedCapture();capture.u=u;control.capture=capture
                # Overlay itself remains a real Qt widget; this portable fixture
                # intentionally has no native positioning or OS capture claim.
                control.target=WindowInfo(123,456,'Owned portable fixture','OwnedFixture')
                control.target_allowed=lambda:True;control.capture_metadata=lambda:None
                control.state.start(control.target.identity)
                finished=[];errors=[];report={'mode':'one-shot','cases':[]}
                def guarded(fn):
                    try:fn()
                    except Exception as exc:errors.append(exc)
                with patch('session_windows.process_metadata',return_value=object()):
                    _start_overlay_duty_mode(control,app=self.app,u=u,paint_mock=paint,mode_report=report,
                                             save=lambda:None,run=guarded,done=lambda:finished.append(True))
                    self.wait(lambda:finished or errors,seconds=45)
                if errors:raise errors[0]
                # Portable plumbing never sets the full two-mode native acceptance flag.
                self.assertNotIn('overlay_duty_cycle_passed',report)
                rows=report['cases']
                self.assertEqual([row['name'] for row in rows],['unchanged','changed_roi','changed_hud','unknown_hud','stop_late'])
                for row in rows:
                    self.assertEqual(row['capture_backend'],'owned-portable-fixture')
                    self.assertEqual(row['capture_count'],1)
                    self.assertEqual(row['max_capture_concurrency'],1)
                    self.assertEqual(row['capture_visible_samples'],0)
                    self.assertEqual(row['qt_show_events_during_capture'],0)
                    self.assertEqual(row['helper_count'],0)
                    self.assertEqual(row['helper_exit_codes'],[])
                    self.assertTrue(all(phase['state_before']==phase['state_at_phase'] for phase in row['phases']))
                self.assertGreaterEqual(rows[0]['sampled_inference_visible_ms'],500)
                self.assertEqual(rows[1]['sampled_inference_visible_ms'],0)
                self.assertEqual(rows[2]['sampled_inference_visible_ms'],0)
                self.assertEqual(rows[3]['sampled_inference_visible_ms'],0)
                self.assertTrue(rows[1]['final_confirmed'])
                self.assertTrue(all(phase['candidate_roi_sha256']!=phase['accepted_candidate_roi_sha256'] and phase['hud_input_sha256']==phase['accepted_hud_input_sha256'] for phase in rows[1]['phases']))
                self.assertTrue(rows[4]['late_final_discarded'])
                self.assertFalse(rows[4]['final_qt_visible'])
                self.assertFalse(rows[4]['final_native_visible'])
                self.assertTrue(control.state.confirmed)
                self.assertEqual(control.state.automatic_frames,2)
                self.assertIs(hero_recognition.recognize_frame,original_recognize)
                self.assertIs(wgc_capture.subprocess.Popen,original_popen)
                self.assertLess(len(json.dumps(report).encode()),100_000)
            finally:
                cleanup=getattr(control,'_smoke_duty_cleanup',None)
                if cleanup:cleanup()
                control.capture=None;control.close()
                self.wait(lambda:not control._workers,seconds=5)
                overlay=control.overlay;overlay.deleteLater();control.deleteLater()
                QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)
                self.app.processEvents();self.assertFalse(isValid(overlay));self.assertFalse(isValid(control))
                gc.collect()


if __name__=='__main__':unittest.main()
