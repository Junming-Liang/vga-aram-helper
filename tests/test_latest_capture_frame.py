import threading
import time
import unittest
from latest_capture_frame import LatestCaptureFrame,CapturedFrame,MAX_FRAME_BYTES

class LatestCaptureFrameTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.buffer=LatestCaptureFrame(clock=lambda:self.now)
        self.addCleanup(self.buffer.close)
    def packet(self,value=b'png',age=.2):return CapturedFrame(value,('rect',),self.now-age,self.now)
    def wait(self):
        until=time.monotonic()+2
        while self.buffer.busy and time.monotonic()<until:time.sleep(.001)
        self.assertFalse(self.buffer.busy)
    def test_latest_only_preserves_acquisition_timestamp(self):
        first=self.packet(b'one');self.buffer.submit(('scope',),lambda _:first);self.wait()
        self.buffer.submit(('scope',),lambda _:self.packet(b'two'));self.wait()
        frame=self.buffer.take(('scope',));self.assertEqual(frame.image,b'two');self.assertEqual(frame.captured_at,99.8)
        self.assertIsNone(self.buffer.take(('scope',)))
    def test_no_parallel_capture_or_early_consume(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def acquire(cancelled):entered.set();release.wait(1);return self.packet()
        self.assertTrue(self.buffer.submit('scope',acquire));self.assertTrue(entered.wait(1))
        self.assertFalse(self.buffer.submit('scope',lambda _:self.packet()))
        self.assertIsNone(self.buffer.take('scope'));release.set();self.wait()
        self.assertIsNotNone(self.buffer.take('scope'))
    def test_clear_revokes_inflight_and_prevents_late_store(self):
        entered=threading.Event();release=threading.Event();cancelled_seen=[];self.addCleanup(release.set)
        def acquire(cancelled):entered.set();release.wait(1);cancelled_seen.append(cancelled());return self.packet()
        self.buffer.submit('old',acquire);self.assertTrue(entered.wait(1));self.buffer.clear();release.set();self.wait()
        self.assertEqual(cancelled_seen,[True]);self.assertIsNone(self.buffer.take('old'));self.assertIsNone(self.buffer.take_failure())
    def test_scope_generation_epoch_and_window_changes_never_reuse(self):
        for scope in (('generation',2),('window',2),('epoch',2)):
            self.buffer.submit(('original',1),lambda _:self.packet());self.wait();self.assertIsNone(self.buffer.take(scope))
    def test_expiry_and_future_frames_do_not_get_new_timestamp(self):
        self.buffer.submit('s',lambda _:self.packet(age=.9));self.wait();self.assertIsNone(self.buffer.take('s'))
        self.buffer.submit('s',lambda _:CapturedFrame(b'x',None,101.,101.));self.wait();self.assertEqual(self.buffer.take_failure(),'s')
    def test_failure_drops_older_slot_and_contains_no_exception_text(self):
        self.buffer.submit('s',lambda _:self.packet());self.wait()
        def fail(_):raise RuntimeError('private path')
        self.buffer.submit('s',fail);self.wait();self.assertIsNone(self.buffer.take('s'));self.assertEqual(self.buffer.take_failure(),'s')
        self.assertIsNone(self.buffer.take_failure())
    def test_retirement_barrier_waits_without_cancelling_producer(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        cancelled_seen=[]
        def acquire(cancelled):
            entered.set();release.wait(1);cancelled_seen.append(cancelled());return self.packet()
        self.buffer.submit('s',acquire);self.assertTrue(entered.wait(1))
        self.assertFalse(self.buffer.prepare_retirement())
        release.set();self.wait()
        self.assertEqual(cancelled_seen,[False])
        self.assertTrue(self.buffer.prepare_retirement())
        self.assertIsNone(self.buffer.take('s'));self.assertIsNone(self.buffer.take_failure())
    def test_retirement_barrier_preserves_failure_until_controller_consumes_it(self):
        def fail(_):raise RuntimeError('owned real failure')
        self.buffer.submit('s',fail);self.wait()
        self.assertFalse(self.buffer.prepare_retirement())
        self.assertEqual(self.buffer.take_failure(),'s')
        self.assertTrue(self.buffer.prepare_retirement())
    def test_close_is_nonblocking_and_revokes_future_submissions(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def acquire(cancelled):entered.set();release.wait(1);return self.packet()
        self.buffer.submit('s',acquire);self.assertTrue(entered.wait(1))
        before=time.monotonic();self.buffer.close();self.assertLess(time.monotonic()-before,.1)
        self.assertFalse(self.buffer.submit('s',acquire));release.set();self.wait();self.assertIsNone(self.buffer.take('s'))
    def test_bounded_packet_rejects_empty_or_oversize_or_nonbytes(self):
        for image in (b'',bytearray(b'private'),b'x'*(MAX_FRAME_BYTES+1)):
            self.buffer.submit('s',lambda _,image=image:self.packet(image));self.wait()
            self.assertIsNone(self.buffer.take('s'));self.assertEqual(self.buffer.take_failure(),'s')

if __name__=='__main__':unittest.main()
