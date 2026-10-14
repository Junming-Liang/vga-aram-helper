"""Portable probe regressions only; owned fake capture is NOT Windows evidence.

The native smoke separately calls this same diagnostic with real HWNDs, actual
capture/helper processes, and the concrete PortraitMatcher plus local OCR.
"""
import gc
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
    from native_smoke import OverlayDutyTrace, start_overlay_duty_probe
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
                finished=[];errors=[];report={};checks=[]
                def guarded(fn):
                    try:fn()
                    except Exception as exc:errors.append(exc)
                with patch('session_windows.process_metadata',return_value=object()):
                    start_overlay_duty_probe(control,app=self.app,u=u,paint_mock=paint,report=report,checks=checks,
                                             save=lambda:None,run=guarded,done=lambda:finished.append(True))
                    self.wait(lambda:finished or errors,seconds=45)
                if errors:raise errors[0]
                self.assertTrue(report['overlay_duty_cycle_passed'])
                rows=report['overlay_duty_cycle']['cases']
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
