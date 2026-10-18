"""Real Qt timers and OCR on owned moving frames with injected bounded latency.

Capture is synthetic, so these are not Windows compositor/gameplay evidence.
"""
import unittest,time
from contextlib import nullcontext
from unittest.mock import patch
from tests import test_animated_augment_rounds as f

@unittest.skipUnless(f.QtWidgets is not None and f.OCR_AVAILABLE,
                     'Optional Qt/local OCR dependencies are not installed')
class SlowCadence(unittest.TestCase):
    setUpClass=classmethod(f.AnimatedAugmentRoundTests.setUpClass.__func__)
    setUp=f.AnimatedAugmentRoundTests.setUp
    wait=f.AnimatedAugmentRoundTests.wait
    dispose_window=f.AnimatedAugmentRoundTests.dispose_window
    record_result=f.AnimatedAugmentRoundTests.record_result
    record_error=f.AnimatedAugmentRoundTests.record_error
    start_frame=f.AnimatedAugmentRoundTests.start_frame
    finish_frame=f.AnimatedAugmentRoundTests.finish_frame
    observe=f.AnimatedAugmentRoundTests.observe
    assert_confirmed=f.AnimatedAugmentRoundTests.assert_confirmed
    def scenario(self, legacy=False, work=1.45, cycles=3, tail_work=None):
        from native_ui import ControlWindow
        from PySide6 import QtCore
        w=self.window
        with patch('native_ui.time',time), (patch('capture_cadence.next_capture_delay',side_effect=lambda base,age,timings: min(base,max(0,int((4-age)*1000)-80)) if age is not None and 0<=age<=4 else base) if legacy else nullcontext()):
            w.ocr_reuse.clock=time.monotonic
            cap=w.capture.capture
            def slow_capture(*args,**kwargs):time.sleep(.35);return cap(*args,**kwargs)
            w.capture.capture=slow_capture
            recog=w.ocr.recognize
            def slow_recog(*args,**kwargs):
                t=time.monotonic();result=recog(*args,**kwargs);time.sleep(max(0,work-(time.monotonic()-t)));return result
            w.ocr.recognize=slow_recog
            w.capture.can_request_visible_overlay=True;w.capture.visible_capture_status='eligible';w.capture.prepare_capture_mode=lambda visible:True
            self.observe((0,1,2),0);self.observe((0,1,2),1);self.assert_confirmed((0,1,2))
            ages=[];timeline=[]
            def on_result(kind,value,gen):
                if kind=='ocr':
                    ages.append(time.monotonic()-value['_capturedAt'])
                    timeline.append(dict(event='result',captured=value['_capturedAt'],completed=value['_completedAt'],received=time.monotonic(),visible=w.overlay.isVisible()))
            w.signals.result.connect(on_result)
            hides=[]
            original_hide=w.overlay.hide
            def hide(reason='unknown'):
                if w.overlay.isVisible():
                    hides.append((reason,round(time.monotonic()-w.last_observation,3)))
                    timeline.append(dict(event='hide',reason=reason,at=time.monotonic(),deadline=w.last_observation+4))
                return original_hide(reason)
            with patch.object(w.overlay,'hide',side_effect=hide):
                w.watchdog.start()
                for phase in range(2,2+cycles):
                    if phase==3 and tail_work is not None:work=tail_work
                    # Production decides idle cadence; stop timer so fixture owns only payload.
                    ControlWindow.schedule_capture(w);delay=w.monitor.interval();w.monitor.stop()
                    timeline.append(dict(event='schedule',delay_ms=delay,at=time.monotonic(),deadline=w.last_observation+4))
                    until=time.monotonic()+delay/1000
                    while time.monotonic()<until:self.app.processEvents();time.sleep(.005)
                    previous=len(self.results);self.start_frame((0,1,2),phase)
                    self.wait(lambda:len(self.results)>previous and not w.ocr_busy and not w._workers)
                w.watchdog.stop()
            return hides,ages,timeline
    def test_fixed_idle_reproduces_repeated_expiry(self):
        hides,ages,timeline=self.scenario(legacy=True)
        print('LEGACY_CADENCE',timeline,flush=True)
        self.assertGreaterEqual(len(hides),2)
        self.assertTrue(all(age>=4 for reason,age in hides))
    def test_measured_budget_keeps_same_latency_frames_visible(self):
        hides,ages,timeline=self.scenario()
        print('BUDGET_CADENCE',timeline,flush=True)
        self.assertEqual(hides,[])
        self.assertTrue(all(1.7<age<4 for age in ages))
        self.assertTrue(all(row['delay_ms']>=50 for row in timeline if row['event']=='schedule'))
    def test_work_exceeding_refresh_budget_still_expires(self):
        hides,ages,timeline=self.scenario(work=1.9,cycles=2)
        self.assertTrue(hides)
        self.assertTrue(all(age>=4 for reason,age in hides))
    def test_unpredicted_long_tail_never_keeps_expired_grade(self):
        hides,ages,timeline=self.scenario(tail_work=4.1,cycles=2)
        self.assertTrue(hides)
        self.assertGreater(ages[-1],4)
        self.assertFalse(self.window.state.confirmed)
        self.assertFalse(self.window.overlay.isVisible())
        self.assertTrue(all(age>=4 for reason,age in hides))

if __name__=='__main__':unittest.main()
