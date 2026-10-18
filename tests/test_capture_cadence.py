import math
import unittest

from capture_cadence import next_capture_delay


class CaptureCadenceTests(unittest.TestCase):
    def test_fast_frames_keep_normal_idle(self):
        self.assertEqual(next_capture_delay(700, 1.2, dict(capture_ms=400,inference_ms=800)),700)

    def test_slow_frames_reserve_next_work_inside_original_deadline(self):
        delay=next_capture_delay(700,1.84,dict(capture_ms=350,inference_ms=1490))
        self.assertEqual(delay,136)
        self.assertLess(1.84+delay/1000+1.84,4)

    def test_impossible_budget_never_busy_loops_or_changes_ttl(self):
        for age in (2.5,3.9,4):
            self.assertEqual(next_capture_delay(700,age,dict(capture_ms=400,inference_ms=2100)),50)

    def test_bad_measurements_and_missing_observation_are_bounded(self):
        for age in (None,-1,math.inf,math.nan,5):
            self.assertEqual(next_capture_delay(700,age,{}),700)
        for timings in (None,{},dict(capture_ms='private',inference_ms=1),dict(capture_ms=1,inference_ms=math.nan)):
            self.assertEqual(next_capture_delay(700,3.9,timings),50)

    def test_base_early_confirmation_cadence_is_never_slowed(self):
        self.assertEqual(next_capture_delay(200,.5,dict(capture_ms=100,inference_ms=400)),200)
