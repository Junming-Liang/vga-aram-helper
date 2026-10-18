"""Startup/retry Qt regression tests with owned fakes; no Windows capture claim.

The timeout is advanced by changing the owned job start timestamp; native OCR
is never interrupted and no test waits eight real seconds.
"""
import copy
import threading
import time
from types import MethodType
import unittest
from unittest.mock import patch

from tests import test_native_capture_worker as fixture
if fixture.QtWidgets is not None:
    from native_ui import ControlWindow
from screen_capture import CapturePaused, ClientRect

@unittest.skipIf(fixture.QtWidgets is None, 'Optional Qt runtime is not installed')
class StartupRecoveryAuditTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCaptureWorkerTests.setUpClass.__func__)
    setUp=fixture.NativeCaptureWorkerTests.setUp
    wait=fixture.NativeCaptureWorkerTests.wait
    dispose_window=fixture.NativeCaptureWorkerTests.dispose_window

    def recovery_scene(self, first_capture_failure=False, held=False):
        w=self.window
        w.schedule_capture=MethodType(ControlWindow.schedule_capture,w)
        calls=[]
        entered,release=threading.Event(),threading.Event()
        self._release_events.append(release)
        names=list(w.data['augments'])[:3]
        hero=next(iter(w.data['heroes']))
        candidates=[{'name':name,'recognized_text':name,'match_method':'exact','ocr_confidence':.99,
                     'box':[[x-40,150],[x+40,150],[x+40,180],[x-40,180]]}
                    for x,name in zip((150,450,750),names)]
        class Capture:
            def capture(self,*a,**k):
                calls.append(time.monotonic())
                if first_capture_failure and len(calls)==1:
                    raise CapturePaused('Owned first-frame startup failure',reason_code='timeout')
                return b'owned-image',ClientRect(0,0,900,600)
            def rect(self,*a):return ClientRect(0,0,900,600)
            def foreground(self,*a):return True
            def retire_session(self):pass
        count=[0]
        def recognize(*a,**k):
            count[0]+=1
            if held and count[0]==1:
                entered.set()
                if not release.wait(4):raise RuntimeError('Owned audit hold did not release')
            return {'automatic_candidates':copy.deepcopy(candidates),'candidates':copy.deepcopy(candidates),
                    'image_size':{'width':900,'height':400},'hero_observation':{'hero':hero,'confident':True}}
        w.capture=Capture()
        return calls,entered,release,recognize

    def test_first_capture_error_rearms_and_confirms_on_two_new_frames(self):
        w=self.window;calls,_,_,recognize=self.recovery_scene(first_capture_failure=True)
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation)
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertEqual(len(calls),3)
        self.assertGreaterEqual(calls[1]-calls[0],.9)
        self.assertEqual(w.state.automatic_frames,2)
        self.assertFalse(w.ocr_busy)

    def test_watchdog_timeout_waits_for_exact_worker_then_rearms(self):
        w=self.window;calls,entered,release,recognize=self.recovery_scene(held=True)
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation)
            self.wait(entered.is_set)
            generation=w.state.generation
            w.ocr_started=time.monotonic()-8.1
            ControlWindow.check_target(w)
            self.assertTrue(w.ocr_timed_out)
            self.assertTrue(w.ocr_busy)
            self.assertTrue(w._capture_cancel.is_set())
            self.assertNotEqual(generation,w.state.generation)
            for _ in range(3):w.capture_tick();self.app.processEvents()
            self.assertEqual(len(calls),1)
            release.set()
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertEqual(len(calls),3)
        self.assertFalse(w.ocr_busy)

    def test_stop_start_while_old_worker_held_does_not_overlap_or_stall(self):
        w=self.window;calls,entered,release,recognize=self.recovery_scene(held=True)
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation)
            self.wait(entered.is_set)
            old_generation=w.state.generation
            from session_windows import ProcessMetadata
            w.window_list.blockSignals(True)
            w.window_list.addItem('Owned manual audit target',w.target)
            w.window_list.setCurrentIndex(w.window_list.count()-1)
            w.window_list.blockSignals(False)
            with patch('session_windows.process_metadata',return_value=ProcessMetadata('C:/owned.exe',123)):
                w.start_monitor()
            self.assertNotEqual(old_generation,w.state.generation)
            w.capture_tick()
            self.assertEqual(len(calls),1)
            release.set()
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertEqual(len(calls),3)
        self.assertFalse(w.ocr_busy)

    def test_old_callbacks_cannot_release_a_new_worker_lease(self):
        w=self.window;scheduled=[];w.schedule_capture=lambda delay=None:scheduled.append(delay)
        old=w.state.generation
        w.state.invalidate('Owned scope change')
        w._active_capture_generation=w.state.generation
        w.ocr_busy=True;w.capture_pending=True
        w.task_error('ocr','Owned delayed error',old)
        w.task_result('ocr',{},old)
        self.assertTrue(w.ocr_busy);self.assertTrue(w.capture_pending)
        self.assertEqual(scheduled,[])

    def test_four_second_stale_first_result_rearms(self):
        w=self.window;calls,_,_,recognize=self.recovery_scene()
        actual=w.task_result
        modified=[False]
        def receive(kind,value,generation):
            if kind=='ocr' and not modified[0]:
                modified[0]=True
                value=dict(value,_capturedAt=time.monotonic()-4.1)
            actual(kind,value,generation)
        # Reconnect the actual terminal Qt slot to add only the injected age.
        w.signals.result.disconnect()
        w.signals.result.connect(receive)
        with patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.capture_hidden(w.state.generation)
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertTrue(modified[0]);self.assertEqual(len(calls),3)
        self.assertFalse(w.ocr_busy)

    def test_initial_no_window_then_verified_binding_rearms_capture(self):
        from automatic_windows import AutomaticWindowPolicy
        from screen_capture import WindowInfo
        from session_windows import ProcessMetadata
        w=self.window;calls,_,_,recognize=self.recovery_scene()
        windows=[]
        game=WindowInfo(765,876,'Owned synthetic game','RiotWindowClass')
        w.capture.windows=lambda **kwargs:list(windows)
        w.target_allowed=MethodType(ControlWindow.target_allowed,w)
        w.capture_metadata=MethodType(ControlWindow.capture_metadata,w)
        w.captured_frame_current=MethodType(ControlWindow.captured_frame_current,w)
        w.live_identity_toggle.blockSignals(True);w.live_identity_toggle.setChecked(False);w.live_identity_toggle.blockSignals(False)
        create=lambda **kw:AutomaticWindowPolicy(resolver=lambda pid:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',456),verifier=lambda path:True,**kw)
        with patch('automatic_windows.AutomaticWindowPolicy',side_effect=create), patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.start_monitor()
            self.wait(lambda:not w.discovery_busy)
            self.assertIsNone(w.target);self.assertTrue(w.state.running)
            self.assertTrue(w.monitor.isActive());self.assertEqual(calls,[])
            windows.append(game);w.queue_discovery(force=True)
            self.wait(lambda:w.target==game)
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertEqual(len(calls),2)

    def test_first_discovery_worker_error_retries_on_watchdog(self):
        from automatic_windows import AutomaticWindowPolicy
        from screen_capture import WindowInfo
        from session_windows import ProcessMetadata
        w=self.window;calls,_,_,recognize=self.recovery_scene()
        game=WindowInfo(765,876,'Owned synthetic game','RiotWindowClass')
        w.capture.windows=lambda **kwargs:[game]
        w.target_allowed=MethodType(ControlWindow.target_allowed,w)
        w.capture_metadata=MethodType(ControlWindow.capture_metadata,w)
        w.captured_frame_current=MethodType(ControlWindow.captured_frame_current,w)
        w.live_identity_toggle.blockSignals(True);w.live_identity_toggle.setChecked(False);w.live_identity_toggle.blockSignals(False)
        policy=AutomaticWindowPolicy(resolver=lambda pid:ProcessMetadata(r'C:\Riot\Game\League of Legends.exe',456),verifier=lambda path:True)
        discover=policy.discover
        count=[0]
        def fault_once(windows):
            count[0]+=1
            if count[0]==1:raise RuntimeError('Owned discovery startup fault')
            return discover(windows)
        policy.discover=fault_once
        with patch('automatic_windows.AutomaticWindowPolicy',return_value=policy), patch('hero_recognition.recognize_frame',side_effect=recognize):
            w.start_monitor()
            self.wait(lambda:not w.discovery_busy)
            self.assertIsNone(w.target);self.assertTrue(w.state.running)
            self.assertTrue(w.monitor.isActive());self.assertEqual(calls,[])
            w.last_window_discovery=0
            ControlWindow.check_target(w)
            self.wait(lambda:w.target==game)
            self.wait(lambda:w.state.confirmed)
            w.monitor.stop()
        self.assertEqual(count[0],2);self.assertEqual(len(calls),2)

    def test_old_serial_result_cannot_release_current_pending_capture(self):
        w=self.window;scheduled=[];w.schedule_capture=lambda delay=None:scheduled.append(delay)
        w._capture_serial=20;w._active_capture_generation=w.state.generation
        w.ocr_busy=True;w.capture_pending=True
        w.task_result('ocr',{'_captureSerial':19},w.state.generation)
        self.assertTrue(w.ocr_busy);self.assertTrue(w.capture_pending)
        self.assertEqual(w._capture_serial,20);self.assertEqual(scheduled,[])

if __name__=='__main__':unittest.main()

