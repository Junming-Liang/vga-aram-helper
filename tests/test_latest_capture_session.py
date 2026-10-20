"""Real wrapper watchdog with synthetic owned I/O; no Windows border claim."""
import io
import time
import unittest
from latest_capture_frame import LatestCaptureFrame,CapturedFrame
import test_wgc_session_protocol as fixtures
ROI=fixtures.ROI

class SlowConsumerSessionTests(unittest.TestCase):
    setUp=fixtures.WrapperTests.setUp
    def test_serial_idle_expires_while_consumer_would_still_be_busy(self):
        self.capture.capture(self.target,self.rect,ROI)
        self.assertTrue(self.capture._transport.ready_for_replacement.wait(2))
        self.assertEqual(self.capture._transport.failure.status,'timeout')
        self.assertGreater(self.process.kills,0)
    def test_bounded_latest_capture_keeps_same_session_alive_without_advancing_observation(self):
        buffer=LatestCaptureFrame();self.addCleanup(buffer.close)
        scope=('owned',self.target.identity,self.target_metadata)
        observation_at=time.monotonic()
        self.capture.capture(self.target,self.rect,ROI)
        transport=self.capture._transport
        # Test fixture scales the independent idle lease to .4s. Keep the
        # consumer blocked for two leases while valid requests continue.
        end=time.monotonic()+.85;requests=0
        def acquire(cancelled):
            start=time.monotonic()
            image=self.capture.capture(self.target,self.rect,ROI,cancelled=cancelled)
            out=io.BytesIO();image.save(out,format='PNG')
            return CapturedFrame(out.getvalue(),self.rect,start,time.monotonic())
        while time.monotonic()<end:
            self.assertTrue(buffer.submit(scope,acquire));requests+=1
            deadline=time.monotonic()+1
            while buffer.busy and time.monotonic()<deadline:time.sleep(.001)
            self.assertFalse(buffer.busy);self.assertIsNone(buffer.take_failure())
            self.assertIs(self.capture._transport,transport)
            self.assertFalse(transport.revoked.is_set());time.sleep(.12)
        self.assertGreaterEqual(requests,5)
        self.assertEqual(self.spawn.call_count,1)
        self.assertEqual(self.process.kills,0)
        frame=buffer.take(scope)
        self.assertIsNotNone(frame)
        self.assertGreater(frame.captured_at,observation_at)
        # The consumer alone owns recognition timestamps; acquiring frames
        # neither creates an observation nor extends an existing display TTL.
        self.assertGreater(time.monotonic()-observation_at,.8)
        self.assertLess(time.monotonic()-frame.captured_at,.4)
        buffer.close();self.capture.close()
        self.assertTrue(transport.ready_for_replacement.wait(2))

if __name__=='__main__':unittest.main()
